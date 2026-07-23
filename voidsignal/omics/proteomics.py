"""
Proteomic PTM layer — phosphorylation, ubiquitination, acetylation networks.

Computes active vs inactive protein fractions and maps PTM crosstalk onto
:class:`~voidsignal.structures.KineticScaleFactors` for MassActionRHS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

from voidsignal.components import (
    BiologicalEntity,
    ModificationSite,
    ModificationType,
    Protein,
)
from voidsignal.structures import KineticScaleFactors
from voidsignal.topology import SignalingNetwork


class PTMKind(str, Enum):
    PHOSPHORYLATION = "phosphorylation"
    UBIQUITINATION = "ubiquitination"
    ACETYLATION = "acetylation"
    METHYLATION = "methylation"


@dataclass(frozen=True)
class PTMSite:
    """
    Occupancy of one residue-level PTM.

    ``occupancy`` ∈ [0, 1] is the modified fraction of the protein pool.
    ``effect`` describes how the modification alters activity.
    """

    protein: str
    residue: str
    kind: PTMKind
    occupancy: float
    effect: str = "activate"
    """One of: activate, inhibit, degrade, stabilize, neutral."""
    strength: float = 1.0
    crosstalk_group: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.protein or not self.residue:
            raise ValueError("protein and residue must be non-empty")
        if not math.isfinite(self.occupancy) or not 0.0 <= self.occupancy <= 1.0:
            raise ValueError("occupancy must be finite in [0, 1]")
        if self.strength < 0.0 or not math.isfinite(self.strength):
            raise ValueError("strength must be non-negative finite")
        if self.effect not in {"activate", "inhibit", "degrade", "stabilize", "neutral"}:
            raise ValueError(f"unknown PTM effect {self.effect!r}")

    def to_modification_site(self) -> ModificationSite:
        mod = {
            PTMKind.PHOSPHORYLATION: ModificationType.PHOSPHORYLATION,
            PTMKind.UBIQUITINATION: ModificationType.UBIQUITINATION,
            PTMKind.ACETYLATION: ModificationType.ACETYLATION,
            PTMKind.METHYLATION: ModificationType.METHYLATION,
        }[self.kind]
        return ModificationSite(
            name=f"{self.residue}:{self.kind.value}",
            modification=mod,
            stoichiometry=self.occupancy,
            rate_constant=self.strength,
        )


@dataclass
class PTMProfile:
    """Patient / sample PTM occupancy matrix."""

    sample_id: str = "sample"
    sites: List[PTMSite] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def proteins(self) -> List[str]:
        return sorted({s.protein.upper() for s in self.sites})

    def by_protein(self) -> Dict[str, List[PTMSite]]:
        out: Dict[str, List[PTMSite]] = {}
        for s in self.sites:
            out.setdefault(s.protein.upper(), []).append(s)
        return out


@dataclass(frozen=True)
class ProteinActivityState:
    """
    Active / inactive / degraded fractions for one protein after PTM aggregation.

    Fractions are normalized to sum ≈ 1 (numerical clamp).
    """

    protein: str
    active_fraction: float
    inactive_fraction: float
    degraded_fraction: float
    kcat_scale: float
    km_scale: float
    degradation_scale: float
    production_scale: float
    binding_scale: float
    site_count: int

    def as_kinetic_scales(self) -> KineticScaleFactors:
        return KineticScaleFactors(
            kcat_scale=self.kcat_scale,
            km_scale=self.km_scale,
            binding_scale=self.binding_scale,
            production_scale=self.production_scale,
        )


def _crosstalk_multiplier(sites: Sequence[PTMSite]) -> float:
    """
    Simple PTM crosstalk: opposing marks in the same group partially cancel;
    synergistic activate×activate boosts slightly.
    """
    groups: Dict[str, List[PTMSite]] = {}
    for s in sites:
        if s.crosstalk_group:
            groups.setdefault(s.crosstalk_group, []).append(s)
    mult = 1.0
    for members in groups.values():
        if len(members) < 2:
            continue
        acts = [m for m in members if m.effect == "activate"]
        inhs = [m for m in members if m.effect == "inhibit"]
        if acts and inhs:
            # competitive occupancy dampening
            a = sum(m.occupancy * m.strength for m in acts) / len(acts)
            i = sum(m.occupancy * m.strength for m in inhs) / len(inhs)
            mult *= max(0.2, 1.0 - 0.5 * min(a, i))
        elif len(acts) >= 2:
            mult *= 1.0 + 0.1 * min(1.0, sum(m.occupancy for m in acts) / len(acts))
    return max(0.2, min(1.5, mult))


def aggregate_ptm_state(protein: str, sites: Sequence[PTMSite]) -> ProteinActivityState:
    """
    Map residue PTMs → active fraction and kinetic scales.

    Model (mass-conserving fractions):
    - activating occupancy raises active pool
    - inhibiting occupancy raises inactive pool
    - ubiquitination raises degraded pool (and degradation_rate scale)
    - acetylation mildly stabilizes (lowers degradation, raises binding)
    """
    if not sites:
        return ProteinActivityState(
            protein=protein.upper(),
            active_fraction=1.0,
            inactive_fraction=0.0,
            degraded_fraction=0.0,
            kcat_scale=1.0,
            km_scale=1.0,
            degradation_scale=1.0,
            production_scale=1.0,
            binding_scale=1.0,
            site_count=0,
        )

    act = 0.0
    inh = 0.0
    deg = 0.0
    stab = 0.0
    for s in sites:
        w = s.occupancy * s.strength
        if s.effect == "activate":
            act += w
        elif s.effect == "inhibit":
            inh += w
        elif s.effect == "degrade" or s.kind == PTMKind.UBIQUITINATION:
            deg += w
        elif s.effect == "stabilize":
            stab += w
        elif s.kind == PTMKind.ACETYLATION and s.effect == "neutral":
            stab += 0.5 * w
        elif s.kind == PTMKind.PHOSPHORYLATION and s.effect == "neutral":
            act += 0.3 * w

    xt = _crosstalk_multiplier(sites)
    act *= xt

    # Softmax-like normalization into three pools
    raw_active = 1.0 + act
    raw_inactive = inh
    raw_degraded = deg
    total = raw_active + raw_inactive + raw_degraded
    active_f = raw_active / total
    inactive_f = raw_inactive / total
    degraded_f = raw_degraded / total

    # Kinetic mapping
    kcat = max(0.02, active_f * (1.0 + 0.35 * min(act, 2.0)))
    km = max(0.25, 1.0 + 1.2 * inactive_f - 0.25 * active_f)
    deg_scale = max(0.2, 1.0 + 1.8 * degraded_f - 0.6 * min(stab, 1.5))
    prod = max(0.2, 1.0 - 0.7 * degraded_f)
    bind = max(0.1, 1.0 - 0.5 * inactive_f + 0.2 * min(stab, 1.0))

    return ProteinActivityState(
        protein=protein.upper(),
        active_fraction=active_f,
        inactive_fraction=inactive_f,
        degraded_fraction=degraded_f,
        kcat_scale=kcat,
        km_scale=km,
        degradation_scale=deg_scale,
        production_scale=prod,
        binding_scale=bind,
        site_count=len(sites),
    )


class PTMTransformer:
    """Apply PTM occupancy matrices onto protein nodes and ModificationSites."""

    def __init__(self, *, also_edges: bool = True, sync_modification_sites: bool = True) -> None:
        self.also_edges = also_edges
        self.sync_modification_sites = sync_modification_sites

    def compute_states(self, profile: PTMProfile) -> Dict[str, ProteinActivityState]:
        return {p: aggregate_ptm_state(p, sites) for p, sites in profile.by_protein().items()}

    def apply(
        self,
        network: SignalingNetwork,
        profile: PTMProfile,
        *,
        gene_aliases: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, ProteinActivityState]:
        states = self.compute_states(profile)
        name_map = _entity_name_index(network)
        aliases = {k.upper(): v for k, v in (gene_aliases or {}).items()}
        by_prot = profile.by_protein()

        for protein, state in states.items():
            target = aliases.get(protein, protein)
            ent = _resolve_entity(name_map, target)
            if ent is None:
                continue
            k = ent.kinetics
            ent.kinetics = k.with_updates(
                vmax=max(0.0, k.vmax * state.kcat_scale),
                km=max(1e-9, k.km * state.km_scale),
                degradation_rate=max(1e-9, k.degradation_rate * state.degradation_scale),
                production_rate=max(0.0, k.production_rate * state.production_scale),
                binding_affinity=max(0.0, k.binding_affinity * state.binding_scale),
                basal_activity=max(0.0, min(1.0, k.basal_activity * state.active_fraction + 0.05 * state.active_fraction)),
            )
            ent.metadata["ptm_active_fraction"] = state.active_fraction
            ent.metadata["ptm_inactive_fraction"] = state.inactive_fraction
            ent.metadata["ptm_degraded_fraction"] = state.degraded_fraction
            ent.metadata["ptm_kcat_scale"] = state.kcat_scale

            if self.sync_modification_sites and isinstance(ent, Protein):
                sites = by_prot.get(protein, [])
                # Replace matching site names; keep unrelated sites
                new_sites = [s.to_modification_site() for s in sites]
                existing = [
                    ms
                    for ms in ent.modification_sites
                    if not any(ms.name == ns.name for ns in new_sites)
                ]
                ent.modification_sites = existing + new_sites

            if self.also_edges:
                for edge in network.out_edges(ent.entity_id):
                    edge.rate_constant = max(0.0, edge.rate_constant * state.kcat_scale)
        return states


def make_demo_ptm_profile(sample_id: str = "PTM_DEMO") -> PTMProfile:
    """ERK activating phospho + MEK inhibitory phospho + EGFR ubiquitin demo."""
    return PTMProfile(
        sample_id=sample_id,
        sites=[
            PTMSite(
                protein="ERK",
                residue="T202",
                kind=PTMKind.PHOSPHORYLATION,
                occupancy=0.82,
                effect="activate",
                strength=1.2,
                crosstalk_group="ERK_act",
            ),
            PTMSite(
                protein="ERK",
                residue="Y204",
                kind=PTMKind.PHOSPHORYLATION,
                occupancy=0.75,
                effect="activate",
                strength=1.1,
                crosstalk_group="ERK_act",
            ),
            PTMSite(
                protein="MEK",
                residue="S212",
                kind=PTMKind.PHOSPHORYLATION,
                occupancy=0.4,
                effect="inhibit",
                strength=1.0,
                crosstalk_group="MEK_gate",
            ),
            PTMSite(
                protein="MEK",
                residue="K97",
                kind=PTMKind.ACETYLATION,
                occupancy=0.25,
                effect="stabilize",
                strength=0.8,
                crosstalk_group="MEK_gate",
            ),
            PTMSite(
                protein="EGFR",
                residue="K721",
                kind=PTMKind.UBIQUITINATION,
                occupancy=0.35,
                effect="degrade",
                strength=1.0,
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
    return name_map.get(key.split("-")[0].split("_")[0])
