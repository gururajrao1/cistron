"""
Perturbation management for VOIDSIGNAL.

Provides a clean mid-simulation injection API for:

* **Mutations** — gene knockouts, constitutive activation / repression,
  kinetic rewiring (altered production or degradation).
* **Drug perturbations** — competitive and non-competitive inhibition of
  a target species or of a specific interaction edge, with explicit
  concentration schedules.

Perturbations compile into :class:`~voidsignal.simulation.PerturbationHook`
callables that the Boolean / ODE engines invoke before each step. Multiple
perturbations compose safely through :class:`PerturbationManager`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Sequence, Set
import math

from voidsignal.components import ActivityState, BiologicalEntity, KineticParameters
from voidsignal.simulation import PerturbationHook, SimulationState
from voidsignal.topology import InteractionEdge, SignalingNetwork


class MutationKind(Enum):
    """Discrete classes of genetic / functional mutations."""

    KNOCKOUT = auto()
    """Force activity OFF and concentration → 0; lock both channels."""

    CONSTITUTIVE_ACTIVATION = auto()
    """Force activity ON at a specified expression level; lock Boolean."""

    CONSTITUTIVE_REPRESSION = auto()
    """Force activity OFF while optionally leaving a residual concentration."""

    OVEREXPRESSION = auto()
    """Multiply production_rate (and optionally set a higher floor concentration)."""

    HYPOMORPH = auto()
    """Partial loss-of-function: scale production / catalytic rates by a factor < 1."""

    ALTER_DEGRADATION = auto()
    """Rewrite the first-order degradation constant."""


class InhibitionModel(Enum):
    """
    Pharmacological inhibition modalities.

    COMPETITIVE
        Drug and substrate compete for the same site. Effective activity:

            v' = v · (1 / (1 + [I]/K_i_app))

        with ``K_i_app = K_i · (1 + [S]/K_m)`` when substrate context is known,
        else ``K_i_app = K_i``. Also raises apparent ``K_m``.

    NONCOMPETITIVE
        Drug binds an allosteric site; depresses V_max independently of substrate:

            v' = v · (1 / (1 + [I]/K_i))

    UNCOMPETITIVE
        Drug binds only the enzyme–substrate complex:

            v' = v · (1 / (1 + [I]/K_i · (1 + K_m/[S])))

    ALLOSTERIC
        Pure velocity modulation with Hill cooperativity *n*:

            v' = v · (1 / (1 + ([I]/K_i)^n))
    """

    COMPETITIVE = "competitive"
    NONCOMPETITIVE = "noncompetitive"
    UNCOMPETITIVE = "uncompetitive"
    ALLOSTERIC = "allosteric"


class Perturbation(ABC):
    """Base type for anything that can rewrite network state at time *t*."""

    name: str
    t_start: float
    t_end: Optional[float]
    applied: bool

    @abstractmethod
    def apply(self, state: SimulationState, t: float) -> None:
        """Mutate ``state.network`` in-place when *t* is in the active window."""

    def is_active(self, t: float) -> bool:
        if t + 1e-15 < self.t_start:
            return False
        if self.t_end is not None and t > self.t_end + 1e-15:
            return False
        return True

    def as_hook(self) -> PerturbationHook:
        """Compile this perturbation into an engine-compatible hook."""

        def hook(state: SimulationState, t: float) -> None:
            # Always dispatch: ``apply`` implementations own active-window and
            # post-window restore / washout logic.
            self.apply(state, t)

        return hook


@dataclass
class Mutation(Perturbation):
    """
    Genetic / functional alteration of a single entity.

    Parameters
    ----------
    target_id :
        Entity to mutate.
    kind :
        Mutation class (knockout, constitutive activation, …).
    expression_level :
        Concentration enforced for constitutive activation / overexpression.
    rate_scale :
        Multiplier for hypomorph / overexpression kinetic rewrites.
    degradation_rate :
        Absolute k_deg used by ``ALTER_DEGRADATION``.
    t_start / t_end :
        Active time window. ``t_end=None`` means permanent once started.
    permanent_lock :
        If True, knockouts / constitutive mutants stay locked after first apply.
    """

    target_id: str
    kind: MutationKind
    name: str = ""
    expression_level: float = 1.0
    rate_scale: float = 1.0
    degradation_rate: Optional[float] = None
    t_start: float = 0.0
    t_end: Optional[float] = None
    permanent_lock: bool = True
    applied: bool = field(default=False, init=False)
    _original_kinetics: Optional[KineticParameters] = field(default=None, init=False, repr=False)
    _original_lock: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"{self.kind.name.lower()}:{self.target_id}"
        if self.expression_level < 0.0:
            raise ValueError("expression_level must be non-negative")
        if self.rate_scale < 0.0:
            raise ValueError("rate_scale must be non-negative")
        if self.degradation_rate is not None and self.degradation_rate < 0.0:
            raise ValueError("degradation_rate must be non-negative")

    def _unlock_write(self, entity: BiologicalEntity) -> None:
        entity.locked = False
        entity.metadata.pop("lock_boolean", None)

    def _lock_entity(self, entity: BiologicalEntity, lock_boolean: bool = True) -> None:
        entity.locked = True
        if lock_boolean:
            entity.metadata["lock_boolean"] = True

    def apply(self, state: SimulationState, t: float) -> None:
        entity = state.entity(self.target_id)

        # Restore after window closes (non-permanent mutations only)
        if self.t_end is not None and t > self.t_end + 1e-15:
            if self.applied and not self.permanent_lock and self._original_kinetics is not None:
                self._unlock_write(entity)
                entity.kinetics = self._original_kinetics
                entity.locked = self._original_lock
                self.applied = False
            return

        if not self.is_active(t):
            return

        if self._original_kinetics is None:
            self._original_kinetics = entity.kinetics
            self._original_lock = entity.locked

        if self.kind is MutationKind.KNOCKOUT:
            self._unlock_write(entity)
            entity.set_concentration(0.0)
            entity.set_boolean(ActivityState.OFF)
            entity.kinetics = entity.kinetics.with_updates(production_rate=0.0, basal_activity=0.0)
            if self.permanent_lock:
                self._lock_entity(entity, lock_boolean=True)
            self.applied = True
            return

        if self.kind is MutationKind.CONSTITUTIVE_ACTIVATION:
            self._unlock_write(entity)
            entity.set_concentration(self.expression_level)
            entity.set_boolean(ActivityState.ON)
            entity.kinetics = entity.kinetics.with_updates(
                production_rate=max(entity.kinetics.production_rate, self.expression_level),
                basal_activity=1.0,
            )
            if self.permanent_lock:
                self._lock_entity(entity, lock_boolean=True)
            self.applied = True
            return

        if self.kind is MutationKind.CONSTITUTIVE_REPRESSION:
            self._unlock_write(entity)
            entity.set_boolean(ActivityState.OFF)
            residual = min(entity.concentration, self.expression_level)
            entity.set_concentration(residual)
            entity.kinetics = entity.kinetics.with_updates(basal_activity=0.0)
            if self.permanent_lock:
                self._lock_entity(entity, lock_boolean=True)
            self.applied = True
            return

        if self.kind is MutationKind.OVEREXPRESSION:
            if not self.applied:
                self._unlock_write(entity)
                entity.kinetics = entity.kinetics.with_updates(
                    production_rate=self._original_kinetics.production_rate * self.rate_scale
                )
                entity.set_concentration(max(entity.concentration, self.expression_level))
                self.applied = True
            return

        if self.kind is MutationKind.HYPOMORPH:
            if not self.applied:
                if self.rate_scale > 1.0:
                    raise ValueError("HYPOMORPH rate_scale must be ≤ 1")
                self._unlock_write(entity)
                entity.kinetics = entity.kinetics.with_updates(
                    production_rate=self._original_kinetics.production_rate * self.rate_scale,
                    vmax=self._original_kinetics.vmax * self.rate_scale,
                )
                self.applied = True
            return

        if self.kind is MutationKind.ALTER_DEGRADATION:
            if self.degradation_rate is None:
                raise ValueError("ALTER_DEGRADATION requires degradation_rate")
            if not self.applied:
                self._unlock_write(entity)
                entity.kinetics = entity.kinetics.with_updates(degradation_rate=self.degradation_rate)
                self.applied = True
            return

        raise ValueError(f"Unhandled mutation kind {self.kind!r}")


@dataclass
class DrugPerturbation(Perturbation):
    """
    Pharmacological intervention with an explicit concentration schedule.

    The drug may inhibit:

    * a **target entity** (scales effective concentration / production seen by
      downstream reactions via metadata flags consumed mid-step), and/or
    * a set of **interaction edges** (scales ``rate_constant`` while active).

    Concentration schedule
    ----------------------
    ``concentration`` is the plateau level. If ``dosing`` is provided it is a
    sorted list of ``(time, concentration)`` knots; piecewise-constant dosing
    is interpolated by right-continuous steps. Otherwise a single-bolus
    plateau between ``t_start`` and ``t_end`` is used.
    """

    target_id: Optional[str] = None
    name: str = ""
    model: InhibitionModel = InhibitionModel.COMPETITIVE
    concentration: float = 1.0
    ki: float = 1.0
    km: float = 1.0
    hill_coefficient: float = 1.0
    substrate_id: Optional[str] = None
    edge_ids: Set[str] = field(default_factory=set)
    dosing: List[tuple[float, float]] = field(default_factory=list)
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _original_rates: Dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _original_target_kinetics: Optional[KineticParameters] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            label = self.target_id or "edges"
            self.name = f"drug[{self.model.value}]:{label}"
        if self.concentration < 0.0:
            raise ValueError("concentration must be non-negative")
        if self.ki <= 0.0:
            raise ValueError("ki must be positive")
        if self.km <= 0.0:
            raise ValueError("km must be positive")
        if self.hill_coefficient <= 0.0:
            raise ValueError("hill_coefficient must be positive")
        if self.target_id is None and not self.edge_ids:
            raise ValueError("DrugPerturbation requires target_id and/or edge_ids")
        if self.dosing:
            self.dosing = sorted(self.dosing, key=lambda knot: knot[0])
            for _, conc in self.dosing:
                if conc < 0.0:
                    raise ValueError("dosing concentrations must be non-negative")

    def drug_level(self, t: float) -> float:
        """Piecewise-constant drug concentration at time *t*."""
        if not self.is_active(t):
            return 0.0
        if not self.dosing:
            return self.concentration
        level = self.dosing[0][1]
        for knot_t, knot_c in self.dosing:
            if t + 1e-15 >= knot_t:
                level = knot_c
            else:
                break
        return level

    def inhibition_factor(self, drug_conc: float, substrate_conc: float = 0.0) -> float:
        """
        Return multiplicative activity factor ∈ (0, 1].

        Factor → 0 under saturating inhibition; 1 when ``drug_conc == 0``.
        """
        if drug_conc <= 0.0:
            return 1.0
        n = self.hill_coefficient
        if self.model is InhibitionModel.COMPETITIVE:
            ki_app = self.ki * (1.0 + max(substrate_conc, 0.0) / self.km)
            return 1.0 / (1.0 + drug_conc / max(ki_app, 1e-15))
        if self.model is InhibitionModel.NONCOMPETITIVE:
            return 1.0 / (1.0 + drug_conc / self.ki)
        if self.model is InhibitionModel.UNCOMPETITIVE:
            # Avoid division by zero when substrate is absent: no ES complex ⇒ no inhibition
            if substrate_conc <= 0.0:
                return 1.0
            return 1.0 / (1.0 + drug_conc / (self.ki * (1.0 + self.km / substrate_conc)))
        if self.model is InhibitionModel.ALLOSTERIC:
            ratio = max(drug_conc, 0.0) / self.ki
            return 1.0 / (1.0 + ratio**n)
        raise ValueError(f"Unknown inhibition model {self.model!r}")

    def apparent_km_scale(self, drug_conc: float, substrate_conc: float = 0.0) -> float:
        """Multiplicative scale for apparent Michaelis constant (≥ 1 for competitive)."""
        if drug_conc <= 0.0:
            return 1.0
        if self.model is InhibitionModel.COMPETITIVE:
            return 1.0 + drug_conc / self.ki
        if self.model is InhibitionModel.UNCOMPETITIVE:
            # Uncompetitive lowers apparent Km
            return 1.0 / (1.0 + drug_conc / self.ki)
        if self.model is InhibitionModel.ALLOSTERIC:
            # Mild affinity shift under allosteric load
            return 1.0 + 0.25 * (drug_conc / self.ki) ** self.hill_coefficient
        return 1.0

    def _cache_originals(self, network: SignalingNetwork) -> None:
        for edge_id in self.edge_ids:
            if edge_id not in self._original_rates:
                self._original_rates[edge_id] = network.get_edge(edge_id).rate_constant
        if self.target_id is not None and self._original_target_kinetics is None:
            entity = network.registry.get(self.target_id)
            self._original_target_kinetics = entity.kinetics

    def _restore(self, network: SignalingNetwork) -> None:
        for edge_id, rate in self._original_rates.items():
            network.get_edge(edge_id).rate_constant = rate
        if self.target_id is not None and self._original_target_kinetics is not None:
            entity = network.registry.get(self.target_id)
            was_locked = entity.locked
            entity.locked = False
            entity.kinetics = self._original_target_kinetics
            entity.locked = was_locked
            entity.metadata.pop("drug_inhibition_factor", None)
            entity.metadata.pop("drug_concentration", None)
        self.applied = False

    def apply(self, state: SimulationState, t: float) -> None:
        network = state.network
        self._cache_originals(network)

        if self.t_end is not None and t > self.t_end + 1e-15:
            if self.applied:
                self._restore(network)
            return

        if not self.is_active(t):
            return

        drug = self.drug_level(t)
        substrate = 0.0
        if self.substrate_id is not None:
            substrate = state.entity(self.substrate_id).concentration
        factor = self.inhibition_factor(drug, substrate)

        for edge_id, base_rate in self._original_rates.items():
            network.get_edge(edge_id).rate_constant = base_rate * factor

        if self.target_id is not None and self._original_target_kinetics is not None:
            entity = state.entity(self.target_id)
            was_locked = entity.locked
            entity.locked = False
            base = self._original_target_kinetics
            km_scale = min(self.apparent_km_scale(drug, substrate), 1e6)
            # Scale catalytic ceiling / production; raise or lower Km safely
            entity.kinetics = base.with_updates(
                vmax=max(0.0, base.vmax * factor),
                production_rate=max(0.0, base.production_rate * factor),
                km=_clamp_km(base.km * km_scale),
            )
            entity.metadata["drug_inhibition_factor"] = factor
            entity.metadata["drug_concentration"] = drug
            entity.metadata["drug_km_scale"] = km_scale
            entity.locked = was_locked

            # Boolean layer: strong inhibition flips target OFF
            if factor < 0.1 and not (entity.locked and entity.metadata.get("lock_boolean")):
                entity.set_boolean(ActivityState.OFF)

        self.applied = True
        state.extras[f"drug:{self.name}"] = {
            "concentration": drug,
            "factor": factor,
            "km_scale": self.apparent_km_scale(drug, substrate),
        }


@dataclass
class RateOverride(Perturbation):
    """Direct rewrite of an edge rate_constant during a time window."""

    edge_id: str
    rate_constant: float
    name: str = ""
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _original: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"rate_override:{self.edge_id}"
        if self.rate_constant < 0.0:
            raise ValueError("rate_constant must be non-negative")

    def apply(self, state: SimulationState, t: float) -> None:
        edge: InteractionEdge = state.network.get_edge(self.edge_id)
        if self._original is None:
            self._original = edge.rate_constant
        if self.t_end is not None and t > self.t_end + 1e-15:
            if self.applied and self._original is not None:
                edge.rate_constant = self._original
                self.applied = False
            return
        if self.is_active(t):
            edge.rate_constant = self.rate_constant
            self.applied = True


class PerturbationManager:
    """
    Ordered collection of perturbations compiled into a single hook chain.

    Usage::

        mgr = PerturbationManager()
        mgr.add(Mutation("EGFR", MutationKind.KNOCKOUT, t_start=10.0))
        mgr.add(DrugPerturbation(target_id="MEK", ki=0.2, concentration=5.0, t_start=20.0))
        engine.run_ode(config, perturbation_hooks=mgr.hooks())
    """

    def __init__(self) -> None:
        self._items: List[Perturbation] = []

    def __len__(self) -> int:
        return len(self._items)

    def add(self, perturbation: Perturbation) -> "PerturbationManager":
        self._items.append(perturbation)
        return self

    def extend(self, perturbations: Sequence[Perturbation]) -> "PerturbationManager":
        for p in perturbations:
            self.add(p)
        return self

    def clear(self) -> None:
        self._items.clear()

    def items(self) -> List[Perturbation]:
        return list(self._items)

    def hooks(self) -> List[PerturbationHook]:
        return [p.as_hook() for p in self._items]

    def combined_hook(self) -> PerturbationHook:
        """Single hook that applies all perturbations in registration order."""
        children = self.hooks()

        def hook(state: SimulationState, t: float) -> None:
            for child in children:
                child(state, t)

        return hook

    def knockout(self, target_id: str, t_start: float = 0.0, **kwargs: Any) -> Mutation:
        mut = Mutation(target_id=target_id, kind=MutationKind.KNOCKOUT, t_start=t_start, **kwargs)
        self.add(mut)
        return mut

    def activate(
        self,
        target_id: str,
        expression_level: float = 1.0,
        t_start: float = 0.0,
        **kwargs: Any,
    ) -> Mutation:
        mut = Mutation(
            target_id=target_id,
            kind=MutationKind.CONSTITUTIVE_ACTIVATION,
            expression_level=expression_level,
            t_start=t_start,
            **kwargs,
        )
        self.add(mut)
        return mut

    def dose(
        self,
        target_id: str,
        concentration: float,
        ki: float,
        model: InhibitionModel = InhibitionModel.COMPETITIVE,
        t_start: float = 0.0,
        t_end: Optional[float] = None,
        **kwargs: Any,
    ) -> DrugPerturbation:
        drug = DrugPerturbation(
            target_id=target_id,
            concentration=concentration,
            ki=ki,
            model=model,
            t_start=t_start,
            t_end=t_end,
            **kwargs,
        )
        self.add(drug)
        return drug

    def summary(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in self._items:
            rows.append(
                {
                    "name": item.name,
                    "class": type(item).__name__,
                    "t_start": item.t_start,
                    "t_end": item.t_end,
                    "applied": item.applied,
                }
            )
        return rows


def clamp01(x: float) -> float:
    """Utility for dose-response curves."""
    if math.isnan(x) or math.isinf(x):
        raise ValueError("value must be finite")
    return max(0.0, min(1.0, x))


def _clamp_km(km: float) -> float:
    """Keep Michaelis constants finite and strictly positive for the ODE solver."""
    if not math.isfinite(km) or km <= 0.0:
        return 1e-12
    return min(km, 1e6)
