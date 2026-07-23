"""
Disease phenotyping engine for VOIDSIGNAL Phase 4.

Warps a baseline :class:`~voidsignal.topology.SignalingNetwork` into concrete
pathological states that compile to :class:`~voidsignal.perturbation.Perturbation`
hooks for :class:`~voidsignal.simulation.DualEngineSimulator`.

Profiles
--------
* **Cancer signaling** — constitutive oncogene locks, negative-feedback
  attenuation, and anti-apoptotic survival pathway boosting.
* **Neurodegeneration** — time-dependent aggregation drift that progressively
  accelerates clearance (``δ_clearance``) of vulnerable nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
import logging

from voidsignal.components import KineticParameters, Protein
from voidsignal.perturbation import (
    Mutation,
    MutationKind,
    Perturbation,
    PerturbationManager,
)
from voidsignal.simulation import DualEngineSimulator, PerturbationHook, SimulationState
from voidsignal.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)


class PhenotypeKind(Enum):
    """High-level disease programme."""

    CANCER_SIGNALING = auto()
    NEURODEGENERATION = auto()
    CUSTOM = auto()


def _resolve_entity_id(network: SignalingNetwork, name_or_id: str) -> Optional[str]:
    if name_or_id in network.registry:
        return name_or_id
    for entity in network.registry.entities():
        if entity.name == name_or_id:
            return entity.entity_id
        if str(entity.metadata.get("uniprot_accession", "")).upper() == name_or_id.upper():
            return entity.entity_id
        if str(entity.metadata.get("gene_symbol", "")).upper() == name_or_id.upper():
            return entity.entity_id
    return None


def _resolve_many(network: SignalingNetwork, names: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name in names:
        eid = _resolve_entity_id(network, name)
        if eid is not None:
            out[name] = eid
    return out


@dataclass
class AggregationDrift(Perturbation):
    """
    Progressive aggregation / proteostasis failure.

    Clearance acceleration for a vulnerable node::

        k_deg(t) = k0 · (1 + α · max(0, t − t_onset)^power)
        δ_clearance(t) = 1 − 1 / (1 + α · max(0, t − t_onset)^power)

    Optionally bleeds concentration each step by a fraction of ``δ_clearance``.
    """

    target_id: str
    name: str = ""
    onset: float = 0.0
    alpha: float = 0.05
    power: float = 1.0
    max_scale: float = 25.0
    concentration_bleed: float = 0.0
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base_deg: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"aggregation:{self.target_id}"
        if self.alpha < 0.0:
            raise ValueError("alpha must be non-negative")
        if self.power <= 0.0:
            raise ValueError("power must be positive")
        if self.max_scale < 1.0:
            raise ValueError("max_scale must be ≥ 1")
        if not 0.0 <= self.concentration_bleed <= 1.0:
            raise ValueError("concentration_bleed must be in [0, 1]")

    def clearance_scale(self, t: float) -> float:
        age = max(0.0, t - self.onset)
        scale = 1.0 + self.alpha * (age**self.power)
        return min(self.max_scale, max(1.0, scale))

    def delta_clearance(self, t: float) -> float:
        scale = self.clearance_scale(t)
        return 1.0 - 1.0 / scale

    def apply(self, state: SimulationState, t: float) -> None:
        if self.t_end is not None and t > self.t_end + 1e-15:
            return
        if not self.is_active(t):
            return
        entity = state.entity(self.target_id)
        if self._base_deg is None:
            self._base_deg = max(entity.kinetics.degradation_rate, 1e-12)
        scale = self.clearance_scale(t)
        was_locked = entity.locked
        entity.locked = False
        entity.kinetics = entity.kinetics.with_updates(
            degradation_rate=min(self._base_deg * scale, self._base_deg * self.max_scale)
        )
        delta = self.delta_clearance(t)
        if self.concentration_bleed > 0.0 and entity.concentration > 0.0:
            bleed = self.concentration_bleed * delta * entity.concentration
            entity.set_concentration(max(0.0, entity.concentration - bleed))
        entity.metadata["delta_clearance"] = delta
        entity.metadata["aggregation_deg_scale"] = scale
        entity.locked = was_locked
        self.applied = True
        state.extras[f"aggregation:{self.target_id}"] = {
            "delta_clearance": delta,
            "deg_scale": scale,
        }


@dataclass
class FeedbackAttenuation(Perturbation):
    """Permanently (or windowed) scale selected inhibitory / feedback edges."""

    edge_ids: Set[str] = field(default_factory=set)
    scale: float = 0.05
    name: str = "feedback_attenuation"
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _original: Dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.scale < 0.0:
            raise ValueError("scale must be non-negative")

    def apply(self, state: SimulationState, t: float) -> None:
        if not self._original:
            for eid in self.edge_ids:
                self._original[eid] = state.network.get_edge(eid).rate_constant
        if self.t_end is not None and t > self.t_end + 1e-15:
            if self.applied:
                for eid, rate in self._original.items():
                    state.network.get_edge(eid).rate_constant = rate
                self.applied = False
            return
        if not self.is_active(t):
            return
        for eid, rate in self._original.items():
            state.network.get_edge(eid).rate_constant = max(0.0, rate * self.scale)
        self.applied = True


@dataclass
class DiseasePhenotype:
    """
    Compiled phenotypic programme ready for DualEngineSimulator injection.

    Attributes
    ----------
    perturbations :
        Ordered list of genetic / kinetic / aggregation drivers.
    metadata :
        Free-form phenotype annotations (driver genes, references, …).
    """

    name: str
    kind: PhenotypeKind
    perturbations: List[Perturbation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    network_tags: Dict[str, Any] = field(default_factory=dict)

    def manager(self) -> PerturbationManager:
        mgr = PerturbationManager()
        mgr.extend(self.perturbations)
        return mgr

    def hooks(self) -> List[PerturbationHook]:
        return self.manager().hooks()

    def apply_static(self, network: SignalingNetwork) -> None:
        """
        Stamp phenotype metadata onto the network and ensure survival nodes
        tagged in ``network_tags`` exist / are boosted at t = 0 without ODE.
        """
        network.metadata["disease_phenotype"] = self.name
        network.metadata["disease_kind"] = self.kind.name
        for key, value in self.network_tags.items():
            network.metadata[key] = value

    def load_into(self, engine: DualEngineSimulator) -> PerturbationManager:
        """Attach all phenotype hooks to a live dual engine and tag its network."""
        self.apply_static(engine.network)
        mgr = self.manager()
        for hook in mgr.hooks():
            engine.add_hook(hook)
        logger.info(
            "Loaded phenotype %r (%s) with %d perturbations",
            self.name,
            self.kind.name,
            len(self.perturbations),
        )
        return mgr

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.name,
            "n_perturbations": len(self.perturbations),
            "perturbations": [
                {
                    "name": getattr(p, "name", type(p).__name__),
                    "class": type(p).__name__,
                    "t_start": getattr(p, "t_start", 0.0),
                    "t_end": getattr(p, "t_end", None),
                }
                for p in self.perturbations
            ],
            "metadata": dict(self.metadata),
        }


@dataclass
class CancerSignalingConfig:
    """Controls for the cancer signalling warp."""

    oncogenes: Sequence[str] = ("KRAS", "EGFR", "RAS", "RAF")
    expression_level: float = 2.0
    attenuate_negative_feedback: bool = True
    feedback_scale: float = 0.05
    survival_nodes: Sequence[str] = ("BCL2", "AKT", "PI3K")
    survival_production_boost: float = 2.5
    ensure_missing_survival: bool = False
    t_start: float = 0.0


@dataclass
class NeurodegenerationConfig:
    """Controls for progressive proteostasis failure."""

    vulnerable_nodes: Sequence[str] = ("TAU", "SNCA", "APP", "TDP43")
    onset: float = 10.0
    alpha: float = 0.08
    power: float = 1.25
    max_scale: float = 20.0
    concentration_bleed: float = 0.002
    t_start: float = 0.0
    t_end: Optional[float] = None


class DiseasePhenotypingEngine:
    """
    Factory that builds :class:`DiseasePhenotype` profiles from a live network.
    """

    def __init__(self, network: SignalingNetwork) -> None:
        self.network = network

    def cancer_signaling(
        self,
        config: Optional[CancerSignalingConfig] = None,
        *,
        name: str = "cancer_signaling",
    ) -> DiseasePhenotype:
        cfg = config or CancerSignalingConfig()
        perts: List[Perturbation] = []
        oncogenes = _resolve_many(self.network, list(cfg.oncogenes))
        for label, eid in oncogenes.items():
            perts.append(
                Mutation(
                    target_id=eid,
                    kind=MutationKind.CONSTITUTIVE_ACTIVATION,
                    expression_level=cfg.expression_level,
                    name=f"cancer_constitutive:{label}",
                    t_start=cfg.t_start,
                    permanent_lock=True,
                )
            )

        feedback_ids: Set[str] = set()
        if cfg.attenuate_negative_feedback:
            for edge in self.network.active_edges():
                if edge.interaction_type.is_inhibitory or edge.metadata.get("feedback"):
                    feedback_ids.add(edge.edge_id)
            # Also capture simple product→upstream inhibitor loops
            loops = self.network.detect_feedback_loops(max_length=6)
            for cycle in loops:
                for i in range(len(cycle) - 1):
                    src, tgt = cycle[i], cycle[i + 1]
                    for edge in self.network.out_edges(src):
                        if edge.target_id == tgt and edge.interaction_type.is_inhibitory:
                            feedback_ids.add(edge.edge_id)
            if feedback_ids:
                perts.append(
                    FeedbackAttenuation(
                        edge_ids=feedback_ids,
                        scale=cfg.feedback_scale,
                        name="cancer_feedback_break",
                        t_start=cfg.t_start,
                    )
                )

        survival = _resolve_many(self.network, list(cfg.survival_nodes))
        if cfg.ensure_missing_survival:
            for label in cfg.survival_nodes:
                if label in survival:
                    continue
                node = Protein(
                    name=label,
                    concentration=0.5,
                    kinetics=KineticParameters(
                        production_rate=0.1 * cfg.survival_production_boost,
                        degradation_rate=0.05,
                        basal_activity=0.3,
                    ),
                    metadata={"role": "anti_apoptotic", "disease_injected": True},
                )
                self.network.add_node(node)
                survival[label] = node.entity_id
                # Wire soft survival ← oncogene activation when possible
                if oncogenes:
                    first_onc = next(iter(oncogenes.values()))
                    self.network.connect(
                        first_onc,
                        node.entity_id,
                        InteractionType.ACTIVATION,
                        rate_constant=0.4,
                        metadata={"disease_edge": "survival"},
                    )

        for label, eid in survival.items():
            perts.append(
                Mutation(
                    target_id=eid,
                    kind=MutationKind.OVEREXPRESSION,
                    expression_level=cfg.expression_level * 0.75,
                    rate_scale=cfg.survival_production_boost,
                    name=f"cancer_survival:{label}",
                    t_start=cfg.t_start,
                    permanent_lock=False,
                )
            )

        return DiseasePhenotype(
            name=name,
            kind=PhenotypeKind.CANCER_SIGNALING,
            perturbations=perts,
            metadata={
                "oncogenes": list(oncogenes.keys()),
                "survival_nodes": list(survival.keys()),
                "feedback_edges": len(feedback_ids),
                "config": {
                    "expression_level": cfg.expression_level,
                    "feedback_scale": cfg.feedback_scale,
                },
            },
            network_tags={
                "phenotype": "cancer",
                "constitutive_oncogenes": list(oncogenes.values()),
            },
        )

    def neurodegeneration(
        self,
        config: Optional[NeurodegenerationConfig] = None,
        *,
        name: str = "neurodegeneration",
    ) -> DiseasePhenotype:
        cfg = config or NeurodegenerationConfig()
        vulnerable = _resolve_many(self.network, list(cfg.vulnerable_nodes))
        if not vulnerable:
            # Fall back to highest-abundance proteins as proxy proteotoxic load
            proteins = [
                e for e in self.network.registry.entities() if isinstance(e, Protein)
            ]
            proteins.sort(key=lambda p: p.concentration, reverse=True)
            for prot in proteins[: max(1, min(3, len(proteins)))]:
                vulnerable[prot.name] = prot.entity_id

        perts: List[Perturbation] = []
        for label, eid in vulnerable.items():
            perts.append(
                AggregationDrift(
                    target_id=eid,
                    name=f"neuro_agg:{label}",
                    onset=cfg.onset,
                    alpha=cfg.alpha,
                    power=cfg.power,
                    max_scale=cfg.max_scale,
                    concentration_bleed=cfg.concentration_bleed,
                    t_start=cfg.t_start,
                    t_end=cfg.t_end,
                )
            )
            # Mild basal hypomorph on production of aggregating species
            perts.append(
                Mutation(
                    target_id=eid,
                    kind=MutationKind.HYPOMORPH,
                    rate_scale=0.85,
                    name=f"neuro_hypomorph:{label}",
                    t_start=cfg.t_start,
                    permanent_lock=False,
                )
            )

        return DiseasePhenotype(
            name=name,
            kind=PhenotypeKind.NEURODEGENERATION,
            perturbations=perts,
            metadata={
                "vulnerable_nodes": list(vulnerable.keys()),
                "onset": cfg.onset,
                "alpha": cfg.alpha,
                "power": cfg.power,
            },
            network_tags={
                "phenotype": "neurodegeneration",
                "aggregating_nodes": list(vulnerable.values()),
            },
        )

    def custom(
        self,
        name: str,
        perturbations: Sequence[Perturbation],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> DiseasePhenotype:
        return DiseasePhenotype(
            name=name,
            kind=PhenotypeKind.CUSTOM,
            perturbations=list(perturbations),
            metadata=dict(metadata or {}),
        )


def build_cancer_phenotype(
    network: SignalingNetwork,
    config: Optional[CancerSignalingConfig] = None,
    **kwargs: Any,
) -> DiseasePhenotype:
    """Convenience wrapper around :meth:`DiseasePhenotypingEngine.cancer_signaling`."""
    return DiseasePhenotypingEngine(network).cancer_signaling(config, **kwargs)


def build_neurodegeneration_phenotype(
    network: SignalingNetwork,
    config: Optional[NeurodegenerationConfig] = None,
    **kwargs: Any,
) -> DiseasePhenotype:
    """Convenience wrapper around :meth:`DiseasePhenotypingEngine.neurodegeneration`."""
    return DiseasePhenotypingEngine(network).neurodegeneration(config, **kwargs)
