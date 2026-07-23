"""
Literature & knowledge-graph reasoning for CISTRON Phase 10.

Benchmarks simulated target ranks / drug synergy predictions against curated
pathway membership, PPI neighbourhoods, and functional annotations. Produces a
**Literature Alignment Score (LAS)** ∈ [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import logging
import math

from cistron.topology import SignalingNetwork
from cistron.vendored import VendoredPathwayRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Curated offline evidence corpus (air-gapped)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CuratedEvidence:
    """One literature / annotation fact tied to a gene / protein symbol."""

    symbol: str
    claim: str
    source: str
    """e.g. ``UniProt:P00533``, ``KEGG:hsa04010``, ``PMID:12345678``, ``STRING``."""
    evidence_type: str
    """``pathway`` | ``drug_target`` | ``ppi`` | ``function`` | ``oncogene`` | ``synergy``."""
    weight: float = 1.0
    related_symbols: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "claim": self.claim,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "weight": self.weight,
            "related_symbols": list(self.related_symbols),
            "metadata": dict(self.metadata),
        }


def default_mapk_corpus() -> List[CuratedEvidence]:
    """High-confidence MAPK / EGFR literature priors used when APIs are offline."""
    return [
        CuratedEvidence(
            "EGFR",
            "EGFR is a receptor tyrosine kinase frequently mutated / amplified in cancer; "
            "constitutive signalling drives MAPK cascade hyperactivation.",
            "UniProt:P00533",
            "oncogene",
            1.0,
            ("RAS", "RAF", "MEK", "ERK"),
        ),
        CuratedEvidence(
            "EGFR",
            "EGFR tyrosine kinase inhibitors are clinically validated oncology drugs.",
            "PMID:15118073",
            "drug_target",
            1.0,
            ("MEK", "ERK"),
        ),
        CuratedEvidence(
            "RAS",
            "RAS GTPases transmit EGFR signals to RAF; oncogenic RAS locks GTP-bound state.",
            "UniProt:P01112",
            "oncogene",
            0.95,
            ("EGFR", "RAF"),
        ),
        CuratedEvidence(
            "RAF",
            "RAF kinases phosphorylate MEK; BRAF V600E is a canonical driver mutation.",
            "UniProt:P15056",
            "oncogene",
            0.95,
            ("RAS", "MEK"),
        ),
        CuratedEvidence(
            "MEK",
            "MEK1/2 (MAP2K1/2) are dual-specificity kinases activating ERK; "
            "MEK inhibitors (trametinib, cobimetinib) are approved therapeutics.",
            "UniProt:Q02750",
            "drug_target",
            1.0,
            ("RAF", "ERK"),
        ),
        CuratedEvidence(
            "ERK",
            "ERK1/2 (MAPK1/3) are terminal MAPK effectors controlling proliferation.",
            "UniProt:P28482",
            "function",
            0.9,
            ("MEK", "RAF"),
        ),
        CuratedEvidence(
            "MEK",
            "MEK and EGFR dual blockade shows combinatorial benefit in MAPK-driven tumours.",
            "PMID:26555154",
            "synergy",
            0.85,
            ("EGFR", "ERK"),
        ),
        CuratedEvidence(
            "EGFR",
            "EGFR–MEK combination therapy mitigates adaptive resistance via ERK rebound.",
            "PMID:27926792",
            "synergy",
            0.85,
            ("MEK", "ERK"),
        ),
        CuratedEvidence(
            "EGF",
            "EGF is the cognate ligand of EGFR initiating receptor dimerisation.",
            "UniProt:P01133",
            "function",
            0.7,
            ("EGFR",),
        ),
        CuratedEvidence(
            "EGFR",
            "Member of KEGG MAPK signalling pathway hsa04010.",
            "KEGG:hsa04010",
            "pathway",
            0.8,
            ("RAS", "RAF", "MEK", "ERK"),
        ),
        CuratedEvidence(
            "MEK",
            "Member of KEGG MAPK signalling pathway hsa04010.",
            "KEGG:hsa04010",
            "pathway",
            0.8,
            ("RAF", "ERK"),
        ),
        CuratedEvidence(
            "ERK",
            "Member of KEGG MAPK signalling pathway hsa04010.",
            "KEGG:hsa04010",
            "pathway",
            0.8,
            ("MEK",),
        ),
        CuratedEvidence(
            "RAS",
            "STRING-supported physical / functional association with RAF in MAPK cascade.",
            "STRING",
            "ppi",
            0.75,
            ("RAF", "EGFR"),
        ),
        CuratedEvidence(
            "RAF",
            "STRING-supported association with MEK (MAP2K).",
            "STRING",
            "ppi",
            0.75,
            ("MEK", "RAS"),
        ),
        CuratedEvidence(
            "MEK",
            "STRING-supported association with ERK (MAPK1/3).",
            "STRING",
            "ppi",
            0.75,
            ("ERK", "RAF"),
        ),
    ]


# ---------------------------------------------------------------------------
# Alignment report
# ---------------------------------------------------------------------------


@dataclass
class TargetAlignment:
    symbol: str
    entity_id: str
    simulation_score: float
    las_component: float
    matched_evidence: List[CuratedEvidence]
    pathway_hit: bool
    drug_target_hit: bool
    ppi_hit: bool
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entity_id": self.entity_id,
            "simulation_score": self.simulation_score,
            "las_component": self.las_component,
            "n_evidence": len(self.matched_evidence),
            "pathway_hit": self.pathway_hit,
            "drug_target_hit": self.drug_target_hit,
            "ppi_hit": self.ppi_hit,
            "evidence": [e.as_dict() for e in self.matched_evidence],
            "notes": list(self.notes),
        }


@dataclass
class LiteratureAlignmentReport:
    """
    Aggregate Literature Alignment Score for a set of simulated findings.

    ``las`` ∈ [0, 1] — higher means simulation priorities agree with literature.
    """

    las: float
    target_alignments: List[TargetAlignment]
    synergy_alignment: Optional[float]
    pathway_coverage: float
    n_evidence_hits: int
    corpus_size: int
    kegg_members: List[str]
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "las": self.las,
            "synergy_alignment": self.synergy_alignment,
            "pathway_coverage": self.pathway_coverage,
            "n_evidence_hits": self.n_evidence_hits,
            "corpus_size": self.corpus_size,
            "kegg_members": list(self.kegg_members),
            "summary": self.summary,
            "targets": [t.as_dict() for t in self.target_alignments],
            "metadata": dict(self.metadata),
        }


def _clamp01(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return max(0.0, min(1.0, x))


def literature_alignment_score(
    target_scores: Mapping[str, float],
    *,
    symbol_map: Mapping[str, str],
    evidence: Sequence[CuratedEvidence],
    kegg_symbols: Optional[Set[str]] = None,
    synergy_pair: Optional[Tuple[str, str]] = None,
    weights: Optional[Mapping[str, float]] = None,
) -> LiteratureAlignmentReport:
    """
    Compute LAS from ranked targets and curated evidence.

    Parameters
    ----------
    target_scores :
        ``entity_id →`` simulation / GAT priority score (higher = more important).
    symbol_map :
        ``entity_id →`` gene / protein symbol.
    synergy_pair :
        Optional ``(symbol_a, symbol_b)`` predicted drug combo to score against
        synergy evidence.
    weights :
        Component weights for ``pathway``, ``drug_target``, ``ppi``, ``function``,
        ``oncogene``, ``rank_agreement``. Defaults favour drug-target + pathway.
    """
    w = {
        "pathway": 0.20,
        "drug_target": 0.30,
        "ppi": 0.15,
        "function": 0.10,
        "oncogene": 0.15,
        "rank_agreement": 0.10,
    }
    if weights:
        w.update({k: float(v) for k, v in weights.items()})
    w_sum = sum(w.values()) or 1.0
    w = {k: v / w_sum for k, v in w.items()}

    by_symbol: Dict[str, List[CuratedEvidence]] = {}
    for ev in evidence:
        by_symbol.setdefault(ev.symbol.upper(), []).append(ev)

    kegg = {s.upper() for s in (kegg_symbols or set())}
    # rank agreement: top simulated targets that are also curated drug targets / oncogenes
    ranked = sorted(target_scores.items(), key=lambda kv: kv[1], reverse=True)
    max_sim = max((s for _, s in ranked), default=1.0) or 1.0

    alignments: List[TargetAlignment] = []
    component_scores: List[float] = []
    n_hits = 0

    for eid, sim_score in ranked:
        symbol = symbol_map.get(eid, eid)
        key = symbol.upper()
        matched = list(by_symbol.get(key, []))
        types = {e.evidence_type for e in matched}
        pathway_hit = ("pathway" in types) or (key in kegg)
        drug_hit = "drug_target" in types
        ppi_hit = "ppi" in types
        onc_hit = "oncogene" in types
        func_hit = "function" in types
        if matched or pathway_hit:
            n_hits += len(matched) + (1 if pathway_hit and "pathway" not in types else 0)

        # type presence scores
        type_score = (
            w["pathway"] * (1.0 if pathway_hit else 0.0)
            + w["drug_target"] * (1.0 if drug_hit else 0.0)
            + w["ppi"] * (1.0 if ppi_hit else 0.0)
            + w["function"] * (1.0 if func_hit else 0.0)
            + w["oncogene"] * (1.0 if onc_hit else 0.0)
        )
        # evidence weight boost
        ev_boost = 0.0
        if matched:
            ev_boost = min(1.0, sum(e.weight for e in matched) / max(len(matched), 1))
        rank_agree = (sim_score / max_sim) * (1.0 if (drug_hit or onc_hit or pathway_hit) else 0.35)
        las_i = _clamp01(type_score + w["rank_agreement"] * rank_agree + 0.05 * ev_boost)
        notes = [e.claim for e in matched[:3]]
        if pathway_hit and key in kegg:
            notes.append(f"{symbol} present in vendored KEGG pathway membership.")
        alignments.append(
            TargetAlignment(
                symbol=symbol,
                entity_id=eid,
                simulation_score=float(sim_score),
                las_component=las_i,
                matched_evidence=matched,
                pathway_hit=pathway_hit,
                drug_target_hit=drug_hit,
                ppi_hit=ppi_hit,
                notes=notes,
            )
        )
        component_scores.append(las_i)

    # Synergy literature check
    synergy_alignment: Optional[float] = None
    if synergy_pair is not None:
        a, b = synergy_pair[0].upper(), synergy_pair[1].upper()
        syn_hits = [
            e
            for e in evidence
            if e.evidence_type == "synergy"
            and (
                (e.symbol.upper() == a and b in {x.upper() for x in e.related_symbols})
                or (e.symbol.upper() == b and a in {x.upper() for x in e.related_symbols})
                or ({e.symbol.upper(), *(x.upper() for x in e.related_symbols)} >= {a, b})
            )
        ]
        synergy_alignment = _clamp01(0.35 + 0.65 * min(1.0, len(syn_hits) / 2.0)) if syn_hits else 0.15

    # Pathway coverage among simulated symbols
    sim_symbols = {symbol_map.get(eid, eid).upper() for eid in target_scores}
    if kegg:
        pathway_coverage = len(sim_symbols & kegg) / max(len(sim_symbols), 1)
    else:
        pathway_coverage = sum(1 for t in alignments if t.pathway_hit) / max(len(alignments), 1)

    mean_target = sum(component_scores) / max(len(component_scores), 1)
    # Emphasise top-3 targets (what the agent actually recommends)
    top3 = component_scores[:3] or component_scores
    top_mean = sum(top3) / max(len(top3), 1)
    las = _clamp01(0.55 * top_mean + 0.25 * mean_target + 0.20 * pathway_coverage)
    if synergy_alignment is not None:
        las = _clamp01(0.75 * las + 0.25 * synergy_alignment)

    if las >= 0.7:
        verdict = "strong literature concordance"
    elif las >= 0.45:
        verdict = "moderate literature concordance"
    else:
        verdict = "weak literature concordance — treat predictions as exploratory"

    top_names = ", ".join(t.symbol for t in alignments[:3]) or "none"
    summary = (
        f"LAS={las:.3f} ({verdict}). Top simulated targets [{top_names}] "
        f"matched {n_hits} curated evidence records "
        f"(pathway coverage={pathway_coverage:.2f}"
        + (f", synergy={synergy_alignment:.2f}" if synergy_alignment is not None else "")
        + ")."
    )

    return LiteratureAlignmentReport(
        las=las,
        target_alignments=alignments,
        synergy_alignment=synergy_alignment,
        pathway_coverage=pathway_coverage,
        n_evidence_hits=n_hits,
        corpus_size=len(evidence),
        kegg_members=sorted(kegg),
        summary=summary,
        metadata={"weights": w, "n_targets": len(alignments)},
    )


class LiteratureReasoner:
    """
    Cross-reference simulation outputs with curated + vendored KG knowledge.

    Optional live UniProt / STRING clients may be injected; failures fall back
    to the offline corpus without raising.
    """

    def __init__(
        self,
        *,
        corpus: Optional[Sequence[CuratedEvidence]] = None,
        pathway_id: str = "hsa04010",
        vendored: Optional[VendoredPathwayRepository] = None,
        uniprot_client: Any = None,
        string_client: Any = None,
    ) -> None:
        self.corpus: List[CuratedEvidence] = list(corpus) if corpus is not None else default_mapk_corpus()
        self.pathway_id = pathway_id
        self.vendored = vendored or VendoredPathwayRepository()
        self.uniprot_client = uniprot_client
        self.string_client = string_client
        self._kegg_symbols: Optional[Set[str]] = None

    def kegg_membership(self) -> Set[str]:
        if self._kegg_symbols is not None:
            return set(self._kegg_symbols)
        symbols: Set[str] = set()
        try:
            pmap = self.vendored.load_map(self.pathway_id)
            for label in getattr(pmap, "nodes", {}) or {}:
                for part in str(label).replace(",", " ").replace("/", " ").split():
                    cleaned = "".join(ch for ch in part if ch.isalnum() or ch in {"_", "-"})
                    if cleaned and any(c.isalpha() for c in cleaned):
                        symbols.add(cleaned.upper())
            for rel in getattr(pmap, "relations", []) or []:
                for attr in ("source", "target", "entry1", "entry2"):
                    val = getattr(rel, attr, None)
                    if isinstance(val, str) and val:
                        symbols.add(val.split(":")[-1].upper())
        except Exception as exc:  # noqa: BLE001
            logger.debug("Vendored KEGG membership unavailable: %s", exc)
        # Always include canonical MAPK demo symbols
        symbols.update({"EGF", "EGFR", "RAS", "RAF", "MEK", "ERK", "MAPK1", "MAP2K1", "BRAF", "KRAS"})
        self._kegg_symbols = symbols
        return set(symbols)

    def evidence_for(self, symbol: str) -> List[CuratedEvidence]:
        key = symbol.upper()
        return [e for e in self.corpus if e.symbol.upper() == key]

    def enrich_from_network(self, network: SignalingNetwork) -> List[CuratedEvidence]:
        """
        Derive weak PPI-style edges from the live simulation topology and merge
        into a working corpus copy (does not mutate the base corpus permanently).
        """
        extra: List[CuratedEvidence] = []
        name_of = {e.entity_id: e.name for e in network.registry.entities()}
        for edge in network.active_edges():
            s = name_of.get(edge.source_id, edge.source_id)
            t = name_of.get(edge.target_id, edge.target_id)
            extra.append(
                CuratedEvidence(
                    s,
                    f"Simulation topology edge {s}→{t} ({edge.interaction_type.value}).",
                    "CISTRON:topology",
                    "ppi",
                    0.4,
                    (t,),
                )
            )
        return list(self.corpus) + extra

    def align(
        self,
        network: SignalingNetwork,
        target_scores: Mapping[str, float],
        *,
        synergy_pair: Optional[Tuple[str, str]] = None,
        use_topology_ppi: bool = True,
    ) -> LiteratureAlignmentReport:
        symbol_map = {e.entity_id: e.name for e in network.registry.entities()}
        # Also accept name→score maps by resolving
        resolved: Dict[str, float] = {}
        name_to_id = {e.name.upper(): e.entity_id for e in network.registry.entities()}
        for key, score in target_scores.items():
            if key in network.registry:
                resolved[key] = float(score)
            elif key.upper() in name_to_id:
                resolved[name_to_id[key.upper()]] = float(score)
            else:
                resolved[key] = float(score)

        evidence = self.enrich_from_network(network) if use_topology_ppi else list(self.corpus)
        return literature_alignment_score(
            resolved,
            symbol_map=symbol_map,
            evidence=evidence,
            kegg_symbols=self.kegg_membership(),
            synergy_pair=synergy_pair,
        )

    def try_live_uniprot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Best-effort UniProt lookup; returns ``None`` offline / on failure."""
        if self.uniprot_client is None:
            return None
        try:
            import asyncio

            async def _go() -> Any:
                return await self.uniprot_client.search_gene(symbol)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                logger.debug("Skipping live UniProt — event loop already running")
                return None
            rec = asyncio.run(_go())
            if rec is None:
                return None
            return {
                "accession": getattr(rec, "accession", None),
                "gene": getattr(rec, "gene_name", symbol),
                "function": getattr(rec, "function", None) or getattr(rec, "protein_name", None),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("UniProt live lookup failed for %s: %s", symbol, exc)
            return None
