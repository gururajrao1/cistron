"""
Transcriptomic splicing layer — Percent Spliced In (PSI) → isoform kinetics.

PSI matrices adjust isoform-specific catalytic efficiency (vmax / k_cat) and
domain availability (binding / production) for protein nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

from cistron.components import BiologicalEntity, Protein
from cistron.structures import KineticScaleFactors
from cistron.topology import SignalingNetwork


@dataclass(frozen=True)
class IsoformRecord:
    """
    One splice isoform of a gene.

    ``psi`` is Percent Spliced In ∈ [0, 1]. Domain flags control which kinetic
    axes the isoform contributes to when aggregated.
    """

    gene: str
    isoform_id: str
    psi: float
    catalytic_efficiency: float = 1.0
    """Relative k_cat vs canonical (1.0 = wild-type catalytic domain intact)."""
    domain_availability: float = 1.0
    """Fraction of binding / docking domain retained after splicing."""
    kinase_domain: bool = True
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.gene or not self.isoform_id:
            raise ValueError("gene and isoform_id must be non-empty")
        if not math.isfinite(self.psi) or not 0.0 <= self.psi <= 1.0:
            raise ValueError("psi must be finite in [0, 1]")
        for name in ("catalytic_efficiency", "domain_availability", "weight"):
            v = getattr(self, name)
            if v < 0.0 or not math.isfinite(v):
                raise ValueError(f"{name} must be non-negative finite")


@dataclass
class SplicingProfile:
    """PSI panel for one sample."""

    sample_id: str = "sample"
    isoforms: List[IsoformRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def genes(self) -> List[str]:
        return sorted({r.gene.upper() for r in self.isoforms})

    def by_gene(self) -> Dict[str, List[IsoformRecord]]:
        out: Dict[str, List[IsoformRecord]] = {}
        for r in self.isoforms:
            out.setdefault(r.gene.upper(), []).append(r)
        return out


@dataclass(frozen=True)
class IsoformKineticEffect:
    """Aggregated PSI-weighted kinetic multipliers for one gene."""

    gene: str
    kcat_scale: float
    binding_scale: float
    production_scale: float
    effective_psi: float
    n_isoforms: int

    def as_kinetic_scales(self) -> KineticScaleFactors:
        return KineticScaleFactors(
            kcat_scale=self.kcat_scale,
            km_scale=1.0 / max(self.kcat_scale, 1e-6),  # weaker isoform → higher apparent Km
            binding_scale=self.binding_scale,
            production_scale=self.production_scale,
        )


def aggregate_psi(isoforms: Sequence[IsoformRecord]) -> IsoformKineticEffect:
    """
    PSI-weighted mean of catalytic efficiency and domain availability.

    Isoforms without a kinase domain contribute to binding/production only.
    """
    if not isoforms:
        raise ValueError("isoforms must be non-empty")
    gene = isoforms[0].gene.upper()
    # Renormalize PSI within gene (tolerate noisy panels that don't sum to 1)
    raw = sum(max(0.0, r.psi) * r.weight for r in isoforms)
    if raw <= 1e-12:
        weights = [1.0 / len(isoforms)] * len(isoforms)
        eff_psi = 0.0
    else:
        weights = [(r.psi * r.weight) / raw for r in isoforms]
        eff_psi = sum(r.psi * w for r, w in zip(isoforms, weights))

    kcat = 0.0
    bind = 0.0
    prod = 0.0
    for r, w in zip(isoforms, weights):
        cat = r.catalytic_efficiency if r.kinase_domain else 0.05 * r.catalytic_efficiency
        kcat += w * cat
        bind += w * r.domain_availability
        prod += w * (0.5 + 0.5 * r.domain_availability)
    return IsoformKineticEffect(
        gene=gene,
        kcat_scale=max(1e-4, kcat),
        binding_scale=max(1e-4, bind),
        production_scale=max(1e-4, prod),
        effective_psi=eff_psi,
        n_isoforms=len(isoforms),
    )


class SplicingTransformer:
    """Apply PSI isoform matrices onto protein kinetic parameters."""

    def __init__(self, *, also_edges: bool = True) -> None:
        self.also_edges = also_edges

    def compute_effects(self, profile: SplicingProfile) -> Dict[str, IsoformKineticEffect]:
        return {g: aggregate_psi(recs) for g, recs in profile.by_gene().items()}

    def apply(
        self,
        network: SignalingNetwork,
        profile: SplicingProfile,
        *,
        gene_aliases: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, IsoformKineticEffect]:
        effects = self.compute_effects(profile)
        name_map = _entity_name_index(network)
        aliases = {k.upper(): v for k, v in (gene_aliases or {}).items()}

        for gene, eff in effects.items():
            target = aliases.get(gene, gene)
            ent = _resolve_entity(name_map, target)
            if ent is None:
                continue
            scales = eff.as_kinetic_scales()
            k = ent.kinetics
            ent.kinetics = k.with_updates(
                vmax=max(0.0, k.vmax * scales.kcat_scale),
                km=max(1e-9, k.km * scales.km_scale),
                binding_affinity=max(0.0, k.binding_affinity * scales.binding_scale),
                production_rate=max(0.0, k.production_rate * scales.production_scale),
            )
            ent.metadata["splicing_kcat_scale"] = scales.kcat_scale
            ent.metadata["splicing_effective_psi"] = eff.effective_psi
            if self.also_edges and isinstance(ent, Protein):
                for edge in network.out_edges(ent.entity_id):
                    edge.rate_constant = max(0.0, edge.rate_constant * scales.kcat_scale)
        return effects


def parse_psi_matrix(
    rows: Iterable[Mapping[str, Any]],
    *,
    gene_key: str = "gene",
    isoform_key: str = "isoform",
    psi_key: str = "psi",
) -> SplicingProfile:
    """Parse a list of dict rows into a :class:`SplicingProfile`."""
    isoforms: List[IsoformRecord] = []
    for row in rows:
        isoforms.append(
            IsoformRecord(
                gene=str(row[gene_key]),
                isoform_id=str(row.get(isoform_key, row.get("isoform_id", "iso1"))),
                psi=float(row[psi_key]),
                catalytic_efficiency=float(row.get("catalytic_efficiency", 1.0)),
                domain_availability=float(row.get("domain_availability", 1.0)),
                kinase_domain=bool(row.get("kinase_domain", True)),
                weight=float(row.get("weight", 1.0)),
            )
        )
    return SplicingProfile(isoforms=isoforms)


def make_demo_splicing_profile(sample_id: str = "SPLICE_DEMO") -> SplicingProfile:
    """MEK kinase-domain skip isoform vs canonical; EGFR exon19-like mix."""
    return SplicingProfile(
        sample_id=sample_id,
        isoforms=[
            IsoformRecord(
                gene="MEK",
                isoform_id="MEK-canonical",
                psi=0.55,
                catalytic_efficiency=1.0,
                domain_availability=1.0,
                kinase_domain=True,
            ),
            IsoformRecord(
                gene="MEK",
                isoform_id="MEK-dKD",
                psi=0.45,
                catalytic_efficiency=0.08,
                domain_availability=0.7,
                kinase_domain=False,
            ),
            IsoformRecord(
                gene="EGFR",
                isoform_id="EGFR-wt",
                psi=0.35,
                catalytic_efficiency=1.0,
                domain_availability=1.0,
            ),
            IsoformRecord(
                gene="EGFR",
                isoform_id="EGFR-ex19del",
                psi=0.65,
                catalytic_efficiency=1.45,
                domain_availability=0.95,
            ),
        ],
    )


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
    base = key.split("-")[0].split("_")[0]
    return name_map.get(base)
