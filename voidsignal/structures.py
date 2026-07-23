"""
Structure-aware kinetic modulation for VOIDSIGNAL Phase 3.

Ingests AlphaFold / PDB-style spatial annotation maps and maps Phase-2 VCF
residue impacts onto continuous scaling of kinetic parameters consumed by
:class:`~voidsignal.simulation.MassActionRHS` (``vmax`` / ``k_cat``, ``km``,
``binding_affinity``).

Disruption model
----------------
A missense (or local structural) hit at residue *r* receives a disruption
score ``δ ∈ [0, 1]`` from its proximity to annotated catalytic domains and
binding pockets. Kinetic updates:

* ``k_cat' = k_cat · (1 − α · δ)``
* ``K_m'   = K_m   · (1 + β · δ)``   (weaker substrate capture)
* ``K_a'   = K_a   · (1 − γ · δ)``   (binding affinity)

Surface variants far from pockets leave parameters essentially untouched
(``δ → 0``). Pocket-centre hits approach constitutive hypomorph / LoF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import json
import logging
import math
import re

from voidsignal.components import KineticParameters, Protein
from voidsignal.parsers import VariantConsequence, VariantRecord
from voidsignal.perturbation import Mutation, MutationKind
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


@dataclass(frozen=True)
class StructuralDomain:
    """Linear domain annotation on a polypeptide (1-based inclusive residues)."""

    name: str
    start: int
    end: int
    kind: str = "domain"
    """``catalytic`` | ``binding`` | ``transmembrane`` | ``domain`` | …"""

    def __post_init__(self) -> None:
        if self.start < 1 or self.end < self.start:
            raise ValueError(f"Invalid domain span {self.start}-{self.end} for {self.name}")

    def contains(self, residue: int) -> bool:
        return self.start <= residue <= self.end

    def centre(self) -> float:
        return 0.5 * (self.start + self.end)

    def distance_to(self, residue: int) -> float:
        if self.contains(residue):
            return 0.0
        if residue < self.start:
            return float(self.start - residue)
        return float(residue - self.end)


@dataclass(frozen=True)
class BindingPocket:
    """
    Binding-site / pocket annotation.

    Prefer explicit residue indices; fall back to a contiguous span when only
    start/end are known. Optional 3D ``center`` enables Euclidean distance when
    residue coordinates are supplied in the parent map.
    """

    name: str
    residues: Tuple[int, ...] = ()
    start: Optional[int] = None
    end: Optional[int] = None
    center: Optional[Tuple[float, float, float]] = None
    radius_angstrom: float = 6.0

    def __post_init__(self) -> None:
        if not self.residues and (self.start is None or self.end is None):
            raise ValueError(f"Pocket {self.name!r} needs residues or start/end")
        if self.radius_angstrom <= 0.0:
            raise ValueError("radius_angstrom must be positive")

    def residue_set(self) -> Tuple[int, ...]:
        if self.residues:
            return self.residues
        assert self.start is not None and self.end is not None
        return tuple(range(self.start, self.end + 1))

    def contains(self, residue: int) -> bool:
        return residue in self.residue_set()

    def sequence_distance(self, residue: int) -> float:
        if self.contains(residue):
            return 0.0
        members = self.residue_set()
        return float(min(abs(residue - r) for r in members))


@dataclass
class ResidueCoordinate:
    """Optional Cα / centroid coordinate for a residue."""

    residue: int
    x: float
    y: float
    z: float

    def distance_to(self, other: "ResidueCoordinate") -> float:
        return math.sqrt(
            (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2
        )


@dataclass
class StructuralMap:
    """
    Protein-level structural annotation bundle (AlphaFold/PDB derived).

    Attributes
    ----------
    protein_id :
        UniProt accession or gene symbol key used for lookups.
    sequence_length :
        Full chain length (amino acids).
    domains / pockets :
        Functional annotations.
    coordinates :
        Optional residue → 3D map for Euclidean pocket distance.
    plddt :
        Optional per-residue confidence (AlphaFold); low-confidence hits are
        softened so we do not over-penalise disordered loops.
    """

    protein_id: str
    sequence_length: int
    domains: List[StructuralDomain] = field(default_factory=list)
    pockets: List[BindingPocket] = field(default_factory=list)
    coordinates: Dict[int, ResidueCoordinate] = field(default_factory=dict)
    plddt: Dict[int, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.protein_id:
            raise ValueError("protein_id is required")
        if self.sequence_length < 1:
            raise ValueError("sequence_length must be ≥ 1")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMap":
        """Parse a JSON-compatible structural annotation document."""
        domains = [
            StructuralDomain(
                name=str(d["name"]),
                start=int(d["start"]),
                end=int(d["end"]),
                kind=str(d.get("kind", "domain")),
            )
            for d in payload.get("domains", []) or []
        ]
        pockets: List[BindingPocket] = []
        for p in payload.get("pockets", []) or []:
            residues = tuple(int(r) for r in (p.get("residues") or []))
            center = p.get("center")
            center_t = None
            if center is not None and len(center) == 3:
                center_t = (float(center[0]), float(center[1]), float(center[2]))
            pockets.append(
                BindingPocket(
                    name=str(p["name"]),
                    residues=residues,
                    start=int(p["start"]) if p.get("start") is not None else None,
                    end=int(p["end"]) if p.get("end") is not None else None,
                    center=center_t,
                    radius_angstrom=float(p.get("radius_angstrom", 6.0)),
                )
            )
        coords: Dict[int, ResidueCoordinate] = {}
        for c in payload.get("coordinates", []) or []:
            res = int(c["residue"])
            coords[res] = ResidueCoordinate(res, float(c["x"]), float(c["y"]), float(c["z"]))
        # Also accept dict form {"123": {"x":..,"y":..,"z":..}}
        if isinstance(payload.get("coordinates"), dict):
            for key, val in payload["coordinates"].items():  # type: ignore[index]
                if not isinstance(val, Mapping):
                    continue
                res = int(key)
                coords[res] = ResidueCoordinate(
                    res, float(val["x"]), float(val["y"]), float(val["z"])
                )
        plddt_raw = payload.get("plddt") or {}
        plddt = {int(k): float(v) for k, v in dict(plddt_raw).items()}
        return cls(
            protein_id=str(payload.get("protein_id") or payload.get("uniprot") or payload.get("id")),
            sequence_length=int(payload.get("sequence_length") or payload.get("length") or 1),
            domains=domains,
            pockets=pockets,
            coordinates=coords,
            plddt=plddt,
            metadata={k: v for k, v in payload.items() if k not in {
                "protein_id", "uniprot", "id", "sequence_length", "length",
                "domains", "pockets", "coordinates", "plddt",
            }},
        )

    @classmethod
    def from_json(cls, path: PathLike) -> "StructuralMap":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))


@dataclass(frozen=True)
class DisruptionAssessment:
    """Continuous structural disruption report for one residue / variant."""

    residue: int
    disruption: float
    """δ ∈ [0, 1] — 0 untouched, 1 maximally disruptive."""
    nearest_pocket: Optional[str]
    nearest_domain: Optional[str]
    sequence_distance: float
    spatial_distance: Optional[float]
    confidence_weight: float
    notes: str = ""


@dataclass(frozen=True)
class KineticScaleFactors:
    """Multipliers applied to :class:`KineticParameters` fields."""

    kcat_scale: float = 1.0
    km_scale: float = 1.0
    binding_scale: float = 1.0
    production_scale: float = 1.0

    def __post_init__(self) -> None:
        for name in ("kcat_scale", "km_scale", "binding_scale", "production_scale"):
            value = getattr(self, name)
            if value < 0.0 or not math.isfinite(value):
                raise ValueError(f"{name} must be a non-negative finite number")


_HGVS_PROTEIN = re.compile(
    r"(?:p\.)?(?P<ref>[A-Za-z]{1,3})?(?P<pos>\d+)(?P<alt>[A-Za-z]{1,3}|\*|=)?",
    re.IGNORECASE,
)


def parse_residue_position(
    variant: VariantRecord | Mutation | Mapping[str, Any] | int | str,
) -> Optional[int]:
    """
    Extract a 1-based protein residue index from heterogeneous variant carriers.
    """
    if isinstance(variant, int):
        return variant if variant >= 1 else None
    if isinstance(variant, str):
        match = _HGVS_PROTEIN.search(variant.replace(" ", ""))
        return int(match.group("pos")) if match else None
    if isinstance(variant, VariantRecord):
        for key in ("AA_POS", "Protein_position", "residue", "POS_AA", "HGVSp"):
            if key in variant.info:
                raw = variant.info[key]
                if isinstance(raw, list):
                    raw = raw[0]
                if isinstance(raw, int):
                    return raw
                parsed = parse_residue_position(str(raw))
                if parsed is not None:
                    return parsed
        if variant.raw_consequence:
            parsed = parse_residue_position(variant.raw_consequence)
            if parsed is not None:
                return parsed
        return None
    if isinstance(variant, Mutation):
        for key in ("residue", "aa_pos", "hgvsp"):
            if key in variant.__dict__.get("metadata", {}):  # type: ignore[attr-defined]
                pass
        # Mutations don't carry metadata field by default — check name
        return parse_residue_position(variant.name)
    if isinstance(variant, Mapping):
        for key in ("residue", "aa_pos", "protein_position", "HGVSp", "hgvsp"):
            if key in variant:
                return parse_residue_position(variant[key])  # type: ignore[index]
    return None


class StructureAwareModulator:
    """
    Map structural context + variant impacts onto kinetic scale factors.

    Parameters
    ----------
    alpha / beta / gamma :
        Sensitivities for ``k_cat``, ``K_m``, and binding affinity respectively.
    pocket_length_scale :
        Sequence-distance (residues) at which pocket influence decays to ``1/e``.
    domain_weight :
        Relative weight of catalytic-domain membership vs pocket proximity.
    """

    def __init__(
        self,
        *,
        alpha: float = 0.85,
        beta: float = 1.5,
        gamma: float = 0.9,
        pocket_length_scale: float = 12.0,
        domain_weight: float = 0.35,
        min_scale: float = 0.05,
    ) -> None:
        if pocket_length_scale <= 0.0:
            raise ValueError("pocket_length_scale must be positive")
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.gamma = float(gamma)
        self.pocket_length_scale = float(pocket_length_scale)
        self.domain_weight = float(domain_weight)
        self.min_scale = float(min_scale)
        self._maps: Dict[str, StructuralMap] = {}

    def register(self, structural_map: StructuralMap) -> None:
        self._maps[structural_map.protein_id] = structural_map
        self._maps[structural_map.protein_id.upper()] = structural_map

    def register_json(self, path: PathLike) -> StructuralMap:
        smap = StructuralMap.from_json(path)
        self.register(smap)
        return smap

    def get(self, protein_id: str) -> Optional[StructuralMap]:
        return self._maps.get(protein_id) or self._maps.get(protein_id.upper())

    def assess_residue(self, structural_map: StructuralMap, residue: int) -> DisruptionAssessment:
        """Compute continuous disruption δ for a residue index."""
        if residue < 1 or residue > structural_map.sequence_length:
            return DisruptionAssessment(
                residue=residue,
                disruption=0.0,
                nearest_pocket=None,
                nearest_domain=None,
                sequence_distance=float("inf"),
                spatial_distance=None,
                confidence_weight=1.0,
                notes="residue_out_of_range",
            )

        # Pocket proximity (sequence + optional Euclidean)
        best_pocket: Optional[str] = None
        seq_dist = float("inf")
        spatial: Optional[float] = None
        pocket_score = 0.0
        for pocket in structural_map.pockets:
            d_seq = pocket.sequence_distance(residue)
            if d_seq < seq_dist:
                seq_dist = d_seq
                best_pocket = pocket.name
            # Sequence Gaussian falloff
            local = math.exp(-d_seq / self.pocket_length_scale)
            # Spatial refinement
            if pocket.center and residue in structural_map.coordinates:
                rc = structural_map.coordinates[residue]
                d3 = math.sqrt(
                    (rc.x - pocket.center[0]) ** 2
                    + (rc.y - pocket.center[1]) ** 2
                    + (rc.z - pocket.center[2]) ** 2
                )
                spatial = d3 if spatial is None else min(spatial, d3)
                if d3 <= pocket.radius_angstrom:
                    local = max(local, 1.0)
                else:
                    local = max(local, math.exp(-(d3 - pocket.radius_angstrom) / max(pocket.radius_angstrom, 1.0)))
            if pocket.contains(residue):
                local = 1.0
            pocket_score = max(pocket_score, local)

        # Catalytic domain membership
        best_domain: Optional[str] = None
        domain_score = 0.0
        for domain in structural_map.domains:
            if domain.kind.lower() not in {"catalytic", "active", "kinase", "binding"}:
                if domain.contains(residue):
                    domain_score = max(domain_score, 0.35)
                    best_domain = domain.name
                continue
            if domain.contains(residue):
                # Distance from domain centre softens extremes
                half = max(0.5 * (domain.end - domain.start), 1.0)
                offset = abs(residue - domain.centre()) / half
                domain_score = max(domain_score, max(0.4, 1.0 - 0.5 * offset))
                best_domain = domain.name
            else:
                d = domain.distance_to(residue)
                domain_score = max(domain_score, 0.25 * math.exp(-d / self.pocket_length_scale))
                if best_domain is None:
                    best_domain = domain.name

        raw = min(1.0, max(pocket_score, self.domain_weight * domain_score + (1.0 - self.domain_weight) * pocket_score))

        # Soften disruption on low-pLDDT residues (disordered / uncertain)
        conf = structural_map.plddt.get(residue, 90.0)
        conf_w = max(0.3, min(1.0, conf / 90.0))
        disruption = max(0.0, min(1.0, raw * conf_w))

        return DisruptionAssessment(
            residue=residue,
            disruption=disruption,
            nearest_pocket=best_pocket,
            nearest_domain=best_domain,
            sequence_distance=seq_dist if math.isfinite(seq_dist) else -1.0,
            spatial_distance=spatial,
            confidence_weight=conf_w,
            notes="ok",
        )

    def scales_from_disruption(
        self,
        disruption: float,
        *,
        consequence: VariantConsequence = VariantConsequence.MISSENSE,
    ) -> KineticScaleFactors:
        """Map δ (+ consequence class) onto kinetic multipliers."""
        delta = max(0.0, min(1.0, disruption))
        if consequence in {
            VariantConsequence.STOP_GAINED,
            VariantConsequence.FRAMESHIFT,
            VariantConsequence.SPLICE_ACCEPTOR,
            VariantConsequence.SPLICE_DONOR,
            VariantConsequence.START_LOST,
        }:
            delta = max(delta, 0.95)
        elif consequence in {
            VariantConsequence.SYNONYMOUS,
            VariantConsequence.INTRON,
            VariantConsequence.UPSTREAM,
            VariantConsequence.DOWNSTREAM,
        }:
            delta = min(delta, 0.05)
        elif consequence in {
            VariantConsequence.INFRAME_INSERTION,
            VariantConsequence.INFRAME_DELETION,
        }:
            delta = max(delta, 0.45)

        kcat = max(self.min_scale, 1.0 - self.alpha * delta)
        km = 1.0 + self.beta * delta
        bind = max(self.min_scale, 1.0 - self.gamma * delta)
        # Severe disruption also reduces effective expression / soluble yield
        prod = max(self.min_scale, 1.0 - 0.5 * delta)
        return KineticScaleFactors(
            kcat_scale=kcat,
            km_scale=km,
            binding_scale=bind,
            production_scale=prod,
        )

    def evaluate_variant(
        self,
        protein_id: str,
        variant: VariantRecord | Mutation | int | str | Mapping[str, Any],
        *,
        consequence: Optional[VariantConsequence] = None,
    ) -> Tuple[DisruptionAssessment, KineticScaleFactors]:
        smap = self.get(protein_id)
        if smap is None:
            raise KeyError(f"No structural map registered for {protein_id!r}")
        residue = parse_residue_position(variant)
        if residue is None:
            # Fall back to mid-protein prior for unannotated missense
            residue = max(1, smap.sequence_length // 2)
            assessment = DisruptionAssessment(
                residue=residue,
                disruption=0.25,
                nearest_pocket=None,
                nearest_domain=None,
                sequence_distance=-1.0,
                spatial_distance=None,
                confidence_weight=0.5,
                notes="residue_inferred",
            )
        else:
            assessment = self.assess_residue(smap, residue)
        csq = consequence
        if csq is None and isinstance(variant, VariantRecord):
            csq = variant.consequence
        if csq is None:
            csq = VariantConsequence.MISSENSE
        scales = self.scales_from_disruption(assessment.disruption, consequence=csq)
        return assessment, scales

    def apply_scales(self, protein: Protein, scales: KineticScaleFactors) -> Protein:
        """
        Mutate ``protein.kinetics`` in-place for MassActionRHS consumption.

        ``vmax`` stands in for ``k_cat``; ``km`` and ``binding_affinity`` map
        directly onto :class:`KineticParameters`.
        """
        k = protein.kinetics
        protein.kinetics = k.with_updates(
            vmax=max(0.0, k.vmax * scales.kcat_scale),
            km=max(1e-9, k.km * scales.km_scale),
            binding_affinity=max(0.0, k.binding_affinity * scales.binding_scale),
            production_rate=max(0.0, k.production_rate * scales.production_scale),
        )
        protein.metadata["structure_kcat_scale"] = scales.kcat_scale
        protein.metadata["structure_km_scale"] = scales.km_scale
        protein.metadata["structure_binding_scale"] = scales.binding_scale
        protein.metadata["structure_production_scale"] = scales.production_scale
        return protein

    def apply_variant_to_network(
        self,
        network: SignalingNetwork,
        protein_name_or_id: str,
        variant: VariantRecord | Mutation | int | str,
        *,
        consequence: Optional[VariantConsequence] = None,
        also_scale_edges: bool = True,
    ) -> Tuple[DisruptionAssessment, KineticScaleFactors]:
        """
        Resolve a live :class:`Protein` in ``network`` and apply structural scales.

        When ``also_scale_edges`` is True, outgoing catalytic edge ``rate_constant``
        values are multiplied by ``kcat_scale`` so MassActionRHS fluxes shrink.
        """
        target: Optional[Protein] = None
        for entity in network.registry.entities():
            if not isinstance(entity, Protein):
                continue
            if entity.name == protein_name_or_id or entity.entity_id == protein_name_or_id:
                target = entity
                break
            if entity.metadata.get("uniprot_accession") == protein_name_or_id:
                target = entity
                break
        if target is None:
            raise KeyError(f"Protein {protein_name_or_id!r} not found in network")

        lookup_key = (
            str(target.metadata.get("uniprot_accession") or "")
            or protein_name_or_id
            or target.name
        )
        if self.get(lookup_key) is None and self.get(target.name) is not None:
            lookup_key = target.name
        assessment, scales = self.evaluate_variant(lookup_key, variant, consequence=consequence)
        self.apply_scales(target, scales)
        target.metadata["structure_disruption"] = assessment.disruption
        target.metadata["structure_residue"] = assessment.residue
        if also_scale_edges:
            for edge in network.out_edges(target.entity_id):
                edge.rate_constant = max(0.0, edge.rate_constant * scales.kcat_scale)
                edge.metadata["structure_kcat_scale"] = scales.kcat_scale
        return assessment, scales

    def mutation_from_assessment(
        self,
        target_id: str,
        assessment: DisruptionAssessment,
        scales: KineticScaleFactors,
        *,
        t_start: float = 0.0,
    ) -> Mutation:
        """
        Emit a Phase-1 :class:`Mutation` consistent with continuous disruption.

        Severe δ (≥ 0.85) → knockout; moderate → hypomorph with ``rate_scale``.
        """
        if assessment.disruption >= 0.85 or scales.kcat_scale <= self.min_scale * 1.5:
            return Mutation(
                target_id=target_id,
                kind=MutationKind.KNOCKOUT,
                name=f"struct_ko:res{assessment.residue}",
                t_start=t_start,
            )
        return Mutation(
            target_id=target_id,
            kind=MutationKind.HYPOMORPH,
            name=f"struct_hypo:res{assessment.residue}:d{assessment.disruption:.2f}",
            rate_scale=max(self.min_scale, scales.kcat_scale),
            permanent_lock=False,
            t_start=t_start,
        )
