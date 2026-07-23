"""
Dynamic biological condition → causal network resolver.

Parses free-text disease / stress / drug queries, expands seed genes via
OmniPath (when reachable) or a curated local interaction bank, and returns a
signed :class:`CausalActivityGraph` with τ tags and default stress clamps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import asyncio
import logging
import re
import time

from voidsignal.data.omnipath import (
    OmniPathClient,
    hypoxia_network_preset,
    offline_mapk_activity_graph,
    parse_activity_flow_rows,
    tau_for_mechanism,
)
from voidsignal.models.graph import (
    TAU_ENZYMATIC_MIN,
    TAU_TRANSCRIPTIONAL_MIN,
    ActivityFlowEdge,
    CausalActivityGraph,
    GraphNode,
    MechanismKind,
)

logger = logging.getLogger(__name__)

# Hard guardrails for interactive Studio / search-and-simulate latency.
EXTERNAL_HTTP_TIMEOUT_S = 2.0
# Wall-clock budget for ALL parallel fetches (must leave room for ODE <1.5s).
INTERACTIVE_FETCH_BUDGET_S = 0.45
MAX_TOPOLOGY_NODES = 30
MAX_FETCH_CONCURRENCY = 4
MAX_FUSED_EDGES = 60

# (source, target, sign, mechanism_token)
EdgeSpec = Tuple[str, str, int, str]


@dataclass
class ConditionProfile:
    """Curated seed library for one biological condition family."""

    id: str
    keywords: Tuple[str, ...]
    seed_genes: Tuple[str, ...]
    trigger_nodes: Tuple[str, ...]
    readout_nodes: Tuple[str, ...]
    default_clamps: Dict[str, float]
    local_edges: Tuple[EdgeSpec, ...]
    description: str = ""


@dataclass
class ResolvedCondition:
    """Fully assembled condition network ready for Hill-cube simulation."""

    query: str
    profile_id: str
    graph: CausalActivityGraph
    default_clamps: Dict[str, float]
    source_node: str
    target_node: str
    seed_genes: List[str]
    provenance: Dict[str, Any] = field(default_factory=dict)
    resolve_ms: float = 0.0


# ---------------------------------------------------------------------------
# Curated condition libraries (offline / sub-second path)
# ---------------------------------------------------------------------------

_CONDITION_LIBRARY: Tuple[ConditionProfile, ...] = (
    ConditionProfile(
        id="hypoxia",
        keywords=("hypoxia", "angiogenesis", "hif", "oxygen", "vegf", "ischemia"),
        seed_genes=("O2", "EGLN1", "HIF1A", "VEGFA", "GLUT1", "MTOR"),
        trigger_nodes=("O2",),
        readout_nodes=("VEGFA", "GLUT1"),
        default_clamps={"O2": 0.0},
        local_edges=(
            ("O2", "EGLN1", 1, "enzymatic"),
            ("EGLN1", "HIF1A", -1, "enzymatic"),
            ("HIF1A", "VEGFA", 1, "transcriptional"),
            ("HIF1A", "GLUT1", 1, "transcriptional"),
            ("HIF1A", "EGLN1", 1, "transcriptional"),
            ("MTOR", "HIF1A", 1, "enzymatic"),
        ),
        description="Hypoxia-induced angiogenesis / HIF metabolic program",
    ),
    ConditionProfile(
        id="alzheimers",
        keywords=(
            "alzheimer",
            "amyloid",
            "neuroinflam",
            "tauopath",
            "abeta",
            "a-beta",
            "neurodegener",
        ),
        seed_genes=("APP", "BACE1", "PSEN1", "MAPT", "TNF", "IL1B", "NFKB1", "ROS", "GSK3B"),
        trigger_nodes=("APP", "ROS"),
        readout_nodes=("TNF", "IL1B", "NFKB1"),
        default_clamps={"APP": 1.0, "ROS": 0.85},
        local_edges=(
            ("APP", "BACE1", 1, "enzymatic"),
            ("BACE1", "PSEN1", 1, "enzymatic"),
            ("PSEN1", "MAPT", 1, "enzymatic"),
            ("ROS", "NFKB1", 1, "enzymatic"),
            ("MAPT", "GSK3B", 1, "enzymatic"),
            ("GSK3B", "NFKB1", 1, "enzymatic"),
            ("NFKB1", "TNF", 1, "transcriptional"),
            ("NFKB1", "IL1B", 1, "transcriptional"),
            ("TNF", "NFKB1", 1, "enzymatic"),
            ("IL1B", "NFKB1", 1, "enzymatic"),
            ("ROS", "MAPT", 1, "enzymatic"),
        ),
        description="Alzheimer amyloid / ROS → neuroinflammatory cascade",
    ),
    ConditionProfile(
        id="tnbc_egfr",
        keywords=(
            "triple-negative",
            "tnbc",
            "breast cancer",
            "egfr",
            "her2",
            "resistance",
            "survival",
        ),
        seed_genes=("EGF", "EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1", "PIK3CA", "AKT1", "MYC"),
        trigger_nodes=("EGF",),
        readout_nodes=("MAPK1", "MYC", "AKT1"),
        default_clamps={"EGF": 1.0},
        local_edges=(
            ("EGF", "EGFR", 1, "enzymatic"),
            ("EGFR", "KRAS", 1, "enzymatic"),
            ("KRAS", "BRAF", 1, "enzymatic"),
            ("BRAF", "MAP2K1", 1, "enzymatic"),
            ("MAP2K1", "MAPK1", 1, "enzymatic"),
            ("MAPK1", "MYC", 1, "transcriptional"),
            ("EGFR", "PIK3CA", 1, "enzymatic"),
            ("PIK3CA", "AKT1", 1, "enzymatic"),
            ("AKT1", "MYC", 1, "transcriptional"),
        ),
        description="TNBC / EGFR survival and MAPK–PI3K crosstalk",
    ),
    ConditionProfile(
        id="dna_damage",
        keywords=("dna damage", "radiation", "p53", "tp53", "ddr", "genotoxic", "atm"),
        seed_genes=("ATM", "ATR", "CHEK1", "CHEK2", "TP53", "CDKN1A", "BAX", "MDM2"),
        trigger_nodes=("ATM",),
        readout_nodes=("CDKN1A", "BAX"),
        default_clamps={"ATM": 1.0},
        local_edges=(
            ("ATM", "CHEK2", 1, "enzymatic"),
            ("ATR", "CHEK1", 1, "enzymatic"),
            ("CHEK2", "TP53", 1, "enzymatic"),
            ("CHEK1", "TP53", 1, "enzymatic"),
            ("TP53", "CDKN1A", 1, "transcriptional"),
            ("TP53", "BAX", 1, "transcriptional"),
            ("TP53", "MDM2", 1, "transcriptional"),
            ("MDM2", "TP53", -1, "enzymatic"),
        ),
        description="DNA-damage response through ATM/ATR → p53 outputs",
    ),
    ConditionProfile(
        id="glaucoma_oxidative",
        keywords=("glaucoma", "oxidative", "ros", "retina", "ocular", "iop"),
        seed_genes=("ROS", "NRF2", "KEAP1", "HMOX1", "SOD2", "TNF", "NFKB1"),
        trigger_nodes=("ROS",),
        readout_nodes=("HMOX1", "TNF"),
        default_clamps={"ROS": 1.0},
        local_edges=(
            ("ROS", "KEAP1", -1, "enzymatic"),
            ("KEAP1", "NRF2", -1, "enzymatic"),
            ("NRF2", "HMOX1", 1, "transcriptional"),
            ("NRF2", "SOD2", 1, "transcriptional"),
            ("ROS", "NFKB1", 1, "enzymatic"),
            ("NFKB1", "TNF", 1, "transcriptional"),
        ),
        description="Glaucoma / ocular oxidative stress and NRF2 vs NF-κB",
    ),
    ConditionProfile(
        id="inflammation",
        keywords=("inflam", "tnf", "cytokine", "nfkb", "lps", "sepsis"),
        seed_genes=("LPS", "TLR4", "MYD88", "NFKB1", "TNF", "IL6", "IL1B"),
        trigger_nodes=("LPS",),
        readout_nodes=("TNF", "IL6"),
        default_clamps={"LPS": 1.0},
        local_edges=(
            ("LPS", "TLR4", 1, "enzymatic"),
            ("TLR4", "MYD88", 1, "enzymatic"),
            ("MYD88", "NFKB1", 1, "enzymatic"),
            ("NFKB1", "TNF", 1, "transcriptional"),
            ("NFKB1", "IL6", 1, "transcriptional"),
            ("NFKB1", "IL1B", 1, "transcriptional"),
            ("TNF", "NFKB1", 1, "enzymatic"),
        ),
        description="Innate inflammatory TLR4 → NF-κB cytokine program",
    ),
    ConditionProfile(
        id="mapk",
        keywords=("mapk", "erk", "egf", "ras", "raf", "mek"),
        seed_genes=("EGF", "EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1", "FOS"),
        trigger_nodes=("EGF",),
        readout_nodes=("MAPK1", "FOS"),
        default_clamps={"EGF": 0.85},
        local_edges=(
            ("EGF", "EGFR", 1, "enzymatic"),
            ("EGFR", "KRAS", 1, "enzymatic"),
            ("KRAS", "BRAF", 1, "enzymatic"),
            ("BRAF", "MAP2K1", 1, "enzymatic"),
            ("MAP2K1", "MAPK1", 1, "enzymatic"),
            ("MAPK1", "FOS", 1, "transcriptional"),
        ),
        description="Canonical EGF → MAPK cascade",
    ),
    ConditionProfile(
        id="glioblastoma",
        keywords=(
            "glioblastoma",
            "gbm",
            "glioma",
            "brain tumor",
            "egfrviii",
            "egfr resistance",
        ),
        seed_genes=(
            "EGF",
            "EGFR",
            "PTEN",
            "PIK3CA",
            "AKT1",
            "MTOR",
            "KRAS",
            "BRAF",
            "MAP2K1",
            "MAPK1",
            "STAT3",
            "MYC",
        ),
        trigger_nodes=("EGF",),
        readout_nodes=("MYC", "STAT3", "MAPK1"),
        default_clamps={"EGF": 1.0},
        local_edges=(
            ("EGF", "EGFR", 1, "enzymatic"),
            ("EGFR", "KRAS", 1, "enzymatic"),
            ("KRAS", "BRAF", 1, "enzymatic"),
            ("BRAF", "MAP2K1", 1, "enzymatic"),
            ("MAP2K1", "MAPK1", 1, "enzymatic"),
            ("MAPK1", "MYC", 1, "transcriptional"),
            ("EGFR", "PIK3CA", 1, "enzymatic"),
            ("PIK3CA", "AKT1", 1, "enzymatic"),
            ("AKT1", "MTOR", 1, "enzymatic"),
            ("MTOR", "MYC", 1, "transcriptional"),
            ("PTEN", "PIK3CA", -1, "enzymatic"),
            ("EGFR", "STAT3", 1, "enzymatic"),
            ("STAT3", "MYC", 1, "transcriptional"),
        ),
        description="Glioblastoma EGFR resistance / PI3K–MAPK survival program",
    ),
)


def _normalize_query(query: str) -> str:
    q = query.strip().lower()
    q = q.replace("’", "'").replace("–", "-").replace("—", "-")
    q = re.sub(r"[^a-z0-9+\-./\s]", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def match_condition_profile(query: str) -> ConditionProfile:
    """Score curated profiles by keyword overlap; default to hypoxia."""
    q = _normalize_query(query)
    best: Optional[ConditionProfile] = None
    best_score = 0
    for profile in _CONDITION_LIBRARY:
        score = 0
        for kw in profile.keywords:
            if kw in q:
                score += 2 if len(kw) > 4 else 1
        # gene symbol hits
        for gene in profile.seed_genes:
            if re.search(rf"\b{re.escape(gene.lower())}\b", q):
                score += 3
        if score > best_score:
            best_score = score
            best = profile
    if best is None or best_score == 0:
        # free-text gene tokens as soft hypoxia fallback with mapk if egf-like
        if any(tok in q for tok in ("egfr", "ras", "erk", "cancer")):
            return next(p for p in _CONDITION_LIBRARY if p.id == "tnbc_egfr")
        return next(p for p in _CONDITION_LIBRARY if p.id == "hypoxia")
    return best


def _mechanism_kind(token: str) -> MechanismKind:
    t = token.lower()
    if "transcri" in t or "tf" in t or "expression" in t:
        return MechanismKind.TRANSCRIPTIONAL
    return MechanismKind.ENZYMATIC


def graph_from_edge_specs(
    edges: Sequence[EdgeSpec],
    *,
    name: str,
    initial: Optional[Mapping[str, float]] = None,
) -> CausalActivityGraph:
    """Assemble a signed CausalActivityGraph with τ tagging."""
    nodes: Dict[str, GraphNode] = {}
    flow: List[ActivityFlowEdge] = []
    init = {k.upper() if False else k: float(v) for k, v in (initial or {}).items()}

    for src, tgt, sign, mech_tok in edges:
        mech = _mechanism_kind(mech_tok)
        flow.append(
            ActivityFlowEdge(
                source=src,
                target=tgt,
                sign=1 if sign >= 0 else -1,  # type: ignore[arg-type]
                is_stimulation=sign >= 0,
                is_inhibition=sign < 0,
                consensus_modification=mech_tok,
                mechanism=mech,
                sources=["voidsignal-resolver"],
                datasets=["local_expansion"],
            )
        )
        for sym in (src, tgt):
            if sym not in nodes:
                nodes[sym] = GraphNode(
                    gene_symbol=sym,
                    tau_min=TAU_ENZYMATIC_MIN,
                    initial_concentration=float(init.get(sym, 0.35)),
                )
        tau = tau_for_mechanism(mech)
        if tau > nodes[tgt].tau_min:
            nodes[tgt] = nodes[tgt].model_copy(update={"tau_min": tau})

    return CausalActivityGraph(
        name=name,
        nodes=nodes,
        edges=flow,
        ambiguous=[],
        provenance={"builder": "resolver.graph_from_edge_specs"},
    )


def local_network_expansion(
    profile: ConditionProfile,
    *,
    extra_genes: Optional[Iterable[str]] = None,
) -> CausalActivityGraph:
    """
    Expand a condition profile into a causal graph using the curated edge bank.

    Extra gene symbols (from the query text) are attached as copy-nodes linked
    from the primary trigger when no curated edges exist — keeps the ODE stable.
    """
    edge_set: Dict[Tuple[str, str], EdgeSpec] = {}
    for e in profile.local_edges:
        edge_set[(e[0], e[1])] = e

    # Pull related library edges that touch seed neighborhood (1-hop expand)
    seeds = set(profile.seed_genes) | set(extra_genes or [])
    for other in _CONDITION_LIBRARY:
        for e in other.local_edges:
            if e[0] in seeds or e[1] in seeds:
                edge_set.setdefault((e[0], e[1]), e)

    graph = graph_from_edge_specs(
        list(edge_set.values()),
        name=f"condition_{profile.id}",
        initial={n: 0.55 for n in profile.trigger_nodes},
    )
    # Ensure all seeds exist even if isolated
    nodes = dict(graph.nodes)
    for sym in seeds:
        if sym not in nodes:
            nodes[sym] = GraphNode(
                gene_symbol=sym,
                tau_min=TAU_ENZYMATIC_MIN,
                initial_concentration=0.35,
            )
    # Soft-link orphan extras from primary trigger so ODE has a path
    edges = list(graph.edges)
    trigger = profile.trigger_nodes[0] if profile.trigger_nodes else next(iter(nodes))
    connected = {e.source for e in edges} | {e.target for e in edges}
    for sym in seeds:
        if sym not in connected and sym != trigger and trigger in nodes:
            edges.append(
                ActivityFlowEdge(
                    source=trigger,
                    target=sym,
                    sign=1,
                    is_stimulation=True,
                    is_inhibition=False,
                    consensus_modification="inferred_coupling",
                    mechanism=MechanismKind.ENZYMATIC,
                    sources=["voidsignal-resolver"],
                    datasets=["inferred"],
                )
            )
    return CausalActivityGraph(
        name=graph.name,
        nodes=nodes,
        edges=edges,
        ambiguous=[],
        provenance={
            "builder": "local_network_expansion",
            "profile": profile.id,
            "n_seeds": len(seeds),
        },
    )


def _extract_gene_tokens(query: str) -> List[str]:
    """Pull ALLCAPS-like / known gene tokens from free text."""
    known: Set[str] = set()
    for p in _CONDITION_LIBRARY:
        known.update(p.seed_genes)
    q = query.upper()
    found: List[str] = []
    for g in sorted(known, key=len, reverse=True):
        if re.search(rf"\b{re.escape(g.upper())}\b", q):
            found.append(g)
    # Generic token: 2–8 letter gene-like words
    for tok in re.findall(r"\b[A-Z][A-Z0-9]{1,7}\b", query.upper()):
        if tok not in found and tok not in {"AND", "OR", "THE", "DNA", "RNA", "ROS"}:
            # keep ROS explicitly
            pass
        if tok == "ROS" and "ROS" not in found:
            found.append("ROS")
        elif tok in known and tok not in found:
            found.append(tok)
    return found


def _merge_omnipath(
    base: CausalActivityGraph,
    live: CausalActivityGraph,
    *,
    max_edges: int = 40,
) -> CausalActivityGraph:
    """Union live OmniPath edges that touch the base node set (capped)."""
    base_nodes = set(base.nodes.keys())
    nodes = dict(base.nodes)
    edges = list(base.edges)
    seen = {(e.source, e.target, e.sign) for e in edges}
    added = 0
    for e in live.edges:
        if added >= max_edges:
            break
        if e.source not in base_nodes and e.target not in base_nodes:
            continue
        key = (e.source, e.target, e.sign)
        if key in seen:
            continue
        edges.append(e)
        seen.add(key)
        added += 1
        for sym in (e.source, e.target):
            if sym not in nodes:
                nodes[sym] = GraphNode(
                    gene_symbol=sym,
                    tau_min=TAU_TRANSCRIPTIONAL_MIN
                    if e.mechanism == MechanismKind.TRANSCRIPTIONAL
                    else TAU_ENZYMATIC_MIN,
                )
            elif e.target == sym:
                tau = tau_for_mechanism(e.mechanism)
                if tau > nodes[sym].tau_min:
                    nodes[sym] = nodes[sym].model_copy(update={"tau_min": tau})
    return CausalActivityGraph(
        name=base.name,
        nodes=nodes,
        edges=edges,
        ambiguous=list(base.ambiguous) + list(live.ambiguous),
        provenance={
            **dict(base.provenance or {}),
            "omnipath_merged": True,
            "omnipath_edges_added": added,
        },
    )


def resolve_condition_network(
    query: str = "",
    *,
    query_str: Optional[str] = None,
    use_omnipath: bool = True,
    omnipath_timeout: float = 0.8,
    client: Optional[OmniPathClient] = None,
) -> ResolvedCondition:
    """
    Parse a free-text biological condition and return a simulation-ready graph.

    Strategy
    --------
    1. Match curated condition profile (fast).
    2. Local edge-bank expansion around seed genes.
    3. Optionally enrich with OmniPath partners (short timeout); ignore on failure.
    """
    t0 = time.perf_counter()
    q = (query_str if query_str is not None else query).strip() or "hypoxia"
    profile = match_condition_profile(q)
    extras = _extract_gene_tokens(q)
    graph = local_network_expansion(profile, extra_genes=extras)

    provenance: Dict[str, Any] = {
        "query": q,
        "profile_id": profile.id,
        "description": profile.description,
        "source": "local_expansion",
        "extras": extras,
    }

    if use_omnipath:
        try:
            op = client or OmniPathClient(timeout=omnipath_timeout)
            # Bound the partner list for latency
            partners = list(dict.fromkeys([*profile.seed_genes, *extras]))[:12]
            live = op.fetch_interactions(genes=partners, use_cache=True)
            if live.edges and live.provenance.get("source") == "omnipath-live":
                graph = _merge_omnipath(graph, live)
                provenance["source"] = "local+omnipath"
                provenance["omnipath_nodes"] = len(live.nodes)
        except Exception as exc:  # pragma: no cover - network failures
            logger.info("OmniPath enrich skipped: %s", exc)
            provenance["omnipath_error"] = str(exc)

    # Prefer hypoxia/mapk presets when exact keyword match & no omnipath merge
    # for bit-identical demos (optional polish)
    if profile.id == "hypoxia" and provenance.get("source") == "local_expansion":
        # Use canonical hypoxia preset topology (already validated in tests)
        graph = hypoxia_network_preset()
        graph = graph.model_copy(
            update={
                "name": "condition_hypoxia",
                "provenance": {**dict(graph.provenance or {}), **provenance},
            }
        )
    elif profile.id == "mapk" and provenance.get("source") == "local_expansion":
        graph = offline_mapk_activity_graph()
        graph = graph.model_copy(
            update={
                "name": "condition_mapk",
                "provenance": {**dict(graph.provenance or {}), **provenance},
            }
        )

    clamps = dict(profile.default_clamps)
    source = profile.trigger_nodes[0]
    # Prefer a readout present in the graph
    target = next((r for r in profile.readout_nodes if r in graph.nodes), profile.readout_nodes[0])
    if source not in graph.nodes:
        source = sorted(graph.nodes.keys())[0]
    if target not in graph.nodes:
        target = sorted(graph.nodes.keys())[-1]

    graph.provenance = {**dict(graph.provenance or {}), **provenance}
    return ResolvedCondition(
        query=q,
        profile_id=profile.id,
        graph=graph,
        default_clamps=clamps,
        source_node=source,
        target_node=target,
        seed_genes=list(profile.seed_genes),
        provenance=provenance,
        resolve_ms=(time.perf_counter() - t0) * 1000.0,
    )


def list_condition_suggestions() -> List[Dict[str, str]]:
    """Quick-suggestion chips for the laboratory search bar."""
    return [
        {"label": "Hypoxia", "query": "Hypoxia-induced angiogenesis"},
        {"label": "Radiation DNA Damage", "query": "Radiation DNA Damage p53 response"},
        {"label": "Alzheimer's Amyloid Stress", "query": "Alzheimer's Amyloid Stress"},
        {"label": "EGFR Resistance", "query": "Glioblastoma EGFR resistance"},
        {"label": "Glaucoma Oxidative Stress", "query": "Glaucoma Oxidative Stress"},
        {"label": "Neuroinflammation", "query": "Alzheimer's Neuroinflammation"},
        {"label": "TNBC EGFR", "query": "Triple-negative breast cancer EGFR survival"},
        {"label": "Inflammation", "query": "LPS inflammatory cytokine storm"},
    ]


# ---------------------------------------------------------------------------
# Multi-source async aggregator (OmniPath / SIGNOR / KEGG / Reactome /
# STRING / BioGRID / UniProt) with offline cache fallback
# ---------------------------------------------------------------------------

OMNIPATH_INTERACTIONS_URL = "https://omnipathdb.org/interactions"
STRING_NETWORK_URL = "https://string-db.org/api/json/network"
UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"


def _confidence_score_1000(raw: Optional[float]) -> float:
    """Normalize evidence to STRING-style confidence Sᵢⱼ ∈ [0, 1000]."""
    if raw is None:
        return 600.0
    s = float(raw)
    if s <= 1.0:
        return max(0.0, min(1000.0, s * 1000.0))
    return max(0.0, min(1000.0, s))


def _attach_edge_provenance(
    edge: ActivityFlowEdge,
    *,
    source_tag: str,
    confidence: Optional[float] = None,
    pmids: Optional[Sequence[str]] = None,
) -> ActivityFlowEdge:
    """Stamp sources / confidence_score / pmid_citations onto an edge."""
    sources = list(dict.fromkeys([*(edge.sources or []), source_tag]))
    datasets = list(dict.fromkeys([*(edge.datasets or []), source_tag]))
    conf = _confidence_score_1000(
        confidence if confidence is not None else edge.evidence_score
    )
    meta = dict(edge.metadata or {})
    meta["confidence_score"] = conf
    prior = list(meta.get("pmid_citations") or [])
    for p in pmids or []:
        if p and p not in prior:
            prior.append(str(p))
    meta["pmid_citations"] = prior
    meta["sources"] = sources
    return edge.model_copy(
        update={
            "sources": sources,
            "datasets": datasets,
            "evidence_score": conf / 1000.0,
            "metadata": meta,
        }
    )


def _apply_kinetic_tau(graph: CausalActivityGraph) -> CausalActivityGraph:
    """
    Enforce latency tags:
      enzymatic / PTM → τ = 1.0 min
      gene-regulatory / transcriptional → τ = 120.0 min
    """
    nodes = dict(graph.nodes)
    new_edges: List[ActivityFlowEdge] = []
    for e in graph.edges:
        tau = tau_for_mechanism(e.mechanism)
        tgt = e.target
        if tgt not in nodes:
            nodes[tgt] = GraphNode(gene_symbol=tgt, tau_min=tau)
        elif tau > nodes[tgt].tau_min:
            nodes[tgt] = nodes[tgt].model_copy(update={"tau_min": tau})
        meta = dict(e.metadata or {})
        meta["tau_min"] = tau
        new_edges.append(e.model_copy(update={"metadata": meta}))
    return graph.model_copy(update={"nodes": nodes, "edges": new_edges})


def _clamp_http_timeout(timeout: Optional[float] = None) -> float:
    """Always enforce the 2s hard cutoff (never longer)."""
    if timeout is None:
        return EXTERNAL_HTTP_TIMEOUT_S
    return max(0.05, min(float(timeout), EXTERNAL_HTTP_TIMEOUT_S))


async def _aio_get_text(
    url: str,
    *,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """
    Async GET with a hard 2s cutoff.

    Prefer threaded sync HTTP (``http_get_text``) so Windows DNS / TLS cannot
    block the event loop — that hang was the infinite Studio loader. aiohttp
    remains as a secondary path with ``ClientTimeout(total=2.0)``.
    """
    cut = _clamp_http_timeout(timeout)

    def _sync_get() -> Optional[str]:
        from voidsignal.integrations.http_sync import http_get_text

        return http_get_text(url, timeout=cut)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync_get), timeout=cut + 0.05)
    except Exception as exc:
        logger.debug("threaded GET abort %s: %s", url, exc)

    try:
        import aiohttp

        client_timeout = aiohttp.ClientTimeout(
            total=cut,
            connect=cut,
            sock_connect=min(cut, 1.0),
            sock_read=cut,
        )
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(
                url,
                headers={"User-Agent": "VoidSignal-Resolver/0.22", "Accept": "*/*"},
            ) as resp:
                if resp.status >= 400:
                    return None
                return await resp.text()
    except Exception as exc:
        logger.debug("aiohttp GET abort %s: %s", url, exc)
        return None


async def _aio_get_json(url: str, *, timeout: Optional[float] = None) -> Any:
    text = await _aio_get_text(url, timeout=timeout)
    if not text:
        return None
    try:
        import json

        return json.loads(text)
    except Exception:
        return None


def trim_topology_to_top_nodes(
    graph: CausalActivityGraph,
    *,
    max_nodes: int = MAX_TOPOLOGY_NODES,
    protect: Optional[Sequence[str]] = None,
) -> CausalActivityGraph:
    """
    Cap topology to the top-N most connected / high-confidence nodes.

    Guarantees sub-second Kraeutler ODE solves by bounding state dimension.
    Protected seeds (triggers / readouts) are always retained when present.
    """
    if max_nodes <= 0 or len(graph.nodes) <= max_nodes:
        return graph

    degree: Dict[str, float] = {n: 0.0 for n in graph.nodes}
    conf_sum: Dict[str, float] = {n: 0.0 for n in graph.nodes}
    conf_n: Dict[str, int] = {n: 0 for n in graph.nodes}
    for e in graph.edges:
        for n in (e.source, e.target):
            if n not in degree:
                degree[n] = 0.0
                conf_sum[n] = 0.0
                conf_n[n] = 0
            degree[n] += 1.0
            conf = float((e.metadata or {}).get("confidence_score") or 0.0)
            if conf <= 0 and e.evidence_score is not None:
                conf = _confidence_score_1000(e.evidence_score)
            conf_sum[n] += conf
            conf_n[n] += 1

    def _score(n: str) -> Tuple[float, float, str]:
        avg_conf = (conf_sum[n] / conf_n[n]) if conf_n[n] else 0.0
        # Prefer hubs with multi-source confidence; stable tie-break by name.
        return (-(degree[n] * 1000.0 + avg_conf), -degree[n], n)

    must = {p for p in (protect or []) if p in graph.nodes}
    ranked = sorted(graph.nodes.keys(), key=_score)
    keep: List[str] = []
    for n in must:
        if n not in keep:
            keep.append(n)
    for n in ranked:
        if n in keep:
            continue
        keep.append(n)
        if len(keep) >= max_nodes:
            break
    keep_set = set(keep)

    edges = [e for e in graph.edges if e.source in keep_set and e.target in keep_set]
    # Drop isolates introduced by edge filtering (except protected).
    connected = {e.source for e in edges} | {e.target for e in edges} | must
    nodes = {n: graph.nodes[n] for n in keep if n in connected or n in must}
    if not nodes:
        # Degenerate trim — keep original top-ranked slice of nodes.
        nodes = {n: graph.nodes[n] for n in keep[:max_nodes] if n in graph.nodes}
        edges = [e for e in graph.edges if e.source in nodes and e.target in nodes]

    prov = dict(graph.provenance or {})
    prov["trimmed_to"] = len(nodes)
    prov["trim_max_nodes"] = max_nodes
    prov["trim_dropped"] = max(0, len(graph.nodes) - len(nodes))
    return graph.model_copy(update={"nodes": nodes, "edges": edges, "provenance": prov})


def _preset_fallback_graph(profile_id: str, query: str) -> CausalActivityGraph:
    """Circuit-breaker: load pre-compiled local cache from data.presets."""
    from voidsignal.data.presets import local_graph_cache

    return _apply_kinetic_tau(local_graph_cache(profile_id, query=query))


async def _fetch_omnipath_async(
    seeds: Sequence[str],
    *,
    timeout: float,
    include_signor: bool,
    allow_live: bool = False,
) -> List[ActivityFlowEdge]:
    """OmniPath (+ SIGNOR) interactions; disk cache first, optional live REST."""
    from voidsignal.data.omnipath import _parse_tsv, parse_activity_flow_rows
    from voidsignal.integrations.cache_store import IntegrationCache

    cut = _clamp_http_timeout(timeout)
    genes = list(dict.fromkeys(seeds))[:12]
    datasets = ("omnipath", "signor") if include_signor else ("omnipath",)
    cache = IntegrationCache()
    cache_key = f"op:{','.join(datasets)}:{','.join(sorted(g.upper() for g in genes))}"
    cached = cache.get_json("resolver_omnipath", cache_key)
    if isinstance(cached, list) and cached:
        edges: List[ActivityFlowEdge] = []
        for row in cached:
            try:
                e = ActivityFlowEdge.model_validate(row)
                edges.append(_attach_edge_provenance(e, source_tag="omnipath"))
            except Exception:
                continue
        return edges

    from voidsignal.data.omnipath import build_omnipath_query

    url = build_omnipath_query(datasets=datasets, genes=genes or None)
    # Live REST under hard 2s cutoff (threaded so DNS cannot block the loop).
    # Skip when allow_live=False — interactive Studio uses cache + local/presets
    # so cancelled to_thread workers cannot saturate the default executor.
    if not allow_live:
        logger.info("OmniPath cache miss — live REST skipped (allow_live=False)")
        return []

    text = await _aio_get_text(url, timeout=cut)
    if not (text and "source" in text.splitlines()[0].lower()):
        # Circuit open — never fall through to a long sync OmniPathClient call.
        logger.info("OmniPath REST abort/timeout (%.2fs) — empty batch", cut)
        return []

    rows = _parse_tsv(text)
    live = parse_activity_flow_rows(rows, graph_name="omnipath_signor_live")

    out: List[ActivityFlowEdge] = []
    rows_for_cache: List[Dict[str, Any]] = []
    for e in live.edges:
        tags = set(e.datasets or []) | set(e.sources or [])
        pmids: List[str] = []
        refs = (e.metadata or {}).get("references") or (e.metadata or {}).get(
            "pmid_citations"
        )
        if isinstance(refs, str):
            pmids = [p.strip() for p in re.split(r"[,;]", refs) if p.strip()]
        elif isinstance(refs, list):
            pmids = [str(p) for p in refs]
        stamped = _attach_edge_provenance(e, source_tag="omnipath", pmids=pmids)
        if include_signor and any("signor" in str(t).lower() for t in tags):
            stamped = _attach_edge_provenance(stamped, source_tag="signor")
        out.append(stamped)
        rows_for_cache.append(stamped.model_dump(mode="json"))
    if rows_for_cache:
        cache.set_json("resolver_omnipath", cache_key, rows_for_cache)
    return out


async def _fetch_string_async(
    seeds: Sequence[str],
    *,
    timeout: float,
) -> List[ActivityFlowEdge]:
    """STRING PPI with Sᵢⱼ ∈ [0, 1000]; offline / disk-cache only on hot path."""
    from voidsignal.integrations.cache_store import IntegrationCache
    from voidsignal.integrations.string_client import _OFFLINE_PPI

    genes = list(dict.fromkeys(seeds))[:10] or ["EGFR", "KRAS", "BRAF"]
    cache = IntegrationCache()
    cache_key = ",".join(sorted(g.upper() for g in genes))
    cached = cache.get_json("resolver_string", cache_key)
    pairs: List[Tuple[str, str, float]] = []
    if isinstance(cached, list) and cached:
        for row in cached:
            pairs.append((str(row["a"]), str(row["b"]), float(row["score"])))
    else:
        # Offline bank only on the interactive aggregator — live STRING REST
        # would burn the fetch budget when hypoxia seeds miss the PPI table.
        seed_u = {g.upper() for g in genes}
        for a, b, score in _OFFLINE_PPI:
            if seed_u and a.upper() not in seed_u and b.upper() not in seed_u:
                continue
            pairs.append((a, b, float(score) * 1000.0 if score <= 1 else float(score)))

    edges: List[ActivityFlowEdge] = []
    for a, b, score in pairs:
        conf = _confidence_score_1000(score)
        for src, tgt in ((a, b), (b, a)):
            edges.append(
                _attach_edge_provenance(
                    ActivityFlowEdge(
                        source=src,
                        target=tgt,
                        sign=1,
                        is_stimulation=True,
                        is_inhibition=False,
                        consensus_modification="ppi",
                        mechanism=MechanismKind.ENZYMATIC,
                        sources=["string"],
                        datasets=["string"],
                        evidence_score=conf / 1000.0,
                        metadata={
                            "confidence_score": conf,
                            "pmid_citations": [],
                            "sources": ["string"],
                        },
                    ),
                    source_tag="string",
                    confidence=conf,
                )
            )
    return edges


async def _fetch_uniprot_async(
    symbols: Sequence[str],
    *,
    timeout: float,
) -> Dict[str, Dict[str, Any]]:
    """UniProt IDs + localization; offline corpus first, live REST best-effort."""
    from voidsignal.integrations.cache_store import IntegrationCache
    from voidsignal.integrations.offline_data import OFFLINE_UNIPROT

    cut = _clamp_http_timeout(timeout)
    cache = IntegrationCache()
    meta: Dict[str, Dict[str, Any]] = {}
    for sym in list(symbols)[:24]:
        cached = cache.get_json("resolver_uniprot", sym.upper())
        if isinstance(cached, dict) and cached.get("uniprot_id"):
            meta[sym] = cached
            continue
        row = OFFLINE_UNIPROT.get(sym.upper()) or OFFLINE_UNIPROT.get(sym)
        if isinstance(row, dict):
            entry = {
                "uniprot_id": row.get("accession"),
                "localization": row.get("localization"),
                "full_name": row.get("full_name"),
                "function": row.get("function"),
                "pmid_citations": [],
                "sources": ["uniprot"],
                "confidence_score": 1000.0,
                "source": "uniprot-offline",
            }
            meta[sym] = entry
            cache.set_json("resolver_uniprot", sym.upper(), entry)
            continue
        # Live REST (hard 2s cutoff) — ignore failures / timeouts
        try:
            from urllib.parse import urlencode

            q = urlencode(
                {
                    "query": f"gene_exact:{sym} AND organism_id:9606",
                    "fields": "accession,gene_names,cc_subcellular_location,protein_name",
                    "format": "json",
                    "size": "1",
                }
            )
            payload = await _aio_get_json(
                f"{UNIPROT_SEARCH_URL}?{q}",
                timeout=cut,
            )
            results = (payload or {}).get("results") if isinstance(payload, dict) else None
            if results:
                hit = results[0]
                acc = hit.get("primaryAccession")
                locs = []
                for comment in hit.get("comments") or []:
                    if comment.get("commentType") == "SUBCELLULAR LOCATION":
                        for loc in comment.get("subcellularLocations") or []:
                            val = (loc.get("location") or {}).get("value")
                            if val:
                                locs.append(val)
                entry = {
                    "uniprot_id": acc,
                    "localization": "; ".join(locs) if locs else None,
                    "full_name": (
                        ((hit.get("proteinDescription") or {}).get("recommendedName") or {}).get(
                            "fullName"
                        )
                        or {}
                    ).get("value"),
                    "pmid_citations": [],
                    "sources": ["uniprot"],
                    "confidence_score": 1000.0,
                    "source": "uniprot-live",
                }
                meta[sym] = entry
                cache.set_json("resolver_uniprot", sym.upper(), entry)
        except Exception:
            continue
    return meta


def _load_topology_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    try:
        from voidsignal.integrations.cache_store import IntegrationCache

        hit = IntegrationCache().get_json("resolver_topology", cache_key)
        return hit if isinstance(hit, dict) else None
    except Exception:
        return None


def _store_topology_cache(cache_key: str, payload: Dict[str, Any]) -> None:
    try:
        from voidsignal.integrations.cache_store import IntegrationCache

        IntegrationCache().set_json("resolver_topology", cache_key, payload)
    except Exception:
        return


async def resolve_multisource_network_async(
    query_str: str = "",
    *,
    query: str = "",
    selected_sources: Optional[Sequence[str]] = None,
    use_omnipath: bool = True,
    timeout_per_source: float = EXTERNAL_HTTP_TIMEOUT_S,
) -> ResolvedCondition:
    """
    Asynchronous multi-source knowledge aggregation.

    External REST calls use ``aiohttp.ClientTimeout(total=2.0)``. Fetches run
    under ``asyncio.gather(..., return_exceptions=True)`` with a concurrency
    semaphore so one slow DB cannot block others. Topology is trimmed to
    ``MAX_TOPOLOGY_NODES`` (30). On external failure the pre-compiled local
    graph cache in ``voidsignal.data.presets`` is used.
    """
    from voidsignal.data import multisource as ms

    t0 = time.perf_counter()
    cut = _clamp_http_timeout(timeout_per_source)
    q = (query_str or query or "").strip() or "hypoxia"

    if selected_sources is None or (
        isinstance(selected_sources, Sequence) and len(list(selected_sources)) == 0
    ):
        sources = list(ms.ALL_SOURCES) if use_omnipath else ["local", "uniprot"]
    else:
        sources = ms.normalize_sources(selected_sources)

    if not use_omnipath:
        sources = [s for s in sources if s not in {"omnipath", "signor"}]
    if "local" not in sources:
        sources = ["local", *sources]

    profile = match_condition_profile(q)
    base = local_network_expansion(profile)
    seeds = list(profile.seed_genes)
    source_status: Dict[str, str] = {"local": "ok"}

    # ------------------------------------------------------------------
    # Fast offline path — no live REST (keeps CI / Explorer sub-second)
    # ------------------------------------------------------------------
    live_sources = [
        s for s in sources if s not in {"local", "uniprot"}
    ]
    if not live_sources:
        local_edges = [
            _attach_edge_provenance(
                e.model_copy(
                    update={
                        "sources": list(dict.fromkeys([*(e.sources or []), "local"])),
                        "datasets": list(dict.fromkeys([*(e.datasets or []), "local"])),
                    }
                ),
                source_tag="local",
                confidence=900.0,
            )
            for e in base.edges
        ]
        node_meta: Dict[str, Dict[str, Any]] = {}
        if "uniprot" in sources:
            from voidsignal.integrations.offline_data import OFFLINE_UNIPROT

            for sym in sorted({n for e in local_edges for n in (e.source, e.target)}):
                row = OFFLINE_UNIPROT.get(sym.upper()) or OFFLINE_UNIPROT.get(sym)
                if isinstance(row, dict):
                    node_meta[sym] = {
                        "uniprot_id": row.get("accession"),
                        "localization": row.get("localization"),
                        "full_name": row.get("full_name"),
                        "function": row.get("function"),
                        "pmid_citations": [],
                        "sources": ["uniprot"],
                        "confidence_score": 1000.0,
                        "source": "uniprot-offline",
                    }
            source_status["uniprot"] = "ok" if node_meta else "empty"

        # Canonical hypoxia/mapk demos when only local contributed
        fallback = resolve_condition_network(q, use_omnipath=False)
        graph = _apply_kinetic_tau(fallback.graph)
        if node_meta:
            nodes = dict(graph.nodes)
            for sym, meta in node_meta.items():
                if sym not in nodes:
                    nodes[sym] = GraphNode(
                        gene_symbol=sym, tau_min=TAU_ENZYMATIC_MIN
                    )
                merged = {**(nodes[sym].metadata or {}), **meta, "provenance": meta}
                nodes[sym] = nodes[sym].model_copy(update={"metadata": merged})
            graph = graph.model_copy(update={"nodes": nodes})
        source_status["fallback"] = "local_canonical"
        protect = list(profile.trigger_nodes) + list(profile.readout_nodes) + list(
            profile.seed_genes
        )
        graph = trim_topology_to_top_nodes(
            graph, max_nodes=MAX_TOPOLOGY_NODES, protect=protect
        )

        clamps = dict(profile.default_clamps)
        source_node = profile.trigger_nodes[0]
        target_node = next(
            (r for r in profile.readout_nodes if r in graph.nodes),
            profile.readout_nodes[0],
        )
        if source_node not in graph.nodes:
            source_node = sorted(graph.nodes.keys())[0]
        if target_node not in graph.nodes:
            target_node = sorted(graph.nodes.keys())[-1]

        provenance = {
            "query": q,
            "profile_id": profile.id,
            "selected_sources": sources,
            "source_status": source_status,
            "n_edges_fused": len(graph.edges),
            "n_nodes": len(graph.nodes),
            "builder": "resolve_multisource_network",
            "resolver": "voidsignal.data.resolver",
            "async": False,
            "mode": "offline_fast",
            "http_timeout_s": cut,
            "max_topology_nodes": MAX_TOPOLOGY_NODES,
        }
        graph.provenance = {**(graph.provenance or {}), **provenance}
        return ResolvedCondition(
            query=q,
            profile_id=profile.id,
            graph=graph,
            default_clamps=clamps,
            source_node=source_node,
            target_node=target_node,
            seed_genes=seeds,
            provenance=provenance,
            resolve_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # ------------------------------------------------------------------
    # Full async multi-source path (hard 2s timeouts + concurrency limit)
    # ------------------------------------------------------------------
    local_edges = [
        _attach_edge_provenance(
            e.model_copy(
                update={
                    "sources": list(dict.fromkeys([*(e.sources or []), "local"])),
                    "datasets": list(dict.fromkeys([*(e.datasets or []), "local"])),
                }
            ),
            source_tag="local",
            confidence=900.0,
        )
        for e in base.edges
    ]
    batches: Dict[str, List[ActivityFlowEdge]] = {"local": local_edges}
    cache_key = (
        f"{profile.id}|{','.join(sources)}|{int(use_omnipath)}|"
        f"{','.join(sorted(seeds)[:8])}|cap{MAX_TOPOLOGY_NODES}"
    )
    sem = asyncio.Semaphore(MAX_FETCH_CONCURRENCY)
    any_external_failure = False

    async def _bounded(name: str, factory):
        """Run one source fetch under semaphore + hard wait_for cutoff."""
        async with sem:
            try:
                # Per-task wait matches interactive budget; HTTP layer still
                # clamps to EXTERNAL_HTTP_TIMEOUT_S (2.0s) ClientTimeout.
                result = await asyncio.wait_for(
                    factory(),
                    timeout=min(cut, INTERACTIVE_FETCH_BUDGET_S),
                )
                return name, result
            except Exception as exc:
                return name, exc

    def _pathways_offline() -> List[ActivityFlowEdge]:
        """
        Offline-first pathway edges — never call live KEGG (18s urllib default).
        Uses curated Reactome/KEGG scaffolds only so the hot path cannot hang.
        """
        from voidsignal.integrations.offline_data import OFFLINE_PATHWAY_EDGES

        edges: List[ActivityFlowEdge] = []
        if "kegg" in sources:
            keys = ("hsa04010", "hsa04151", "hsa04115", "hsa04630")
            for key in keys:
                rows = OFFLINE_PATHWAY_EDGES.get(key) or []
                for row in rows:
                    try:
                        src = str(row["source"])
                        tgt = str(row["target"])
                        typ = str(row.get("type") or "activation").lower()
                        sign = -1 if "inhib" in typ else 1
                        edges.append(
                            _attach_edge_provenance(
                                ActivityFlowEdge(
                                    source=src,
                                    target=tgt,
                                    sign=sign,  # type: ignore[arg-type]
                                    is_stimulation=sign == 1,
                                    is_inhibition=sign == -1,
                                    consensus_modification=typ,
                                    mechanism=(
                                        MechanismKind.TRANSCRIPTIONAL
                                        if "transcri" in typ
                                        else MechanismKind.ENZYMATIC
                                    ),
                                    sources=["kegg"],
                                    datasets=["kegg"],
                                    evidence_score=0.75,
                                ),
                                source_tag="kegg",
                                confidence=750.0,
                            )
                        )
                    except Exception:
                        continue
        if "reactome" in sources:
            # Reactome lab client is offline-only (no live REST).
            try:
                for e in ms._fetch_kegg_reactome(
                    profile.id,
                    want_kegg=False,
                    want_reactome=True,
                ):
                    edges.append(_attach_edge_provenance(e, source_tag="reactome"))
            except Exception as exc:
                logger.debug("Reactome offline skip: %s", exc)
        return edges

    tasks = []
    if "omnipath" in sources or "signor" in sources:
        tasks.append(
            _bounded(
                "omnipath",
                lambda: _fetch_omnipath_async(
                    seeds,
                    timeout=cut,
                    include_signor="signor" in sources,
                ),
            )
        )
    if "string" in sources:
        tasks.append(
            _bounded(
                "string",
                lambda: _fetch_string_async(seeds, timeout=cut),
            )
        )
    if "biogrid" in sources:
        tasks.append(
            _bounded(
                "biogrid",
                lambda: asyncio.to_thread(ms._fetch_biogrid, seeds),
            )
        )
    if "kegg" in sources or "reactome" in sources:
        tasks.append(
            _bounded(
                "pathways",
                lambda: asyncio.to_thread(_pathways_offline),
            )
        )

    # One slow DB must not block siblings. Cap the whole wave so ODE still
    # fits under the interactive 1.5s SLO; each HTTP call still uses a
    # ClientTimeout(total<=2.0) hard ceiling.
    if tasks:
        wrapped = [asyncio.create_task(t) for t in tasks]
        done, pending = await asyncio.wait(
            wrapped,
            timeout=INTERACTIVE_FETCH_BUDGET_S,
            return_when=asyncio.ALL_COMPLETED,
        )
        for t in pending:
            any_external_failure = True
            t.cancel()
        # Do NOT await cancelled aiohttp tasks — session teardown can burn the
        # remaining ClientTimeout and blow the interactive SLO.
        raw_results: List[Any] = []
        for t in done:
            if t.cancelled():
                any_external_failure = True
                continue
            exc = t.exception()
            if exc is not None:
                raw_results.append(exc)
            else:
                raw_results.append(t.result())
        if pending:
            source_status["fetch_budget"] = (
                f"aborted_pending={len(pending)};budget_s={INTERACTIVE_FETCH_BUDGET_S}"
            )
    else:
        raw_results = []

    for item in raw_results:
        if isinstance(item, BaseException):
            any_external_failure = True
            source_status["gather"] = f"error:{type(item).__name__}"
            continue
        name, result = item
        if isinstance(result, BaseException):
            any_external_failure = True
            source_status[name] = f"error:{type(result).__name__}"
            logger.info("Source %s aborted: %s", name, result)
            continue
        if name == "omnipath":
            batches["omnipath"] = list(result)
            source_status["omnipath"] = "ok" if result else "empty"
            if "signor" in sources:
                signor_edges = [
                    e
                    for e in result
                    if "signor" in (e.datasets or [])
                    or "signor" in (e.sources or [])
                ]
                batches["signor"] = signor_edges or list(result)[:12]
                source_status["signor"] = "ok" if batches["signor"] else "empty"
        elif name == "pathways":
            kegg_e = [
                e
                for e in result
                if "kegg" in (e.datasets or e.sources or [])
            ]
            reac_e = [
                e
                for e in result
                if "reactome" in (e.datasets or e.sources or [])
            ]
            if "kegg" in sources:
                batches["kegg"] = kegg_e
                source_status["kegg"] = "ok" if kegg_e else "empty"
            if "reactome" in sources:
                batches["reactome"] = reac_e
                source_status["reactome"] = "ok" if reac_e else "empty"
        elif name == "biogrid":
            stamped = [
                _attach_edge_provenance(
                    e,
                    source_tag="biogrid",
                    confidence=_confidence_score_1000(
                        (e.evidence_score or 0.7) * 1000
                        if (e.evidence_score or 0) <= 1
                        else e.evidence_score
                    ),
                )
                for e in result
            ]
            batches["biogrid"] = stamped
            source_status["biogrid"] = "ok" if stamped else "empty"
        else:
            batches[name] = list(result)
            source_status[name] = "ok" if result else "empty"

    fused = ms.fuse_edges(batches, max_edges=MAX_FUSED_EDGES)
    seen = {(e.source, e.target, e.sign) for e in fused}
    for e in local_edges:
        key = (e.source, e.target, e.sign)
        if key not in seen:
            fused.insert(0, e)
            seen.add(key)

    enriched: List[ActivityFlowEdge] = []
    for e in fused:
        meta = dict(e.metadata or {})
        meta.setdefault("pmid_citations", [])
        meta.setdefault(
            "confidence_score",
            _confidence_score_1000(e.evidence_score),
        )
        meta.setdefault("sources", list(e.sources or []))
        enriched.append(e.model_copy(update={"metadata": meta}))

    node_meta: Dict[str, Dict[str, Any]] = {}
    if "uniprot" in sources:
        try:
            from voidsignal.integrations.offline_data import OFFLINE_UNIPROT

            for sym in sorted({n for e in enriched for n in (e.source, e.target)}):
                row = OFFLINE_UNIPROT.get(sym.upper()) or OFFLINE_UNIPROT.get(sym)
                if isinstance(row, dict):
                    node_meta[sym] = {
                        "uniprot_id": row.get("accession"),
                        "localization": row.get("localization"),
                        "full_name": row.get("full_name"),
                        "function": row.get("function"),
                        "pmid_citations": [],
                        "sources": ["uniprot"],
                        "confidence_score": 1000.0,
                        "source": "uniprot-offline",
                    }
            source_status["uniprot"] = "ok" if node_meta else "empty"
        except Exception as exc:  # pragma: no cover
            source_status["uniprot"] = f"error:{type(exc).__name__}"

    graph = ms._assemble_graph(
        enriched,
        name=f"multisource_{profile.id}",
        node_meta=node_meta,
        base_nodes=base.nodes,
    )
    graph = _apply_kinetic_tau(graph)

    external_ok = any(
        source_status.get(s) == "ok" and s not in {"local", "uniprot"}
        for s in sources
    )
    # Circuit breaker: no usable external topology → pre-compiled local presets.
    # Individual source timeouts already aborted above (empty batch + error status).
    if not external_ok:
        cached = _load_topology_cache(cache_key)
        if cached and cached.get("graph") and not any_external_failure:
            try:
                graph = CausalActivityGraph.model_validate(cached["graph"])
                graph = _apply_kinetic_tau(graph)
                source_status["fallback"] = "disk_cache"
            except Exception:
                graph = _preset_fallback_graph(profile.id, q)
                source_status["fallback"] = "presets.local_graph_cache"
        else:
            graph = _preset_fallback_graph(profile.id, q)
            source_status["fallback"] = "presets.local_graph_cache"
    elif any_external_failure:
        source_status["circuit"] = "partial_ok_some_sources_aborted"

    protect = list(profile.trigger_nodes) + list(profile.readout_nodes) + list(
        profile.seed_genes
    )
    graph = trim_topology_to_top_nodes(
        graph, max_nodes=MAX_TOPOLOGY_NODES, protect=protect
    )

    clamps = dict(profile.default_clamps)
    source_node = profile.trigger_nodes[0]
    target_node = next(
        (r for r in profile.readout_nodes if r in graph.nodes),
        profile.readout_nodes[0],
    )
    if not graph.nodes:
        graph = _preset_fallback_graph(profile.id, q)
        source_status["fallback"] = "presets.empty_guard"
    if source_node not in graph.nodes:
        source_node = sorted(graph.nodes.keys())[0]
    if target_node not in graph.nodes:
        target_node = sorted(graph.nodes.keys())[-1]

    provenance = {
        "query": q,
        "profile_id": profile.id,
        "selected_sources": sources,
        "source_status": source_status,
        "n_edges_fused": len(graph.edges),
        "n_nodes": len(graph.nodes),
        "builder": "resolve_multisource_network",
        "resolver": "voidsignal.data.resolver",
        "async": True,
        "mode": "multi_source",
        "http_timeout_s": cut,
        "max_topology_nodes": MAX_TOPOLOGY_NODES,
        "fetch_concurrency": MAX_FETCH_CONCURRENCY,
    }
    graph.provenance = {**(graph.provenance or {}), **provenance}

    try:
        _store_topology_cache(
            cache_key,
            {
                "graph": graph.model_dump(mode="json"),
                "edges": len(graph.edges),
                "provenance": provenance,
            },
        )
    except Exception:
        pass

    return ResolvedCondition(
        query=q,
        profile_id=profile.id,
        graph=graph,
        default_clamps=clamps,
        source_node=source_node,
        target_node=target_node,
        seed_genes=list(profile.seed_genes),
        provenance=provenance,
        resolve_ms=(time.perf_counter() - t0) * 1000.0,
    )


def resolve_multisource_network(
    query_str: str = "",
    *,
    query: str = "",
    selected_sources: Optional[Sequence[str]] = None,
    use_omnipath: bool = True,
    timeout_per_source: float = EXTERNAL_HTTP_TIMEOUT_S,
    max_workers: int = 4,
) -> ResolvedCondition:
    """
    Sync entry-point for the async multi-source aggregator.

    Safe under FastAPI / TestClient (uses a fresh event loop when needed).
    ``max_workers`` is retained for API compatibility with older callers.
    """
    del max_workers  # asyncio gather replaces the old thread pool
    coro = resolve_multisource_network_async(
        query_str,
        query=query,
        selected_sources=selected_sources,
        use_omnipath=use_omnipath,
        timeout_per_source=_clamp_http_timeout(timeout_per_source),
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop (rare in sync FastAPI handlers) — run in thread
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(asyncio.run, coro)
        try:
            return fut.result(timeout=EXTERNAL_HTTP_TIMEOUT_S + 3.0)
        except concurrent.futures.TimeoutError:
            logger.error("resolve_multisource_network hard wall timeout — presets")
            profile = match_condition_profile(
                (query_str or query or "").strip() or "hypoxia"
            )
            graph = _preset_fallback_graph(profile.id, query_str or query or "hypoxia")
            return ResolvedCondition(
                query=(query_str or query or "hypoxia").strip() or "hypoxia",
                profile_id=profile.id,
                graph=graph,
                default_clamps=dict(profile.default_clamps),
                source_node=profile.trigger_nodes[0],
                target_node=profile.readout_nodes[0],
                seed_genes=list(profile.seed_genes),
                provenance={
                    "fallback": "presets.wall_timeout",
                    "builder": "resolve_multisource_network",
                },
                resolve_ms=(EXTERNAL_HTTP_TIMEOUT_S + 3.0) * 1000.0,
            )


__all__ = [
    "ConditionProfile",
    "EXTERNAL_HTTP_TIMEOUT_S",
    "MAX_TOPOLOGY_NODES",
    "ResolvedCondition",
    "graph_from_edge_specs",
    "list_condition_suggestions",
    "local_network_expansion",
    "match_condition_profile",
    "resolve_condition_network",
    "resolve_multisource_network",
    "resolve_multisource_network_async",
    "trim_topology_to_top_nodes",
]
