"""
Multi-source biological knowledge resolution and consensus edge fusion.

Aggregates OmniPath/SIGNOR, Reactome, KEGG, STRING, BioGRID, and UniProt
into a single signed :class:`CausalActivityGraph` with provenance badges.
External calls are short-timeout and best-effort; local curated banks always
guarantee a simulation-ready fallback under the latency budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import logging
import time

from cistron.data.omnipath import OmniPathClient, tau_for_mechanism
from cistron.data.resolver import (
    ResolvedCondition,
    local_network_expansion,
    match_condition_profile,
    resolve_condition_network,
)
from cistron.integrations.catalog import resolve_pathway_ids
from cistron.integrations.offline_data import OFFLINE_UNIPROT
from cistron.integrations.reactome_client import LabReactomeClient
from cistron.integrations.kegg_client import LabKEGGClient
from cistron.models.graph import (
    TAU_ENZYMATIC_MIN,
    ActivityFlowEdge,
    CausalActivityGraph,
    GraphNode,
    MechanismKind,
)
from cistron.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)

ALL_SOURCES: Tuple[str, ...] = (
    "local",
    "omnipath",
    "signor",
    "kegg",
    "reactome",
    "string",
    "biogrid",
    "uniprot",
)

SOURCE_WEIGHTS: Dict[str, float] = {
    "local": 1.0,
    "omnipath": 1.25,
    "signor": 1.25,
    "kegg": 1.05,
    "reactome": 0.95,
    "string": 0.7,
    "biogrid": 0.65,
    "uniprot": 0.0,
}

# Offline BioGRID-style physical pairs (geneA, geneB, score)
_OFFLINE_BIOGRID: Tuple[Tuple[str, str, float], ...] = (
    ("EGFR", "GRB2", 0.88),
    ("EGFR", "SHC1", 0.84),
    ("KRAS", "RAF1", 0.9),
    ("BRAF", "MAP2K1", 0.93),
    ("MAP2K1", "MAPK1", 0.94),
    ("PIK3CA", "AKT1", 0.87),
    ("PTEN", "PIK3CA", 0.8),
    ("TP53", "MDM2", 0.91),
    ("HIF1A", "EPAS1", 0.75),
    ("TNF", "TNFRSF1A", 0.86),
    ("NFKB1", "RELA", 0.92),
    ("APP", "BACE1", 0.78),
)

_PROFILE_PATHWAY_HINTS: Dict[str, Tuple[str, ...]] = {
    "hypoxia": ("MAPK",),
    "mapk": ("MAPK", "PI3K-Akt"),
    "tnbc_egfr": ("MAPK", "PI3K-Akt"),
    "glioblastoma": ("MAPK", "PI3K-Akt"),
    "dna_damage": ("p53",),
    "alzheimers": ("MAPK",),
    "inflammation": ("MAPK",),
    "glaucoma_oxidative": ("MAPK",),
}


@dataclass
class EdgeEvidence:
    """Accumulated multi-source evidence for one directed signed edge."""

    source: str
    target: str
    sign: int
    mechanism: MechanismKind
    sources: Set[str] = field(default_factory=set)
    datasets: Set[str] = field(default_factory=set)
    weight_sum: float = 0.0
    evidence_score: float = 0.0
    modification: str = ""


def normalize_sources(selected: Optional[Sequence[str]]) -> List[str]:
    """Normalize / validate selected source names; default = all."""
    if not selected:
        return list(ALL_SOURCES)
    out: List[str] = []
    for raw in selected:
        key = str(raw).strip().lower()
        if key in {"op", "omni"}:
            key = "omnipath"
        if key == "bio-grid":
            key = "biogrid"
        if key in ALL_SOURCES and key not in out:
            out.append(key)
    return out or list(ALL_SOURCES)


def _sym_from_entity(net: SignalingNetwork, entity_id: str) -> Optional[str]:
    try:
        ent = net.registry.get(entity_id)
    except Exception:
        return None
    sym = getattr(ent, "gene_symbol", None) or getattr(ent, "name", None)
    if not sym:
        return None
    return str(sym).strip()


def _edges_from_signaling_network(
    net: SignalingNetwork,
    *,
    source_tag: str,
) -> List[ActivityFlowEdge]:
    edges: List[ActivityFlowEdge] = []
    for edge in net._edges.values():  # noqa: SLF001 — lab adapter
        src = _sym_from_entity(net, edge.source_id)
        tgt = _sym_from_entity(net, edge.target_id)
        if not src or not tgt or src == tgt:
            continue
        itype = edge.interaction_type
        if itype == InteractionType.BINDING:
            # Undirected PPI — emit weak bidirectional activation for ODE coupling
            for a, b in ((src, tgt), (tgt, src)):
                edges.append(
                    ActivityFlowEdge(
                        source=a,
                        target=b,
                        sign=1,
                        is_stimulation=True,
                        is_inhibition=False,
                        consensus_modification="binding",
                        mechanism=MechanismKind.ENZYMATIC,
                        sources=[source_tag],
                        datasets=[source_tag],
                        evidence_score=float(getattr(edge, "weight", 0.5) or 0.5),
                    )
                )
            continue
        inhibitory = bool(itype.is_inhibitory)
        transcriptional = itype in {
            InteractionType.TRANSCRIPTION,
            InteractionType.TRANSLATION,
        }
        sign = -1 if inhibitory else 1
        edges.append(
            ActivityFlowEdge(
                source=src,
                target=tgt,
                sign=sign,  # type: ignore[arg-type]
                is_stimulation=not inhibitory,
                is_inhibition=inhibitory,
                consensus_modification=itype.value,
                mechanism=(
                    MechanismKind.TRANSCRIPTIONAL
                    if transcriptional
                    else MechanismKind.ENZYMATIC
                ),
                sources=[source_tag],
                datasets=[source_tag],
                evidence_score=float(getattr(edge, "weight", 1.0) or 1.0),
            )
        )
    return edges


def _fetch_omnipath(
    seeds: Sequence[str],
    *,
    timeout: float,
    include_signor: bool,
) -> List[ActivityFlowEdge]:
    try:
        client = OmniPathClient(timeout=timeout)
        live = client.fetch_interactions(genes=list(seeds)[:12], use_cache=True)
        out: List[ActivityFlowEdge] = []
        for e in live.edges:
            tags = set(e.datasets or []) | set(e.sources or [])
            tagged = list(e.sources or [])
            datasets = list(e.datasets or [])
            if "omnipath" not in datasets:
                datasets.append("omnipath")
            if include_signor and any("signor" in str(t).lower() for t in tags):
                if "signor" not in datasets:
                    datasets.append("signor")
            # Always tag omnipath
            if "omnipath" not in tagged:
                tagged.append("omnipath")
            out.append(
                e.model_copy(
                    update={
                        "sources": tagged,
                        "datasets": datasets,
                    }
                )
            )
        return out
    except Exception as exc:  # pragma: no cover
        logger.info("OmniPath multi-source skip: %s", exc)
        return []


def _fetch_kegg_reactome(
    profile_id: str,
    *,
    want_kegg: bool,
    want_reactome: bool,
) -> List[ActivityFlowEdge]:
    hints = _PROFILE_PATHWAY_HINTS.get(profile_id, ("MAPK",))
    entries = resolve_pathway_ids(list(hints))
    edges: List[ActivityFlowEdge] = []
    kegg = LabKEGGClient()
    reactome = LabReactomeClient()
    for entry in entries[:3]:
        try:
            if want_kegg and (entry.source == "kegg" or entry.kegg_id):
                pid = entry.kegg_id or entry.pathway_id
                if not str(pid).startswith("domain:"):
                    net = kegg.build_network(pid, name=entry.name)
                    edges.extend(_edges_from_signaling_network(net, source_tag="kegg"))
            if want_reactome and (
                entry.source == "reactome"
                or entry.reactome_id
                or str(entry.pathway_id).startswith("R-HSA")
            ):
                rid = entry.reactome_id or entry.pathway_id
                if str(rid).startswith("R-HSA"):
                    net = reactome.build_network(rid, name=entry.name)
                    edges.extend(_edges_from_signaling_network(net, source_tag="reactome"))
        except Exception as exc:  # pragma: no cover
            logger.info("Pathway fetch skip %s: %s", entry.pathway_id, exc)
    return edges


def _fetch_string(seeds: Sequence[str]) -> List[ActivityFlowEdge]:
    """STRING neighbourhood — offline PPI bank (live REST on /proteins path only)."""
    try:
        from cistron.integrations.string_client import _OFFLINE_PPI

        seed_u = {s.upper() for s in seeds}
        edges: List[ActivityFlowEdge] = []
        for a, b, score in _OFFLINE_PPI:
            if seed_u and a.upper() not in seed_u and b.upper() not in seed_u:
                continue
            for src, tgt in ((a, b), (b, a)):
                edges.append(
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
                        evidence_score=float(score),
                    )
                )
        if not edges:
            for a, b, score in _OFFLINE_PPI:
                edges.append(
                    ActivityFlowEdge(
                        source=a,
                        target=b,
                        sign=1,
                        is_stimulation=True,
                        is_inhibition=False,
                        consensus_modification="ppi",
                        mechanism=MechanismKind.ENZYMATIC,
                        sources=["string"],
                        datasets=["string"],
                        evidence_score=float(score),
                    )
                )
        return edges
    except Exception as exc:  # pragma: no cover
        logger.info("STRING skip: %s", exc)
        return []


def _fetch_biogrid(seeds: Sequence[str]) -> List[ActivityFlowEdge]:
    """Sync BioGRID proxy — offline curated pairs filtered to seed neighbourhood."""
    seed_u = {s.upper() for s in seeds}
    edges: List[ActivityFlowEdge] = []
    for a, b, score in _OFFLINE_BIOGRID:
        if seed_u and a.upper() not in seed_u and b.upper() not in seed_u:
            # Keep high-confidence pairs that touch at least one seed when seeds set
            continue
        for src, tgt in ((a, b), (b, a)):
            edges.append(
                ActivityFlowEdge(
                    source=src,
                    target=tgt,
                    sign=1,
                    is_stimulation=True,
                    is_inhibition=False,
                    consensus_modification="physical",
                    mechanism=MechanismKind.ENZYMATIC,
                    sources=["biogrid"],
                    datasets=["biogrid"],
                    evidence_score=score,
                )
            )
    # If seed filter emptied everything, fall back to full offline bank
    if not edges:
        for a, b, score in _OFFLINE_BIOGRID:
            edges.append(
                ActivityFlowEdge(
                    source=a,
                    target=b,
                    sign=1,
                    is_stimulation=True,
                    is_inhibition=False,
                    consensus_modification="physical",
                    mechanism=MechanismKind.ENZYMATIC,
                    sources=["biogrid"],
                    datasets=["biogrid"],
                    evidence_score=score,
                )
            )
    return edges


def _enrich_uniprot(symbols: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Offline-first UniProt metadata (live REST reserved for /proteins card)."""
    meta: Dict[str, Dict[str, Any]] = {}
    for sym in list(symbols)[:32]:
        row = OFFLINE_UNIPROT.get(sym.upper()) or OFFLINE_UNIPROT.get(sym)
        if isinstance(row, dict):
            meta[sym] = {
                "uniprot_id": row.get("accession"),
                "localization": row.get("localization"),
                "full_name": row.get("full_name"),
                "function": row.get("function"),
                "pubmed": [],
                "source": "uniprot-offline",
            }
    return meta


def fuse_edges(
    edge_batches: Mapping[str, Sequence[ActivityFlowEdge]],
    *,
    max_edges: int = 80,
) -> List[ActivityFlowEdge]:
    """
    Consensus fusion: group by (source, target), vote on sign, accumulate
    provenance, and rank by weighted evidence.
    """
    buckets: Dict[Tuple[str, str], Dict[int, EdgeEvidence]] = {}
    for src_name, batch in edge_batches.items():
        w = SOURCE_WEIGHTS.get(src_name, 0.5)
        for e in batch:
            key = (e.source, e.target)
            sign_map = buckets.setdefault(key, {})
            ev = sign_map.get(int(e.sign))
            if ev is None:
                ev = EdgeEvidence(
                    source=e.source,
                    target=e.target,
                    sign=int(e.sign),
                    mechanism=e.mechanism,
                    modification=e.consensus_modification or "",
                )
                sign_map[int(e.sign)] = ev
            ev.sources.add(src_name)
            ev.sources.update(e.sources or [])
            ev.datasets.add(src_name)
            ev.datasets.update(e.datasets or [])
            score = float(e.evidence_score if e.evidence_score is not None else 0.6)
            ev.weight_sum += w * score
            ev.evidence_score = max(ev.evidence_score, score)
            if e.mechanism == MechanismKind.TRANSCRIPTIONAL:
                ev.mechanism = MechanismKind.TRANSCRIPTIONAL

    fused: List[Tuple[float, ActivityFlowEdge]] = []
    for (_s, _t), sign_map in buckets.items():
        # Pick the sign with highest weight; prefer signed causal over weak PPI ties
        best = max(sign_map.values(), key=lambda x: x.weight_sum)
        # Require minimum evidence unless local/omnipath contributed
        trusted = best.sources & {"local", "omnipath", "signor", "kegg", "reactome"}
        if not trusted and best.weight_sum < 0.55:
            continue
        n_src = len(best.sources)
        consensus = min(1.0, best.weight_sum / max(1.0, 1.5) * (0.7 + 0.3 * n_src / 4))
        fused.append(
            (
                consensus,
                ActivityFlowEdge(
                    source=best.source,
                    target=best.target,
                    sign=1 if best.sign >= 0 else -1,  # type: ignore[arg-type]
                    is_stimulation=best.sign >= 0,
                    is_inhibition=best.sign < 0,
                    consensus_modification=best.modification or "consensus",
                    mechanism=best.mechanism,
                    sources=sorted(best.sources),
                    datasets=sorted(best.datasets),
                    evidence_score=float(consensus),
                    metadata={
                        "n_sources": n_src,
                        "weight_sum": best.weight_sum,
                        "confidence_score": float(
                            min(1000.0, max(0.0, consensus * 1000.0))
                        ),
                        "pmid_citations": [],
                        "sources": sorted(best.sources),
                    },
                ),
            )
        )

    fused.sort(key=lambda p: (-p[0], p[1].source, p[1].target))
    return [e for _, e in fused[:max_edges]]


def _assemble_graph(
    edges: Sequence[ActivityFlowEdge],
    *,
    name: str,
    node_meta: Optional[Mapping[str, Dict[str, Any]]] = None,
    base_nodes: Optional[Mapping[str, GraphNode]] = None,
) -> CausalActivityGraph:
    nodes: Dict[str, GraphNode] = dict(base_nodes or {})
    for e in edges:
        for sym in (e.source, e.target):
            if sym not in nodes:
                nodes[sym] = GraphNode(
                    gene_symbol=sym,
                    tau_min=TAU_ENZYMATIC_MIN,
                    initial_concentration=0.35,
                    metadata={},
                )
            if e.target == sym:
                tau = tau_for_mechanism(e.mechanism)
                if tau > nodes[sym].tau_min:
                    nodes[sym] = nodes[sym].model_copy(update={"tau_min": tau})
    if node_meta:
        for sym, meta in node_meta.items():
            if sym not in nodes:
                nodes[sym] = GraphNode(gene_symbol=sym, tau_min=TAU_ENZYMATIC_MIN)
            merged_meta = {**(nodes[sym].metadata or {}), **meta, "provenance": meta}
            nodes[sym] = nodes[sym].model_copy(update={"metadata": merged_meta})
    return CausalActivityGraph(
        name=name,
        nodes=nodes,
        edges=list(edges),
        ambiguous=[],
        provenance={"builder": "resolve_multisource_network"},
    )


def resolve_multisource_network(
    query_str: str = "",
    *,
    query: str = "",
    selected_sources: Optional[Sequence[str]] = None,
    use_omnipath: bool = True,
    timeout_per_source: float = 0.45,
    max_workers: int = 4,
) -> ResolvedCondition:
    """Delegate to the async multi-source aggregator in ``cistron.data.resolver``."""
    from cistron.data.resolver import resolve_multisource_network as _resolve

    return _resolve(
        query_str,
        query=query,
        selected_sources=selected_sources,
        use_omnipath=use_omnipath,
        timeout_per_source=timeout_per_source,
        max_workers=max_workers,
    )


def list_available_sources() -> List[Dict[str, str]]:
    """UI catalogue for Explorer source toggles."""
    labels = {
        "local": "Local curated bank",
        "omnipath": "OmniPath",
        "signor": "SIGNOR",
        "kegg": "KEGG",
        "reactome": "Reactome",
        "string": "STRING",
        "biogrid": "BioGRID",
        "uniprot": "UniProt",
    }
    return [{"id": s, "label": labels.get(s, s)} for s in ALL_SOURCES]


def list_source_situations(
    selected_sources: Optional[Sequence[str]] = None,
) -> List[Dict[str, str]]:
    """
    Curated biological situations keyed by knowledge source for Explorer dropdowns.

    Each row: id, source, label, query, pathway_id (optional), description.
    """
    from cistron.data.resolver import list_condition_suggestions
    from cistron.integrations.catalog import HUMAN_PATHWAY_CATALOG

    want = set(normalize_sources(selected_sources)) if selected_sources else set(ALL_SOURCES)
    rows: List[Dict[str, str]] = []

    # Local / OmniPath / SIGNOR disease–stress situations
    local_situations = [
        ("local", "Hypoxia-induced angiogenesis", "Hypoxia · HIF → VEGFA", "O2→EGLN1⊣HIF1A angiogenic program"),
        ("local", "Radiation DNA Damage p53 response", "Radiation DNA Damage", "ATM/ATR → TP53 checkpoint"),
        ("local", "Alzheimer's Amyloid Stress", "Alzheimer's Amyloid Stress", "APP/BACE → neuroinflammation"),
        ("local", "Alzheimer's Neuroinflammation", "Neuroinflammation", "ROS/NF-κB cytokine loop"),
        ("local", "Glioblastoma EGFR resistance", "EGFR Resistance (GBM)", "EGFR → MAPK/PI3K survival"),
        ("local", "Triple-negative breast cancer EGFR survival", "TNBC EGFR Survival", "EGF→EGFR MAPK–PI3K"),
        ("local", "Glaucoma Oxidative Stress", "Glaucoma Oxidative Stress", "ROS → NRF2 vs NF-κB"),
        ("local", "LPS inflammatory cytokine storm", "Inflammation (LPS)", "TLR4 → NF-κB cytokines"),
        ("omnipath", "Hypoxia-induced angiogenesis", "OmniPath · Hypoxia scaffold", "Activity-flow HIF axis"),
        ("omnipath", "EGFR Resistance MAPK bypass", "OmniPath · EGFR/MAPK", "Signed RTK→MAPK interactions"),
        ("signor", "LPS inflammatory cytokine storm", "SIGNOR · Inflammation", "Signed TLR/NF-κB edges"),
        ("signor", "Alzheimer's Neuroinflammation", "SIGNOR · Neuroinflammation", "TNF/IL1B causal links"),
    ]
    for source, query, label, desc in local_situations:
        if source not in want:
            continue
        rows.append(
            {
                "id": f"{source}:{query}",
                "source": source,
                "label": label,
                "query": query,
                "pathway_id": "",
                "description": desc,
            }
        )

    # Also mirror chip suggestions under local if not already added
    if "local" in want:
        seen_q = {r["query"] for r in rows if r["source"] == "local"}
        for tip in list_condition_suggestions():
            if tip["query"] in seen_q:
                continue
            rows.append(
                {
                    "id": f"local:{tip['query']}",
                    "source": "local",
                    "label": tip["label"],
                    "query": tip["query"],
                    "pathway_id": "",
                    "description": "Curated Cistron condition",
                }
            )

    # KEGG / Reactome pathway situations
    for entry in HUMAN_PATHWAY_CATALOG:
        src = entry.source if entry.source in {"kegg", "reactome"} else (
            "kegg" if entry.kegg_id else "reactome" if entry.reactome_id else None
        )
        if src is None or src not in want:
            # Emit under kegg when kegg_id present even if source is synthetic
            if entry.kegg_id and "kegg" in want:
                src = "kegg"
            elif entry.reactome_id and "reactome" in want:
                src = "reactome"
            else:
                continue
        query = entry.name
        # Prefer disease-flavoured queries for known resistance pathway
        if "EGFR" in entry.name and "resistance" in entry.name.lower():
            query = "Glioblastoma EGFR resistance"
        elif "p53" in entry.name.lower():
            query = "Radiation DNA Damage p53 response"
        elif "NF-kappa" in entry.name or "NF-κB" in entry.name:
            query = "LPS inflammatory cytokine storm"
        elif "MAPK" in entry.name:
            query = "EGFR Resistance MAPK bypass"
        elif "PI3K" in entry.name or "Akt" in entry.name:
            query = "Triple-negative breast cancer EGFR survival"
        rows.append(
            {
                "id": f"{src}:{entry.pathway_id}",
                "source": src,
                "label": f"{src.upper()} · {entry.name}",
                "query": query,
                "pathway_id": entry.pathway_id,
                "description": entry.description or entry.name,
            }
        )
        if entry.reactome_id and "reactome" in want and src != "reactome":
            rows.append(
                {
                    "id": f"reactome:{entry.reactome_id}",
                    "source": "reactome",
                    "label": f"Reactome · {entry.name}",
                    "query": query,
                    "pathway_id": entry.reactome_id,
                    "description": entry.description or entry.name,
                }
            )

    # STRING / BioGRID hub situations
    if "string" in want:
        for label, query, desc in (
            ("STRING · EGFR neighbourhood", "Glioblastoma EGFR resistance", "High-confidence EGFR PPI hub"),
            ("STRING · MAPK cascade PPI", "EGFR Resistance MAPK bypass", "EGFR–KRAS–BRAF–MEK–ERK"),
            ("STRING · TP53–MDM2", "Radiation DNA Damage p53 response", "Physical TP53/MDM2 complex"),
        ):
            rows.append(
                {
                    "id": f"string:{query}",
                    "source": "string",
                    "label": label,
                    "query": query,
                    "pathway_id": "",
                    "description": desc,
                }
            )
    if "biogrid" in want:
        for label, query, desc in (
            ("BioGRID · EGFR adapters", "Glioblastoma EGFR resistance", "EGFR–GRB2–SHC1 physical links"),
            ("BioGRID · PI3K–AKT", "Triple-negative breast cancer EGFR survival", "PIK3CA–AKT1 interactions"),
            ("BioGRID · NF-κB complex", "LPS inflammatory cytokine storm", "NFKB1–RELA dimer"),
        ):
            rows.append(
                {
                    "id": f"biogrid:{query}:{label}",
                    "source": "biogrid",
                    "label": label,
                    "query": query,
                    "pathway_id": "",
                    "description": desc,
                }
            )

    if "uniprot" in want:
        for label, query, desc in (
            ("UniProt · EGFR (P00533)", "Glioblastoma EGFR resistance", "Plasma membrane RTK localization"),
            ("UniProt · HIF1A (Q16665)", "Hypoxia-induced angiogenesis", "Nuclear hypoxia TF"),
            ("UniProt · TP53 (P04637)", "Radiation DNA Damage p53 response", "Nuclear tumor suppressor"),
            ("UniProt · APP (P05067)", "Alzheimer's Amyloid Stress", "Amyloid precursor membrane protein"),
        ):
            rows.append(
                {
                    "id": f"uniprot:{query}:{label}",
                    "source": "uniprot",
                    "label": label,
                    "query": query,
                    "pathway_id": "",
                    "description": desc,
                }
            )

    # Stable order: source then label
    rows.sort(key=lambda r: (r["source"], r["label"]))
    return rows


__all__ = [
    "ALL_SOURCES",
    "SOURCE_WEIGHTS",
    "fuse_edges",
    "list_available_sources",
    "list_source_situations",
    "normalize_sources",
    "resolve_multisource_network",
]
