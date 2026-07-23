"""
Epigenomic transformers — DNA methylation & histone acetylation → k_transcription.

Scores in [0, 1] scale baseline gene transcription rates and, optionally,
downstream protein ``production_rate`` when a gene→protein mapping is known.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

from voidsignal.components import BiologicalEntity, Gene, Protein
from voidsignal.structures import KineticScaleFactors
from voidsignal.topology import SignalingNetwork


@dataclass(frozen=True)
class MethylationRecord:
    """
    CpG / promoter methylation level for one gene.

    ``beta`` is the Illumina-style β-value in [0, 1] (1 = fully methylated).
    Hypermethylation represses transcription.
    """

    gene: str
    beta: float
    region: str = "promoter"
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.gene:
            raise ValueError("MethylationRecord.gene must be non-empty")
        if not math.isfinite(self.beta) or not 0.0 <= self.beta <= 1.0:
            raise ValueError("beta must be finite in [0, 1]")
        if self.weight < 0.0 or not math.isfinite(self.weight):
            raise ValueError("weight must be non-negative finite")


@dataclass(frozen=True)
class HistoneAcetylationRecord:
    """
    Histone acetylation enrichment (e.g. H3K27ac) as a [0, 1] openness score.

    Higher acetylation → stronger transcription (chromatin open).
    """

    gene: str
    score: float
    mark: str = "H3K27ac"
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.gene:
            raise ValueError("HistoneAcetylationRecord.gene must be non-empty")
        if not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be finite in [0, 1]")
        if self.weight < 0.0 or not math.isfinite(self.weight):
            raise ValueError("weight must be non-negative finite")


@dataclass(frozen=True)
class ChromatinAccessibilityRecord:
    """ATAC-seq / DNase accessibility in [0, 1]."""

    gene: str
    accessibility: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.gene:
            raise ValueError("ChromatinAccessibilityRecord.gene must be non-empty")
        if (
            not math.isfinite(self.accessibility)
            or not 0.0 <= self.accessibility <= 1.0
        ):
            raise ValueError("accessibility must be finite in [0, 1]")


@dataclass
class EpigenomicProfile:
    """Bundle of epigenomic assays for one patient / sample."""

    sample_id: str = "sample"
    methylation: List[MethylationRecord] = field(default_factory=list)
    acetylation: List[HistoneAcetylationRecord] = field(default_factory=list)
    accessibility: List[ChromatinAccessibilityRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def genes(self) -> List[str]:
        names = {r.gene for r in self.methylation}
        names |= {r.gene for r in self.acetylation}
        names |= {r.gene for r in self.accessibility}
        return sorted(names)


@dataclass(frozen=True)
class TranscriptionScale:
    """Composite multiplier on k_transcription for one gene."""

    gene: str
    scale: float
    methylation_factor: float = 1.0
    acetylation_factor: float = 1.0
    accessibility_factor: float = 1.0

    def __post_init__(self) -> None:
        if self.scale < 0.0 or not math.isfinite(self.scale):
            raise ValueError("scale must be non-negative finite")


def methylation_factor(beta: float, *, strength: float = 0.85) -> float:
    """Map β-methylation → multiplicative transcription factor ∈ (1-strength, 1]."""
    b = max(0.0, min(1.0, float(beta)))
    s = max(0.0, min(1.0, float(strength)))
    return max(1e-6, 1.0 - s * b)


def acetylation_factor(score: float, *, strength: float = 0.75, baseline: float = 0.35) -> float:
    """
    Map histone acetylation → transcription factor.

    At score=baseline → 1.0; above opens chromatin (scale > 1), below represses.
    """
    x = max(0.0, min(1.0, float(score)))
    s = max(0.0, float(strength))
    b = max(0.0, min(1.0, float(baseline)))
    # Linear around baseline, clamped
    return max(0.05, 1.0 + s * (x - b))


def accessibility_factor(access: float, *, strength: float = 0.6, baseline: float = 0.4) -> float:
    x = max(0.0, min(1.0, float(access)))
    s = max(0.0, float(strength))
    b = max(0.0, min(1.0, float(baseline)))
    return max(0.05, 1.0 + s * (x - b))


def _weighted_mean(pairs: Sequence[Tuple[float, float]], default: float = 1.0) -> float:
    if not pairs:
        return default
    num = sum(v * w for v, w in pairs)
    den = sum(w for _, w in pairs)
    if den <= 0.0:
        return default
    return num / den


class EpigenomicTransformer:
    """
    Convert epigenomic assays into per-gene transcription scales and stamp
    them onto :class:`~voidsignal.components.Gene` nodes (and optional proteins).
    """

    def __init__(
        self,
        *,
        methylation_strength: float = 0.85,
        acetylation_strength: float = 0.75,
        accessibility_strength: float = 0.6,
        also_scale_protein_production: bool = True,
    ) -> None:
        self.methylation_strength = methylation_strength
        self.acetylation_strength = acetylation_strength
        self.accessibility_strength = accessibility_strength
        self.also_scale_protein_production = also_scale_protein_production

    def compute_scales(self, profile: EpigenomicProfile) -> Dict[str, TranscriptionScale]:
        meth: Dict[str, List[Tuple[float, float]]] = {}
        acet: Dict[str, List[Tuple[float, float]]] = {}
        acc: Dict[str, List[Tuple[float, float]]] = {}

        for r in profile.methylation:
            meth.setdefault(r.gene.upper(), []).append(
                (methylation_factor(r.beta, strength=self.methylation_strength), r.weight)
            )
        for r in profile.acetylation:
            acet.setdefault(r.gene.upper(), []).append(
                (
                    acetylation_factor(r.score, strength=self.acetylation_strength),
                    r.weight,
                )
            )
        for r in profile.accessibility:
            acc.setdefault(r.gene.upper(), []).append(
                (
                    accessibility_factor(r.accessibility, strength=self.accessibility_strength),
                    r.weight,
                )
            )

        genes = set(meth) | set(acet) | set(acc)
        out: Dict[str, TranscriptionScale] = {}
        for g in genes:
            mf = _weighted_mean(meth.get(g, []), 1.0)
            af = _weighted_mean(acet.get(g, []), 1.0)
            xf = _weighted_mean(acc.get(g, []), 1.0)
            scale = max(1e-6, mf * af * xf)
            out[g] = TranscriptionScale(
                gene=g,
                scale=scale,
                methylation_factor=mf,
                acetylation_factor=af,
                accessibility_factor=xf,
            )
        return out

    def apply(
        self,
        network: SignalingNetwork,
        profile: EpigenomicProfile,
        *,
        gene_aliases: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, TranscriptionScale]:
        """
        Stamp transcription scales onto matching Gene / Protein nodes.

        ``gene_aliases`` maps assay gene symbols → network entity names.
        """
        scales = self.compute_scales(profile)
        name_map = _entity_name_index(network)
        aliases = {k.upper(): v for k, v in (gene_aliases or {}).items()}

        for gene, ts in scales.items():
            target_name = aliases.get(gene, gene)
            ent = _resolve_entity(name_map, target_name)
            if ent is None:
                continue
            if isinstance(ent, Gene):
                ent.transcription_rate = max(0.0, ent.transcription_rate * ts.scale)
                ent.promoter_strength = max(0.0, ent.promoter_strength * math.sqrt(ts.scale))
                k = ent.kinetics
                ent.kinetics = k.with_updates(
                    production_rate=max(0.0, k.production_rate * ts.scale)
                )
            elif isinstance(ent, Protein) and self.also_scale_protein_production:
                k = ent.kinetics
                ent.kinetics = k.with_updates(
                    production_rate=max(0.0, k.production_rate * ts.scale)
                )
            else:
                k = ent.kinetics
                ent.kinetics = k.with_updates(
                    production_rate=max(0.0, k.production_rate * ts.scale)
                )
            ent.metadata["epigenomic_transcription_scale"] = ts.scale
            ent.metadata["epigenomic_gene"] = gene
        return scales

    def to_kinetic_scales(
        self, scales: Mapping[str, TranscriptionScale]
    ) -> Dict[str, KineticScaleFactors]:
        return {
            g: KineticScaleFactors(
                production_scale=ts.scale,
                kcat_scale=1.0,
                km_scale=1.0,
                binding_scale=1.0,
            )
            for g, ts in scales.items()
        }


def _entity_name_index(network: SignalingNetwork) -> Dict[str, BiologicalEntity]:
    idx: Dict[str, BiologicalEntity] = {}
    for ent in network.registry.entities():
        idx[ent.name.upper()] = ent
        gs = ent.metadata.get("gene_symbol")
        if isinstance(gs, str) and gs:
            idx[gs.upper()] = ent
    return idx


def _resolve_entity(
    name_map: Mapping[str, BiologicalEntity], name: str
) -> Optional[BiologicalEntity]:
    key = name.upper()
    if key in name_map:
        return name_map[key]
    # Strip isoform suffixes like EGFR-001
    base = key.split("-")[0].split("_")[0]
    return name_map.get(base)


def make_demo_epigenomic_profile(sample_id: str = "EPI_DEMO") -> EpigenomicProfile:
    """EGFR hypermethylation + MEK open chromatin demo panel."""
    return EpigenomicProfile(
        sample_id=sample_id,
        methylation=[
            MethylationRecord(gene="EGFR", beta=0.72, region="promoter"),
            MethylationRecord(gene="TP53", beta=0.15, region="promoter"),
        ],
        acetylation=[
            HistoneAcetylationRecord(gene="MEK", score=0.82, mark="H3K27ac"),
            HistoneAcetylationRecord(gene="ERK", score=0.55, mark="H3K27ac"),
        ],
        accessibility=[
            ChromatinAccessibilityRecord(gene="MEK", accessibility=0.78),
            ChromatinAccessibilityRecord(gene="RAS", accessibility=0.45),
        ],
    )
