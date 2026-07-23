"""
OmniPath + SIGNOR 3.0 activity-flow ingestion for VOIDSIGNAL.

Fetches directed consensus interactions from the OmniPath REST API
(``https://omnipathdb.org/interactions``), tags enzymatic vs transcriptional
latency (τ), attaches AlphaFold / VCF structural disruption weights, and
exports ODE-ready :class:`~voidsignal.topology.SignalingNetwork` objects.

Offline: curated hypoxia + MAPK scaffolds keep demos / CI network-free.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode
import csv
import io
import logging

from voidsignal.components import KineticParameters, Protein, StructuralMetadata
from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.http_sync import http_get_text
from voidsignal.models.graph import (
    DDG_ACTIVITY_SLOPE,
    DDG_DESTABILIZATION_KCAL,
    TAU_ENZYMATIC_MIN,
    TAU_TRANSCRIPTIONAL_MIN,
    ActivityFlowEdge,
    AmbiguousEdge,
    CausalActivityGraph,
    GraphNode,
    MechanismKind,
    StructuralDisruption,
)
from voidsignal.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)

OMNIPATH_INTERACTIONS_URL = "https://omnipathdb.org/interactions"
DEFAULT_DATASETS = ("omnipath", "signor")

# Post-translational / enzymatic mechanism tokens
_ENZYMATIC_TOKENS = frozenset(
    {
        "phosphorylation",
        "dephosphorylation",
        "ubiquitination",
        "acetylation",
        "methylation",
        "glycosylation",
        "cleavage",
        "enzymatic",
        "post_translational",
        "post-translational",
        "ptm",
        "kinase",
        "phosphatase",
    }
)

# Gene-regulatory / transcriptional tokens
_TRANSCRIPTIONAL_TOKENS = frozenset(
    {
        "transcription",
        "transcriptional",
        "transcriptional_regulation",
        "tf_target",
        "tfregulons",
        "dorothea",
        "gene_expression",
        "expression",
    }
)


# ---------------------------------------------------------------------------
# Structural disruption (Domain 3)
# ---------------------------------------------------------------------------


def activity_weight_from_ddg(
    delta_delta_g: Optional[float],
    *,
    ramachandran_outlier: bool = False,
) -> float:
    """
    Map structural destabilisation to functional capacity multiplier ``w_i``.

        w_i = max(0, 1 − 0.15 · ΔΔG)   if ΔΔG > 2.5 kcal/mol
                                         or Ramachandran outlier

    Otherwise ``w_i = 1.0`` (wild-type capacity).
    """
    if not ramachandran_outlier and (delta_delta_g is None or delta_delta_g <= DDG_DESTABILIZATION_KCAL):
        return 1.0
    ddg = float(delta_delta_g) if delta_delta_g is not None else DDG_DESTABILIZATION_KCAL
    return max(0.0, 1.0 - DDG_ACTIVITY_SLOPE * ddg)


def apply_structural_disruption(
    node: GraphNode,
    *,
    delta_delta_g: Optional[float] = None,
    ramachandran_outlier: bool = False,
    variant_hgvs: Optional[str] = None,
) -> GraphNode:
    """Attach structural disruption metrics and update ``activity_weight`` / τ metadata."""
    w = activity_weight_from_ddg(delta_delta_g, ramachandran_outlier=ramachandran_outlier)
    structural = StructuralDisruption(
        gene_symbol=node.gene_symbol,
        variant_hgvs=variant_hgvs,
        delta_delta_g=delta_delta_g,
        ramachandran_outlier=ramachandran_outlier,
        activity_weight=w,
    )
    meta = dict(node.metadata)
    meta["structure_disruption"] = 1.0 - w
    return node.model_copy(
        update={
            "activity_weight": w,
            "structural": structural,
            "metadata": meta,
        }
    )


# ---------------------------------------------------------------------------
# Mechanism / latency tagging
# ---------------------------------------------------------------------------


def classify_mechanism(
    consensus_modification: Optional[str] = None,
    *,
    interaction_type: Optional[str] = None,
    sources: Optional[Sequence[str]] = None,
) -> MechanismKind:
    """Tag enzymatic (τ=1 min) vs transcriptional (τ=120 min) latency class."""
    blob = " ".join(
        filter(
            None,
            [
                (consensus_modification or "").lower().replace("-", "_"),
                (interaction_type or "").lower().replace("-", "_"),
                " ".join(s.lower() for s in (sources or [])),
            ],
        )
    )
    tokens = set(blob.replace("/", " ").replace(";", " ").split())
    if tokens & _TRANSCRIPTIONAL_TOKENS or "tf_" in blob or "dorothea" in blob:
        return MechanismKind.TRANSCRIPTIONAL
    if tokens & _ENZYMATIC_TOKENS:
        return MechanismKind.ENZYMATIC
    # Default: directed protein activity flow → enzymatic timescale
    return MechanismKind.ENZYMATIC


def tau_for_mechanism(mechanism: MechanismKind) -> float:
    if mechanism is MechanismKind.TRANSCRIPTIONAL:
        return TAU_TRANSCRIPTIONAL_MIN
    return TAU_ENZYMATIC_MIN


# ---------------------------------------------------------------------------
# OmniPath REST fetch + parse
# ---------------------------------------------------------------------------


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in {"1", "true", "t", "yes", "y"}


def _parse_tsv(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return [dict(row) for row in reader]


def build_omnipath_query(
    *,
    datasets: Sequence[str] = DEFAULT_DATASETS,
    genes: Optional[Sequence[str]] = None,
    organisms: int = 9606,
) -> str:
    """Construct OmniPath interactions URL (genesymbols, directed consensus fields)."""
    fields = [
        "type",
        "is_directed",
        "is_stimulation",
        "is_inhibition",
        "consensus_direction",
        "consensus_stimulation",
        "consensus_inhibition",
        "sources",
        "references",
        "curation_effort",
    ]
    params: Dict[str, str] = {
        "genesymbols": "1",
        "datasets": ",".join(datasets),
        "organisms": str(organisms),
        "fields": ",".join(fields),
    }
    if genes:
        params["partners"] = ",".join(sorted({g.strip() for g in genes if g.strip()}))
    return f"{OMNIPATH_INTERACTIONS_URL}/?{urlencode(params)}"


def parse_activity_flow_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    graph_name: str = "omnipath_signor",
) -> CausalActivityGraph:
    """
    Convert OmniPath TSV/JSON-like rows into a signed causal activity graph.

    Keeps only directed edges with unambiguous stimulation XOR inhibition.
    Ambiguous / undirected rows are collected under ``ambiguous``.
    """
    edges: List[ActivityFlowEdge] = []
    ambiguous: List[AmbiguousEdge] = []
    nodes: Dict[str, GraphNode] = {}

    for row in rows:
        source = str(row.get("source_genesymbol") or row.get("source") or "").strip()
        target = str(row.get("target_genesymbol") or row.get("target") or "").strip()
        if not source or not target or source == target:
            continue

        is_directed = _truthy(row.get("is_directed", row.get("consensus_direction", 1)))
        # Prefer consensus stimulation/inhibition when present
        stim = _truthy(row.get("consensus_stimulation", row.get("is_stimulation", 0)))
        inhib = _truthy(row.get("consensus_inhibition", row.get("is_inhibition", 0)))
        # Fall back to non-consensus flags if consensus empty
        if not stim and not inhib:
            stim = _truthy(row.get("is_stimulation", 0))
            inhib = _truthy(row.get("is_inhibition", 0))

        mod = row.get("consensus_modification") or row.get("type") or row.get("modification")
        mod_s = str(mod).strip() if mod not in (None, "") else None
        sources_raw = str(row.get("sources") or row.get("source_databases") or "")
        source_list = [s.strip() for s in sources_raw.replace(";", ",").split(",") if s.strip()]
        datasets = []
        if "SIGNOR" in sources_raw.upper() or "signor" in (row.get("datasets") or "").lower():
            datasets.append("signor")
        if "OmniPath" in sources_raw or "omnipath" in (row.get("datasets") or "").lower():
            datasets.append("omnipath")

        if not is_directed:
            ambiguous.append(
                AmbiguousEdge(
                    source=source,
                    target=target,
                    reason="not_directed",
                    is_directed=False,
                    is_stimulation=stim,
                    is_inhibition=inhib,
                    consensus_modification=mod_s,
                    raw=dict(row),
                )
            )
            continue

        if stim == inhib:
            reason = "both_stimulation_and_inhibition" if stim and inhib else "unsigned_directed"
            ambiguous.append(
                AmbiguousEdge(
                    source=source,
                    target=target,
                    reason=reason,
                    is_directed=True,
                    is_stimulation=stim,
                    is_inhibition=inhib,
                    consensus_modification=mod_s,
                    raw=dict(row),
                )
            )
            continue

        sign: int = 1 if stim else -1
        mechanism = classify_mechanism(mod_s, interaction_type=str(row.get("type") or ""), sources=source_list)
        try:
            edge = ActivityFlowEdge(
                source=source,
                target=target,
                sign=sign,  # type: ignore[arg-type]
                is_stimulation=stim,
                is_inhibition=inhib,
                consensus_modification=mod_s,
                mechanism=mechanism,
                sources=source_list,
                datasets=datasets or list(DEFAULT_DATASETS),
                metadata={"curation_effort": row.get("curation_effort")},
            )
        except Exception as exc:
            ambiguous.append(
                AmbiguousEdge(
                    source=source,
                    target=target,
                    reason=f"schema_reject:{exc}",
                    is_directed=True,
                    is_stimulation=stim,
                    is_inhibition=inhib,
                    consensus_modification=mod_s,
                    raw=dict(row),
                )
            )
            continue
        edges.append(edge)

        for sym, role in ((source, "source"), (target, "target")):
            if sym not in nodes:
                nodes[sym] = GraphNode(gene_symbol=sym, tau_min=TAU_ENZYMATIC_MIN)
            if role == "target":
                # Target inherits latency from the strongest (largest τ) incoming mechanism
                tau = tau_for_mechanism(mechanism)
                if tau >= nodes[sym].tau_min:
                    nodes[sym] = nodes[sym].model_copy(update={"tau_min": tau})

    return CausalActivityGraph(
        name=graph_name,
        nodes=nodes,
        edges=edges,
        ambiguous=ambiguous,
        provenance={"parser": "voidsignal.data.omnipath", "n_input_rows": len(rows)},
    )


class OmniPathClient:
    """
    Zero-key OmniPath / SIGNOR activity-flow fetcher with disk cache + offline fallback.
    """

    def __init__(self, cache: Optional[IntegrationCache] = None, *, timeout: float = 45.0) -> None:
        self.cache = cache or IntegrationCache()
        self.timeout = float(timeout)

    def fetch_interactions(
        self,
        *,
        datasets: Sequence[str] = DEFAULT_DATASETS,
        genes: Optional[Sequence[str]] = None,
        organisms: int = 9606,
        use_cache: bool = True,
    ) -> CausalActivityGraph:
        """
        Query OmniPath for directed consensus activity-flow edges.

        Falls back to curated offline MAPK rows when the network is unreachable.
        """
        cache_key = f"{','.join(datasets)}|{organisms}|{','.join(sorted(genes or []))}"
        if use_cache:
            cached = self.cache.get_json("omnipath", cache_key)
            if isinstance(cached, dict) and "edges" in cached:
                return CausalActivityGraph.model_validate(cached)

        url = build_omnipath_query(datasets=datasets, genes=genes, organisms=organisms)
        text = http_get_text(url, timeout=self.timeout, accept="text/tab-separated-values, text/plain, */*")
        if text and "source" in text.splitlines()[0].lower():
            rows = _parse_tsv(text)
            graph = parse_activity_flow_rows(rows, graph_name="omnipath_signor_live")
            graph.provenance.update({"url": url, "source": "omnipath-live", "n_rows": len(rows)})
            if use_cache:
                self.cache.set_json("omnipath", cache_key, graph.model_dump(mode="json"))
            return graph

        logger.warning("OmniPath unreachable — using offline MAPK activity-flow scaffold")
        graph = offline_mapk_activity_graph()
        graph.provenance["fallback"] = "offline_mapk"
        return graph


# ---------------------------------------------------------------------------
# Hypoxia preset + offline MAPK
# ---------------------------------------------------------------------------


def hypoxia_network_preset() -> CausalActivityGraph:
    """
    Canonical hypoxia signalling scaffold:

        O2 → EGLN1 ⊣ HIF1A → VEGFA
        HIF1A → GLUT1
        HIF1A → EGLN1   (transcriptional feedback)
        MTOR → HIF1A

    Note: systems-biology texts sometimes write ``O2 ⊣ EGLN1`` for the
    *hypoxic* (low-O2) condition; the causal edge used for ODE kinetics is
    oxygen *stimulating* EGLN1 hydroxylase activity (high O2 ⇒ HIF1A off).
    """
    raw_edges: List[Tuple[str, str, int, str, MechanismKind]] = [
        ("O2", "EGLN1", 1, "oxygen_activation", MechanismKind.ENZYMATIC),
        ("EGLN1", "HIF1A", -1, "hydroxylation", MechanismKind.ENZYMATIC),
        ("HIF1A", "VEGFA", 1, "transcription", MechanismKind.TRANSCRIPTIONAL),
        ("HIF1A", "GLUT1", 1, "transcription", MechanismKind.TRANSCRIPTIONAL),
        ("HIF1A", "EGLN1", 1, "transcription", MechanismKind.TRANSCRIPTIONAL),
        ("MTOR", "HIF1A", 1, "phosphorylation", MechanismKind.ENZYMATIC),
    ]
    nodes: Dict[str, GraphNode] = {}
    edges: List[ActivityFlowEdge] = []
    for src, tgt, sign, mod, mech in raw_edges:
        edges.append(
            ActivityFlowEdge(
                source=src,
                target=tgt,
                sign=sign,  # type: ignore[arg-type]
                is_stimulation=sign == 1,
                is_inhibition=sign == -1,
                consensus_modification=mod,
                mechanism=mech,
                sources=["VOIDSIGNAL-hypoxia-preset"],
                datasets=["synthetic"],
            )
        )
        for sym in (src, tgt):
            if sym not in nodes:
                nodes[sym] = GraphNode(
                    gene_symbol=sym,
                    tau_min=tau_for_mechanism(mech) if sym == tgt else TAU_ENZYMATIC_MIN,
                    initial_concentration=0.55 if sym == "O2" else 0.35,
                )
            elif sym == tgt:
                tau = tau_for_mechanism(mech)
                if tau > nodes[sym].tau_min:
                    nodes[sym] = nodes[sym].model_copy(update={"tau_min": tau})

    return CausalActivityGraph(
        name="hypoxia_preset",
        nodes=nodes,
        edges=edges,
        ambiguous=[],
        provenance={
            "preset": "hypoxia",
            "topology": "O2→EGLN1⊣HIF1A→VEGFA/GLUT1; HIF1A→EGLN1; MTOR→HIF1A",
        },
    )


def offline_mapk_activity_graph() -> CausalActivityGraph:
    """Small directed MAPK activity-flow scaffold for offline / CI use."""
    rows = [
        {"source": "EGF", "target": "EGFR", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "0", "type": "post_translational"},
        {"source": "EGFR", "target": "KRAS", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "0", "type": "post_translational"},
        {"source": "KRAS", "target": "BRAF", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "0", "type": "post_translational"},
        {"source": "BRAF", "target": "MAP2K1", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "0", "type": "phosphorylation", "consensus_modification": "phosphorylation"},
        {"source": "MAP2K1", "target": "MAPK1", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "0", "type": "phosphorylation", "consensus_modification": "phosphorylation"},
        {"source": "MAPK1", "target": "FOS", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "0", "type": "transcriptional_regulation"},
        # Ambiguous on purpose for review pipeline
        {"source": "SRC", "target": "EGFR", "is_directed": "1", "is_stimulation": "1", "is_inhibition": "1", "type": "phosphorylation"},
        {"source": "GRB2", "target": "SOS1", "is_directed": "0", "is_stimulation": "1", "is_inhibition": "0", "type": "binding"},
    ]
    graph = parse_activity_flow_rows(rows, graph_name="offline_mapk")
    graph.provenance["source"] = "offline"
    return graph


# ---------------------------------------------------------------------------
# ODE materialisation
# ---------------------------------------------------------------------------


def _interaction_type_for_edge(edge: ActivityFlowEdge) -> InteractionType:
    mod = (edge.consensus_modification or "").lower()
    if edge.mechanism is MechanismKind.TRANSCRIPTIONAL:
        return InteractionType.TRANSCRIPTION if edge.sign > 0 else InteractionType.INHIBITION
    if "phospho" in mod:
        return InteractionType.PHOSPHORYLATION if edge.sign > 0 else InteractionType.DEPHOSPHORYLATION
    if "ubiquit" in mod:
        return InteractionType.UBIQUITINATION
    return InteractionType.ACTIVATION if edge.sign > 0 else InteractionType.INHIBITION


def to_signaling_network(graph: CausalActivityGraph) -> SignalingNetwork:
    """
    Format a :class:`CausalActivityGraph` as an ODE-ready :class:`SignalingNetwork`.

    * ``tau_min`` → ``metadata['tau_min']`` and scales degradation timescale
    * ``activity_weight`` → ``structure.disruption_delta = 1 − w_i`` and basal gate
    """
    net = SignalingNetwork(name=graph.name)
    id_map: Dict[str, str] = {}

    for sym, node in graph.nodes.items():
        w = float(node.activity_weight)
        delta = max(0.0, min(1.0, 1.0 - w))
        # Map τ to a soft degradation prior (faster enzymatic nodes clear quicker)
        k_deg = 0.05 * (TAU_ENZYMATIC_MIN / max(node.tau_min, 1e-6))
        protein = Protein(
            name=sym,
            gene_symbol=sym,
            concentration=float(node.initial_concentration) * w,
            kinetics=KineticParameters(
                degradation_rate=max(0.005, min(0.5, k_deg)),
                production_rate=0.02 * w,
                basal_activity=max(0.0, min(1.0, 0.05 * w)),
            ),
            structure=StructuralMetadata(disruption_delta=delta),
            pathway_membership=[graph.name],
            metadata={
                "tau_min": node.tau_min,
                "activity_weight": w,
                "structure_disruption": delta,
                **dict(node.metadata),
            },
        )
        if node.structural is not None:
            protein.metadata["delta_delta_g"] = node.structural.delta_delta_g
            protein.metadata["ramachandran_outlier"] = node.structural.ramachandran_outlier
            protein.metadata["variant_hgvs"] = node.structural.variant_hgvs
        nid = net.add_node(protein)
        id_map[sym] = nid

    for edge in graph.edges:
        src = id_map.get(edge.source)
        tgt = id_map.get(edge.target)
        if not src or not tgt:
            continue
        itype = _interaction_type_for_edge(edge)
        weight = 1.0 if edge.sign > 0 else 1.0
        net.connect(
            src,
            tgt,
            itype,
            weight=weight,
            rate_constant=1.0,
            metadata={
                "sign": edge.sign,
                "mechanism": edge.mechanism.value,
                "consensus_modification": edge.consensus_modification,
                "sources": list(edge.sources),
                "omnipath": True,
            },
        )

    net.annotate_pathway(graph.name, net.nodes())
    return net


def ingest_omnipath_for_ode(
    *,
    genes: Optional[Sequence[str]] = None,
    datasets: Sequence[str] = DEFAULT_DATASETS,
    disruptions: Optional[Mapping[str, Mapping[str, Any]]] = None,
    client: Optional[OmniPathClient] = None,
) -> Tuple[CausalActivityGraph, SignalingNetwork]:
    """
    End-to-end scaffold: fetch → sign-filter → attach ΔΔG weights → ODE network.
    """
    client = client or OmniPathClient()
    graph = client.fetch_interactions(datasets=datasets, genes=genes)
    if disruptions:
        for sym, payload in disruptions.items():
            key = sym.strip()
            if key not in graph.nodes:
                graph.nodes[key] = GraphNode(gene_symbol=key)
            graph.nodes[key] = apply_structural_disruption(
                graph.nodes[key],
                delta_delta_g=payload.get("delta_delta_g"),
                ramachandran_outlier=bool(payload.get("ramachandran_outlier", False)),
                variant_hgvs=payload.get("variant_hgvs"),
            )
    return graph, to_signaling_network(graph)


__all__ = [
    "DEFAULT_DATASETS",
    "OMNIPATH_INTERACTIONS_URL",
    "OmniPathClient",
    "activity_weight_from_ddg",
    "apply_structural_disruption",
    "build_omnipath_query",
    "classify_mechanism",
    "hypoxia_network_preset",
    "ingest_omnipath_for_ode",
    "offline_mapk_activity_graph",
    "parse_activity_flow_rows",
    "tau_for_mechanism",
    "to_signaling_network",
]
