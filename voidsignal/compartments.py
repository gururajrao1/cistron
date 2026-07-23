"""
Spatial compartment barriers and diffusion routing for VOIDSIGNAL Phase 3.

Partitions a :class:`~voidsignal.topology.SignalingNetwork` into geographic
tiers and enforces barrier policies: edges that cross structural boundaries
must route through :class:`~voidsignal.components.Receptor` or transporter
nodes. Cross-compartment fluxes are slowed by diffusion / permeability
coefficients relative to intra-compartment reactions.

Transport ODE (well-mixed pools linked by a permeable interface)::

    J_{i→j} = P · A · ( [X]_i / V_i − [X]_j / V_j )
    d[X]_i/dt  -= J_{i→j} · (V_ref / V_i)
    d[X]_j/dt  += J_{i→j} · (V_ref / V_j)

with flooring to keep concentrations non-negative under the integrator clamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import logging
import math

from voidsignal.components import (
    BiologicalEntity,
    CellularCompartment,
    EntityType,
    Protein,
    Receptor,
)
from voidsignal.topology import InteractionEdge, InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)


class CompartmentTier(Enum):
    """Canonical cellular geography tiers."""

    EXTRACELLULAR = "extracellular"
    PLASMA_MEMBRANE = "plasma_membrane"
    CYTOPLASM = "cytoplasm"
    NUCLEUS = "nucleus"
    OTHER = "other"

    @property
    def rank(self) -> int:
        order = {
            CompartmentTier.EXTRACELLULAR: 0,
            CompartmentTier.PLASMA_MEMBRANE: 1,
            CompartmentTier.CYTOPLASM: 2,
            CompartmentTier.NUCLEUS: 3,
            CompartmentTier.OTHER: 4,
        }
        return order[self]


_ADJACENT: Set[Tuple[CompartmentTier, CompartmentTier]] = {
    (CompartmentTier.EXTRACELLULAR, CompartmentTier.PLASMA_MEMBRANE),
    (CompartmentTier.PLASMA_MEMBRANE, CompartmentTier.EXTRACELLULAR),
    (CompartmentTier.PLASMA_MEMBRANE, CompartmentTier.CYTOPLASM),
    (CompartmentTier.CYTOPLASM, CompartmentTier.PLASMA_MEMBRANE),
    (CompartmentTier.CYTOPLASM, CompartmentTier.NUCLEUS),
    (CompartmentTier.NUCLEUS, CompartmentTier.CYTOPLASM),
}


def _tiers_adjacent(a: CompartmentTier, b: CompartmentTier) -> bool:
    if a is b:
        return True
    return (a, b) in _ADJACENT


@dataclass
class CompartmentSpec:
    """Runtime descriptor for a geographic compartment pool."""

    tier: CompartmentTier
    compartment_id: str
    name: str
    volume: float = 1.0
    permeability_default: float = 0.05
    interface_area: float = 1.0

    def __post_init__(self) -> None:
        if self.volume <= 0.0:
            raise ValueError("volume must be positive")
        if self.permeability_default < 0.0 or self.interface_area < 0.0:
            raise ValueError("permeability/area must be non-negative")


@dataclass
class TransportLink:
    """
    Diffusive / permeable link between two compartments for a cargo species.

    ``entity_a`` and ``entity_b`` are entity ids representing the *same*
    logical cargo pooled in each compartment (or the unique resident when
    single-pool models are used with edge slowing only).
    """

    entity_a: str
    entity_b: str
    compartment_a: str
    compartment_b: str
    permeability: float
    area: float = 1.0
    transporter_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.permeability < 0.0 or self.area < 0.0:
            raise ValueError("permeability/area must be non-negative")


@dataclass
class BarrierViolation:
    """Record of an edge that illegally crosses a structural boundary."""

    edge_id: str
    source_id: str
    target_id: str
    source_tier: CompartmentTier
    target_tier: CompartmentTier
    reason: str


class SpatialCompartmentModel:
    """
    Geographic partition + barrier routing for a signalling network.
    """

    GATEKEEPER_TYPES = {EntityType.RECEPTOR}
    GATEKEEPER_METADATA_FLAGS = ("is_transporter", "is_channel", "is_pore")

    def __init__(self, network: SignalingNetwork) -> None:
        self.network = network
        self.compartments: Dict[str, CompartmentSpec] = {}
        self._entity_tier: Dict[str, CompartmentTier] = {}
        self._entity_compartment: Dict[str, str] = {}
        self.transport_links: List[TransportLink] = []
        self.barrier_slowdown: float = 0.15
        """Rate multiplier applied to illegal/cross-boundary non-routed edges."""
        self.intra_rate_boost: float = 1.0

    # -- registration -------------------------------------------------------

    def register_compartment(self, spec: CompartmentSpec) -> CellularCompartment:
        self.compartments[spec.compartment_id] = spec
        if spec.compartment_id not in self.network.registry:
            comp = CellularCompartment(
                name=spec.name,
                compartment_id=spec.compartment_id,
                volume=spec.volume,
                metadata={"tier": spec.tier.value},
            )
            self.network.registry.register_compartment(comp)
            if not self.network.has_node(spec.compartment_id):
                self.network.add_node_id(spec.compartment_id)
            return comp
        existing = self.network.registry.get_compartment(spec.compartment_id)
        existing.volume = spec.volume
        existing.metadata["tier"] = spec.tier.value
        return existing

    def ensure_default_tiers(self) -> Dict[CompartmentTier, str]:
        """Create the four canonical compartments if absent."""
        mapping: Dict[CompartmentTier, str] = {}
        defaults = [
            (CompartmentTier.EXTRACELLULAR, "extracellular", 10.0),
            (CompartmentTier.PLASMA_MEMBRANE, "plasma_membrane", 0.2),
            (CompartmentTier.CYTOPLASM, "cytoplasm", 1.0),
            (CompartmentTier.NUCLEUS, "nucleus", 0.3),
        ]
        for tier, name, volume in defaults:
            # Reuse existing compartment with matching tier metadata / name
            existing_id = None
            for cid, spec in self.compartments.items():
                if spec.tier is tier:
                    existing_id = cid
                    break
            if existing_id is None:
                for comp in self.network.registry.compartments():
                    if comp.metadata.get("tier") == tier.value or comp.name == name:
                        existing_id = comp.compartment_id
                        break
            if existing_id is None:
                tmp = CellularCompartment(name=name, volume=volume, metadata={"tier": tier.value})
                spec = CompartmentSpec(
                    tier=tier,
                    compartment_id=tmp.compartment_id,
                    name=name,
                    volume=volume,
                )
                self.register_compartment(spec)
                existing_id = spec.compartment_id
            else:
                if existing_id not in self.compartments:
                    self.register_compartment(
                        CompartmentSpec(
                            tier=tier,
                            compartment_id=existing_id,
                            name=name,
                            volume=volume,
                        )
                    )
            mapping[tier] = existing_id
        return mapping

    def assign(self, entity_id: str, tier: CompartmentTier, compartment_id: Optional[str] = None) -> None:
        if entity_id not in self.network.registry:
            raise KeyError(f"Unknown entity {entity_id!r}")
        if compartment_id is None:
            tiers = self.ensure_default_tiers()
            compartment_id = tiers[tier]
        if compartment_id not in self.compartments:
            raise KeyError(f"Unknown compartment {compartment_id!r}")
        entity = self.network.registry.get(entity_id)
        # Move resident bookkeeping
        old = entity.compartment_id
        if old and old in {c.compartment_id for c in self.network.registry.compartments()}:
            try:
                self.network.registry.get_compartment(old).remove_resident(entity_id)
            except KeyError:
                pass
        entity.compartment_id = compartment_id
        entity.metadata["compartment_tier"] = tier.value
        self.network.registry.get_compartment(compartment_id).add_resident(entity_id)
        self._entity_tier[entity_id] = tier
        self._entity_compartment[entity_id] = compartment_id

    def assign_by_name(self, name: str, tier: CompartmentTier) -> None:
        for ent in self.network.registry.entities():
            if ent.name == name:
                self.assign(ent.entity_id, tier)
                return
        raise KeyError(f"No entity named {name!r}")

    def tier_of(self, entity_id: str) -> CompartmentTier:
        if entity_id in self._entity_tier:
            return self._entity_tier[entity_id]
        entity = self.network.registry.get(entity_id)
        raw = entity.metadata.get("compartment_tier")
        if raw:
            try:
                tier = CompartmentTier(str(raw))
                self._entity_tier[entity_id] = tier
                return tier
            except ValueError:
                pass
        if isinstance(entity, Receptor):
            return CompartmentTier.PLASMA_MEMBRANE
        return CompartmentTier.CYTOPLASM

    def is_gatekeeper(self, entity_id: str) -> bool:
        entity = self.network.registry.get(entity_id)
        if entity.entity_type in self.GATEKEEPER_TYPES:
            return True
        if any(entity.metadata.get(flag) for flag in self.GATEKEEPER_METADATA_FLAGS):
            return True
        if entity.metadata.get("role") in {"transporter", "channel", "pore"}:
            return True
        return False

    # -- barrier policy -----------------------------------------------------

    def validate_routing(self, *, autofix_slowdown: bool = True) -> List[BarrierViolation]:
        """
        Scan directed edges for illegal geographic jumps.

        Legal patterns
        --------------
        * Intra-compartment edges.
        * Adjacent tiers if source or target is a gatekeeper (Receptor /
          transporter), or the edge type is BINDING / TRANSLOCATION involving
          a membrane node.
        * Non-adjacent jumps (e.g. extracellular → nucleus) are always illegal
          without an explicit multi-hop path (flagged, optionally slowed).
        """
        violations: List[BarrierViolation] = []
        for edge in self.network.active_edges():
            src_tier = self.tier_of(edge.source_id)
            tgt_tier = self.tier_of(edge.target_id)
            if src_tier is tgt_tier:
                edge.metadata.setdefault("spatial_class", "intra")
                continue
            adjacent = _tiers_adjacent(src_tier, tgt_tier)
            gated = self.is_gatekeeper(edge.source_id) or self.is_gatekeeper(edge.target_id)
            translocation = edge.interaction_type in {
                InteractionType.BINDING,
                InteractionType.TRANSLOCATION,
                InteractionType.ACTIVATION,
            }
            if adjacent and gated and translocation:
                edge.metadata["spatial_class"] = "gated_boundary"
                # Slow vs intra-compartment kinetics
                if "spatial_rate_scale" not in edge.metadata:
                    scale = max(self.barrier_slowdown, 1e-3)
                    edge.metadata["spatial_rate_scale"] = scale
                    edge.rate_constant = max(0.0, edge.rate_constant * scale)
                continue
            if adjacent and gated:
                edge.metadata["spatial_class"] = "gated_boundary"
                if "spatial_rate_scale" not in edge.metadata:
                    scale = max(self.barrier_slowdown, 1e-3)
                    edge.metadata["spatial_rate_scale"] = scale
                    edge.rate_constant = max(0.0, edge.rate_constant * scale)
                continue
            reason = (
                "non_adjacent_tiers"
                if not adjacent
                else "missing_receptor_or_transporter"
            )
            violations.append(
                BarrierViolation(
                    edge_id=edge.edge_id,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    source_tier=src_tier,
                    target_tier=tgt_tier,
                    reason=reason,
                )
            )
            edge.metadata["spatial_class"] = "illegal_boundary"
            edge.metadata["spatial_violation"] = reason
            if autofix_slowdown:
                scale = max(self.barrier_slowdown * 0.25, 1e-4)
                edge.metadata["spatial_rate_scale"] = scale
                edge.rate_constant = max(0.0, edge.rate_constant * scale)
        if violations:
            logger.warning("Spatial routing found %d barrier violations", len(violations))
        return violations

    def mark_transporter(self, entity_id: str) -> None:
        entity = self.network.registry.get(entity_id)
        entity.metadata["is_transporter"] = True
        entity.metadata["role"] = "transporter"

    # -- diffusion links ----------------------------------------------------

    def add_transport_link(self, link: TransportLink) -> None:
        if link.entity_a not in self.network.registry or link.entity_b not in self.network.registry:
            raise KeyError("Transport link references unknown entities")
        self.transport_links.append(link)
        # Ensure a TRANSLOCATION edge exists for topology analytics
        self.network.connect(
            link.entity_a,
            link.entity_b,
            InteractionType.TRANSLOCATION,
            rate_constant=link.permeability,
            weight=link.area,
            metadata={
                "spatial_class": "diffusion",
                "compartment_a": link.compartment_a,
                "compartment_b": link.compartment_b,
                "transporter_id": link.transporter_id,
            },
        )

    def apply_transport_ode(
        self,
        conc: Mapping[str, float],
        dydt: Dict[str, float],
        *,
        v_ref: float = 1.0,
    ) -> None:
        """
        Inject diffusive exchange terms into ``dydt``.

        Uses concentration flooring; locked species are skipped.
        """
        for link in self.transport_links:
            a = link.entity_a
            b = link.entity_b
            if a not in dydt or b not in dydt:
                continue
            ent_a = self.network.registry.get(a)
            ent_b = self.network.registry.get(b)
            if ent_a.locked or ent_b.locked:
                continue
            spec_a = self.compartments.get(link.compartment_a)
            spec_b = self.compartments.get(link.compartment_b)
            vol_a = spec_a.volume if spec_a else 1.0
            vol_b = spec_b.volume if spec_b else 1.0
            ca = max(conc.get(a, 0.0), 0.0)
            cb = max(conc.get(b, 0.0), 0.0)
            # Chemical potential proxy: concentration density
            density_a = ca / vol_a
            density_b = cb / vol_b
            flux = link.permeability * link.area * (density_a - density_b)
            if not math.isfinite(flux):
                continue
            # Convert flux to concentration rates
            dydt[a] -= flux * (v_ref / vol_a)
            dydt[b] += flux * (v_ref / vol_b)

    def summary(self) -> Dict[str, object]:
        counts: Dict[str, int] = {}
        for tier in self._entity_tier.values():
            counts[tier.value] = counts.get(tier.value, 0) + 1
        return {
            "n_compartments": len(self.compartments),
            "entity_tier_counts": counts,
            "n_transport_links": len(self.transport_links),
        }


def annotate_standard_mapk_geography(network: SignalingNetwork) -> SpatialCompartmentModel:
    """
    Convenience: assign EGF extracellular, EGFR membrane, cascade cytoplasmic.
    """
    model = SpatialCompartmentModel(network)
    model.ensure_default_tiers()
    table = {
        "EGF": CompartmentTier.EXTRACELLULAR,
        "EGFR": CompartmentTier.PLASMA_MEMBRANE,
        "HRAS": CompartmentTier.PLASMA_MEMBRANE,
        "KRAS": CompartmentTier.PLASMA_MEMBRANE,
        "RAF1": CompartmentTier.CYTOPLASM,
        "BRAF": CompartmentTier.CYTOPLASM,
        "MAP2K1": CompartmentTier.CYTOPLASM,
        "MAP2K2": CompartmentTier.CYTOPLASM,
        "MAPK1": CompartmentTier.CYTOPLASM,
        "MAPK3": CompartmentTier.CYTOPLASM,
        "MAPK1_P": CompartmentTier.CYTOPLASM,
        "MAP2K1_P": CompartmentTier.NUCLEUS,
        "MAPK14": CompartmentTier.NUCLEUS,
        "MAPK8": CompartmentTier.NUCLEUS,
    }
    for ent in network.registry.entities():
        if ent.name in table:
            model.assign(ent.entity_id, table[ent.name])
        elif isinstance(ent, Receptor):
            model.assign(ent.entity_id, CompartmentTier.PLASMA_MEMBRANE)
    model.validate_routing(autofix_slowdown=True)
    return model
