"""
Dual-paradigm simulation engine for VOIDSIGNAL.

Two interchangeable runtimes operate on the same :class:`SignalingNetwork`:

1. **Boolean Dynamics** — synchronous (or block-sequential) logic-gate updates
   on discrete activity states. Captures qualitative attractors, cycles, and
   logical necessity/sufficiency of regulators.

2. **Deterministic ODEs (mass-action / Hill kinetics)** — continuous
   concentrations integrated with classical RK4 or an embedded Heun
   (improved Euler) adaptive stepper. Captures transient amplitudes and
   dose-response without requiring SciPy at install time.

Perturbations are applied through an injected callback at configurable times
so mutations and drugs can appear mid-trajectory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)
import math
import time

from voidsignal.components import (
    ActivityState,
    BiologicalEntity,
    Complex,
    EntityType,
    Gene,
    RNA,
    Receptor,
)
from voidsignal.topology import (
    InteractionEdge,
    InteractionType,
    LogicGate,
    SignalingNetwork,
)

# Lazily typed to avoid circular imports at module load for type checkers
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from voidsignal.compartments import SpatialCompartmentModel
    from voidsignal.dogma import CentralDogmaEngine
    from voidsignal.plugins import PluginRegistry


class SimulatorBackend(Enum):
    BOOLEAN = auto()
    ODE = auto()


class ODEStepper(Enum):
    """Available deterministic integrators."""

    RK4 = "rk4"
    HEUN_ADAPTIVE = "heun_adaptive"


PerturbationHook = Callable[["SimulationState", float], None]
"""Signature: ``hook(state, t)`` invoked before each step at time *t*."""


@dataclass
class SimulationConfig:
    """
    Shared runtime configuration.

    Attributes
    ----------
    t_start / t_end :
        Integration / Boolean schedule window.
    dt :
        Fixed step for RK4 and Boolean wall-time mapping.
    boolean_steps :
        Number of synchronous Boolean updates when running the logic engine.
        If None, derived as ``int((t_end - t_start) / dt)``.
    sync_threshold :
        Concentration→Boolean mapping threshold for hybrid readouts.
    record_every :
        Store one trajectory sample every N steps (≥ 1).
    clamp_nonnegative :
        Force ODE concentrations through ``max(0, ·)`` after each stage.
    relative_tolerance / absolute_tolerance :
        Error control for the adaptive Heun stepper.
    """

    t_start: float = 0.0
    t_end: float = 100.0
    dt: float = 0.1
    boolean_steps: Optional[int] = None
    sync_threshold: float = 0.5
    record_every: int = 1
    clamp_nonnegative: bool = True
    relative_tolerance: float = 1e-4
    absolute_tolerance: float = 1e-7
    min_dt: float = 1e-6
    max_dt: float = 1.0
    stepper: ODEStepper = ODEStepper.RK4

    def __post_init__(self) -> None:
        if self.t_end < self.t_start:
            raise ValueError("t_end must be ≥ t_start")
        if self.dt <= 0.0:
            raise ValueError("dt must be positive")
        if self.record_every < 1:
            raise ValueError("record_every must be ≥ 1")
        if self.sync_threshold < 0.0:
            raise ValueError("sync_threshold must be non-negative")
        if self.boolean_steps is not None and self.boolean_steps < 0:
            raise ValueError("boolean_steps must be non-negative")
        if self.min_dt <= 0.0 or self.max_dt < self.min_dt:
            raise ValueError("require 0 < min_dt ≤ max_dt")

    @property
    def n_boolean_steps(self) -> int:
        if self.boolean_steps is not None:
            return self.boolean_steps
        return max(1, int(round((self.t_end - self.t_start) / self.dt)))


@dataclass
class SimulationState:
    """Live mutable view exposed to perturbation hooks."""

    network: SignalingNetwork
    time: float
    step_index: int
    backend: SimulatorBackend
    extras: Dict[str, Any] = field(default_factory=dict)

    def entity(self, entity_id: str) -> BiologicalEntity:
        return self.network.registry.get(entity_id)

    def concentrations(self) -> Dict[str, float]:
        return self.network.registry.concentrations()

    def boolean_map(self) -> Dict[str, ActivityState]:
        return self.network.registry.boolean_states()


@dataclass
class TrajectoryResult:
    """
    Time-indexed recording of a completed run.

    ``concentrations[t_idx][entity_id]`` and ``boolean_states[t_idx][entity_id]``
    share the same ``times`` axis.
    """

    times: List[float]
    concentrations: List[Dict[str, float]]
    boolean_states: List[Dict[str, int]]
    backend: SimulatorBackend
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.times)

    def final_concentrations(self) -> Dict[str, float]:
        if not self.concentrations:
            return {}
        return dict(self.concentrations[-1])

    def final_boolean(self) -> Dict[str, int]:
        if not self.boolean_states:
            return {}
        return dict(self.boolean_states[-1])

    def series(self, entity_id: str) -> List[float]:
        """Extract the continuous trajectory of one entity."""
        return [sample[entity_id] for sample in self.concentrations if entity_id in sample]

    def boolean_series(self, entity_id: str) -> List[int]:
        return [sample[entity_id] for sample in self.boolean_states if entity_id in sample]

    def to_columnar(self) -> Dict[str, Any]:
        """
        Column-oriented export for pandas / plotting adapters::

            {"time": [...], "ERK": [...], "RAF": [...], ...}
        """
        columns: Dict[str, Any] = {"time": list(self.times)}
        if not self.concentrations:
            return columns
        keys = sorted(self.concentrations[0].keys())
        for key in keys:
            columns[key] = [row.get(key, float("nan")) for row in self.concentrations]
        return columns


class Simulator(Protocol):
    """Structural protocol shared by Boolean and ODE engines."""

    def run(
        self,
        config: SimulationConfig,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> TrajectoryResult:
        ...


# ---------------------------------------------------------------------------
# Boolean engine
# ---------------------------------------------------------------------------


class BooleanSimulator:
    """
    Synchronous Boolean network dynamics with typed interaction semantics.

    Update rule for node *v* with configured :class:`~voidsignal.topology.NodeLogic`:

    * Collect active incoming edges with ``weight ≥ threshold``.
    * Partition into activators vs inhibitors via ``logic_role`` /
      ``InteractionType.is_inhibitory``.
    * Combine with AND / OR / MAJORITY / NOT / COPY.
    * Optional inhibitor veto: any ON inhibitor forces OFF.

    Delayed edges (``edge.delay > 0``) read historical Boolean states from a
    rolling buffer so negative/positive feedback with explicit lag is expressible.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        dogma: Optional["CentralDogmaEngine"] = None,
    ) -> None:
        issues = network.validate()
        if issues:
            raise ValueError("Network validation failed:\n  - " + "\n  - ".join(issues))
        self.network = network
        self.dogma = dogma
        self._history: List[Dict[str, ActivityState]] = []
        self._boolean_dt: float = 1.0

    def attach_dogma(self, dogma: "CentralDogmaEngine") -> None:
        self.dogma = dogma
        if not dogma.chains:
            dogma.discover_chains()

    def _source_state(self, edge: InteractionEdge, current: Mapping[str, ActivityState]) -> ActivityState:
        if edge.delay <= 0 or len(self._history) <= edge.delay:
            return current[edge.source_id]
        # history[-1] is previous step; delay=1 → immediately previous
        return self._history[-(edge.delay)][edge.source_id]

    def _evaluate_node(
        self,
        node_id: str,
        current: Mapping[str, ActivityState],
    ) -> ActivityState:
        entity = self.network.registry.get(node_id)
        if entity.locked and entity.metadata.get("lock_boolean", False):
            return entity.boolean_state

        logic = self.network.get_node_logic(node_id)
        edges = [e for e in self.network.in_edges(node_id) if e.active and e.weight >= logic.threshold]

        if not edges:
            # Basal: keep state, or use basal_activity as weakly ON
            if entity.kinetics.basal_activity >= 0.5:
                return ActivityState.ON
            return entity.boolean_state

        activators_on: List[bool] = []
        inhibitors_on: List[bool] = []
        for edge in edges:
            src_on = self._source_state(edge, current) is ActivityState.ON
            if edge.logic_role == "inhibitor" or edge.interaction_type.is_inhibitory:
                inhibitors_on.append(src_on)
            else:
                activators_on.append(src_on)

        if logic.gate is LogicGate.NOT:
            if len(edges) != 1:
                raise ValueError(f"NOT gate on {node_id!r} requires exactly one input")
            return ActivityState.OFF if self._source_state(edges[0], current) is ActivityState.ON else ActivityState.ON

        if logic.gate is LogicGate.COPY:
            if len(edges) != 1:
                raise ValueError(f"COPY gate on {node_id!r} requires exactly one input")
            return self._source_state(edges[0], current)

        if logic.inhibitor_veto and any(inhibitors_on):
            return ActivityState.OFF

        if logic.gate is LogicGate.AND:
            if not activators_on:
                return ActivityState.OFF
            return ActivityState.ON if all(activators_on) else ActivityState.OFF

        if logic.gate is LogicGate.OR:
            if any(activators_on):
                return ActivityState.ON
            # Pure inhibition without activators: OFF if any inhibitor, else basal
            if inhibitors_on and not logic.inhibitor_veto:
                return ActivityState.OFF if any(inhibitors_on) else ActivityState.ON
            return ActivityState.ON if entity.kinetics.basal_activity >= 0.5 else ActivityState.OFF

        if logic.gate is LogicGate.MAJORITY:
            a = sum(1 for x in activators_on if x)
            i = sum(1 for x in inhibitors_on if x)
            if a > i:
                return ActivityState.ON
            if a < i:
                return ActivityState.OFF
            return entity.boolean_state

        raise ValueError(f"Unsupported logic gate {logic.gate!r} on {node_id!r}")

    def step(self) -> Dict[str, ActivityState]:
        """Perform one synchronous update; returns the new state map."""
        current = self.network.registry.boolean_states()
        nxt: Dict[str, ActivityState] = {}
        for node_id in self.network.nodes():
            nxt[node_id] = self._evaluate_node(node_id, current)
        for node_id, state in nxt.items():
            entity = self.network.registry.get(node_id)
            if entity.locked and entity.metadata.get("lock_boolean", False):
                continue
            entity.boolean_state = state
            entity.sync_concentration_from_boolean(
                on_level=max(entity.concentration, 1.0),
                off_level=0.0,
            )
        if self.dogma is not None:
            self.dogma.boolean_step(self._boolean_dt)
        self._history.append(dict(current))
        max_delay = 0
        for edge in self.network.edges():
            if edge.delay > max_delay:
                max_delay = edge.delay
        keep = max(max_delay + 2, 2)
        if len(self._history) > keep:
            self._history = self._history[-keep:]
        return nxt

    def run(
        self,
        config: SimulationConfig,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> TrajectoryResult:
        hooks = list(perturbation_hooks or [])
        times: List[float] = []
        concentrations: List[Dict[str, float]] = []
        boolean_states: List[Dict[str, int]] = []
        n_steps = config.n_boolean_steps
        t = config.t_start
        self._boolean_dt = config.dt
        wall0 = time.perf_counter()

        def record(step_i: int) -> None:
            if step_i % config.record_every != 0:
                return
            times.append(t)
            concentrations.append(self.network.registry.concentrations())
            boolean_states.append(
                {eid: st.value for eid, st in self.network.registry.boolean_states().items()}
            )

        record(0)
        for step_i in range(1, n_steps + 1):
            state = SimulationState(
                network=self.network,
                time=t,
                step_index=step_i,
                backend=SimulatorBackend.BOOLEAN,
            )
            for hook in hooks:
                hook(state, t)
            self.step()
            t = config.t_start + step_i * config.dt
            record(step_i)

        return TrajectoryResult(
            times=times,
            concentrations=concentrations,
            boolean_states=boolean_states,
            backend=SimulatorBackend.BOOLEAN,
            metadata={
                "n_steps": n_steps,
                "wall_time_s": time.perf_counter() - wall0,
                "n_nodes": len(self.network),
            },
        )

    def find_attractor(self, max_steps: int = 256) -> Dict[str, Any]:
        """
        Iterate until a previously seen Boolean global state reappears.

        Returns the attractor cycle (list of state dicts) and transient length.
        """
        if max_steps < 1:
            raise ValueError("max_steps must be ≥ 1")
        seen: Dict[Tuple[Tuple[str, int], ...], int] = {}
        trajectory: List[Dict[str, int]] = []
        for i in range(max_steps + 1):
            freeze = tuple(
                sorted((eid, st.value) for eid, st in self.network.registry.boolean_states().items())
            )
            as_dict = {eid: val for eid, val in freeze}
            if freeze in seen:
                start = seen[freeze]
                return {
                    "transient_length": start,
                    "period": i - start,
                    "cycle": trajectory[start:],
                    "converged": True,
                }
            seen[freeze] = i
            trajectory.append(as_dict)
            if i < max_steps:
                self.step()
        return {
            "transient_length": max_steps,
            "period": None,
            "cycle": [],
            "converged": False,
        }


# ---------------------------------------------------------------------------
# ODE engine
# ---------------------------------------------------------------------------


_CONC_FLOOR = 1e-12
_STOICH_ROLES = frozenset({"substrate_to_product", "catalysis", "consumption"})


@dataclass
class CompiledStoichReaction:
    """
    Mass-action reaction compiled from Phase-2 edge metadata:

        ν_S · S (+ enzyme)  ──k→  ν_P · P

    Rate law (irreversible forward)::

        v = k · w · ∏_i max([S_i], ε)^{ν_i} · f_enz

    where ``f_enz = 1 + Σ [E]`` when catalysts are present (linear enzyme
    drive; reduces to 1 when none). Net ODEs::

        d[S_i]/dt  -= ν_i · v
        d[P_j]/dt  += ν_j · v
    """

    reaction_id: str
    substrates: Dict[str, float]
    products: Dict[str, float]
    catalysts: List[str]
    rate_constant: float
    weight: float = 1.0
    reversible: bool = False
    reverse_rate: float = 0.0


def _safe_power(concentration: float, exponent: float, floor: float = _CONC_FLOOR) -> float:
    """
    Stable ``max(c, ε)^ν`` avoiding 0^negative and overflow on large ν.
    """
    base = concentration if concentration > floor else floor
    if exponent == 1.0:
        return base if concentration > floor else max(concentration, 0.0)
    if exponent == 0.0:
        return 1.0
    # Integer exponents on non-negative bases are exact and safer
    if abs(exponent - round(exponent)) < 1e-12 and exponent >= 0:
        return base ** int(round(exponent))
    try:
        return math.pow(base, float(exponent))
    except (OverflowError, ValueError):
        return 0.0


def _coeff(meta: Mapping[str, Any], *keys: str, default: float = 1.0) -> float:
    for key in keys:
        if key in meta and meta[key] is not None:
            try:
                value = float(meta[key])
            except (TypeError, ValueError):
                continue
            if value > 0.0 and math.isfinite(value):
                return value
    return default


class MassActionRHS:
    """
    Right-hand side builder for deterministic signalling + stoichiometric ODEs.

    Dual evaluation paths
    ---------------------
    1. **Compiled stoichiometric reactions** (Phase-2 metadata): edges that share
       a ``reaction_id`` and carry ``role`` /
       ``stoichiometry_source|target`` contribute a single mass-action flux

           v = k · ∏ [S]^{ν_S}

       applied with true stoichiometric scaling to every substrate / product.

    2. **Legacy pairwise regulatory edges** (no reaction_id / role): Hill /
       activation / inhibition channels with default coefficients ν = 1.0.

    Numerical safeguards: non-negative concentrations, ε-floor on power laws,
    finite rate clamping, locked species held at zero derivative.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        dogma: Optional["CentralDogmaEngine"] = None,
        spatial: Optional["SpatialCompartmentModel"] = None,
    ) -> None:
        self.network = network
        self.dogma = dogma
        self.spatial = spatial
        self._order: List[str] = []
        self._index: Dict[str, int] = {}
        self._reactions: List[CompiledStoichReaction] = []
        self._reaction_edge_ids: set[str] = set()
        self.rebuild()
        if dogma is not None and not dogma.chains:
            dogma.discover_chains()
        if spatial is not None:
            spatial.validate_routing(autofix_slowdown=True)

    def attach_dogma(self, dogma: "CentralDogmaEngine") -> None:
        self.dogma = dogma
        dogma.discover_chains()

    def attach_spatial(self, spatial: "SpatialCompartmentModel") -> None:
        self.spatial = spatial
        spatial.validate_routing(autofix_slowdown=True)

    def rebuild(self) -> None:
        # Exclude pure compartment marker nodes from the ODE state vector
        self._order = [
            nid
            for nid in self.network.nodes()
            if self.network.registry.get(nid).entity_type is not EntityType.COMPARTMENT
        ]
        self._index = {nid: i for i, nid in enumerate(self._order)}
        self._reactions, self._reaction_edge_ids = self._compile_stoichiometric_reactions()

    @property
    def species(self) -> List[str]:
        return list(self._order)

    @property
    def compiled_reactions(self) -> List[CompiledStoichReaction]:
        return list(self._reactions)

    def pack(self) -> List[float]:
        return [self.network.registry.get(nid).concentration for nid in self._order]

    def unpack(self, y: Sequence[float], clamp: bool = True) -> None:
        if len(y) != len(self._order):
            raise ValueError(f"State vector length {len(y)} ≠ n_species {len(self._order)}")
        for nid, value in zip(self._order, y):
            entity = self.network.registry.get(nid)
            if entity.locked:
                continue
            conc = max(0.0, float(value)) if clamp else float(value)
            entity.concentration = conc

    def _compile_stoichiometric_reactions(
        self,
    ) -> Tuple[List[CompiledStoichReaction], set[str]]:
        """
        Aggregate Phase-2 edges into mass-action reactions keyed by ``reaction_id``.
        """
        buckets: Dict[str, Dict[str, Any]] = {}
        used_edges: set[str] = set()

        for edge in self.network.active_edges():
            meta = edge.metadata or {}
            role = str(meta.get("role") or "")
            reaction_id = meta.get("reaction_id") or meta.get("reaction")
            if not reaction_id:
                # Pairwise stoich defaults — synthesise a local reaction id
                if role in _STOICH_ROLES or (
                    "stoichiometry_source" in meta or "stoichiometry_target" in meta
                ):
                    reaction_id = f"pair:{edge.edge_id}"
                else:
                    continue
            reaction_id = str(reaction_id)
            bucket = buckets.setdefault(
                reaction_id,
                {
                    "substrates": {},
                    "products": {},
                    "catalysts": [],
                    "rate_constant": 0.0,
                    "weight": 0.0,
                    "reversible": bool(meta.get("reversible") or meta.get("reverse")),
                    "reverse_rate": 0.0,
                    "edge_ids": [],
                },
            )
            nu_s = _coeff(meta, "stoichiometry_source", default=1.0)
            nu_t = _coeff(meta, "stoichiometry_target", default=1.0)
            used_edges.add(edge.edge_id)
            bucket["edge_ids"].append(edge.edge_id)

            if role == "substrate_to_product" or (
                role not in _STOICH_ROLES
                and edge.interaction_type is InteractionType.CATALYSIS
            ):
                if meta.get("reverse"):
                    # Reverse flux channel: product → substrate
                    bucket["substrates"][edge.target_id] = max(
                        bucket["substrates"].get(edge.target_id, 0.0), nu_t
                    )
                    bucket["products"][edge.source_id] = max(
                        bucket["products"].get(edge.source_id, 0.0), nu_s
                    )
                    bucket["reverse_rate"] = max(bucket["reverse_rate"], edge.rate_constant)
                    bucket["reversible"] = True
                else:
                    bucket["substrates"][edge.source_id] = max(
                        bucket["substrates"].get(edge.source_id, 0.0), nu_s
                    )
                    bucket["products"][edge.target_id] = max(
                        bucket["products"].get(edge.target_id, 0.0), nu_t
                    )
                    bucket["rate_constant"] = max(bucket["rate_constant"], edge.rate_constant)
                    bucket["weight"] = max(bucket["weight"], edge.weight)
            elif role == "catalysis" or meta.get("enzyme_action") == "produce":
                if edge.source_id not in bucket["catalysts"]:
                    bucket["catalysts"].append(edge.source_id)
                bucket["products"][edge.target_id] = max(
                    bucket["products"].get(edge.target_id, 0.0), nu_t
                )
                bucket["rate_constant"] = max(bucket["rate_constant"], edge.rate_constant)
                bucket["weight"] = max(bucket["weight"], edge.weight)
            elif role == "consumption" or meta.get("enzyme_action") == "engage_substrate":
                if edge.source_id not in bucket["catalysts"]:
                    bucket["catalysts"].append(edge.source_id)
                bucket["substrates"][edge.target_id] = max(
                    bucket["substrates"].get(edge.target_id, 0.0), nu_t
                )
                bucket["rate_constant"] = max(bucket["rate_constant"], edge.rate_constant * 0.5)
            else:
                # Annotated stoich without explicit role — treat as S→P
                bucket["substrates"][edge.source_id] = max(
                    bucket["substrates"].get(edge.source_id, 0.0), nu_s
                )
                bucket["products"][edge.target_id] = max(
                    bucket["products"].get(edge.target_id, 0.0), nu_t
                )
                bucket["rate_constant"] = max(bucket["rate_constant"], edge.rate_constant)
                bucket["weight"] = max(bucket["weight"], edge.weight)

        compiled: List[CompiledStoichReaction] = []
        for rid, bucket in buckets.items():
            if not bucket["substrates"] and not bucket["products"]:
                continue
            k = float(bucket["rate_constant"]) if bucket["rate_constant"] > 0 else 1.0
            w = float(bucket["weight"]) if bucket["weight"] > 0 else 1.0
            compiled.append(
                CompiledStoichReaction(
                    reaction_id=rid,
                    substrates={k_: float(v) for k_, v in bucket["substrates"].items()},
                    products={k_: float(v) for k_, v in bucket["products"].items()},
                    catalysts=list(bucket["catalysts"]),
                    rate_constant=k,
                    weight=w,
                    reversible=bool(bucket["reversible"]),
                    reverse_rate=float(bucket["reverse_rate"]) if bucket["reverse_rate"] > 0 else 0.5 * k,
                )
            )
        return compiled, used_edges

    def _mass_action_flux(
        self,
        conc: Mapping[str, float],
        substrates: Mapping[str, float],
        catalysts: Sequence[str],
        rate_constant: float,
        weight: float,
    ) -> float:
        """
        v = k · w · ∏ [S_i]^{ν_i} · f_enz   with f_enz = 1 + Σ[E] (or 1).
        """
        flux = max(rate_constant, 0.0) * max(weight, 0.0)
        if flux == 0.0:
            return 0.0
        for species_id, nu in substrates.items():
            level = conc.get(species_id, 0.0)
            if level < 0.0:
                level = 0.0
            flux *= _safe_power(level, nu)
            if flux == 0.0:
                return 0.0
        if catalysts:
            enzyme_drive = 0.0
            vmax_acc = 0.0
            for enz_id in catalysts:
                enzyme_drive += max(conc.get(enz_id, 0.0), 0.0)
                enz = self.network.registry.get(enz_id)
                vmax_acc += max(enz.kinetics.vmax, 0.0)
            n = max(len(catalysts), 1)
            vmax_mean = vmax_acc / n
            # Linear enzyme factor × structural/kinetic k_cat (vmax)
            flux *= (1.0 + enzyme_drive) * max(vmax_mean, 0.0)
        if not math.isfinite(flux) or flux < 0.0:
            return 0.0
        return flux

    def _apply_stoichiometric_fluxes(
        self,
        conc: Mapping[str, float],
        dydt: Dict[str, float],
    ) -> None:
        for reaction in self._reactions:
            v_f = self._mass_action_flux(
                conc,
                reaction.substrates,
                reaction.catalysts,
                reaction.rate_constant,
                reaction.weight,
            )
            v_r = 0.0
            if reaction.reversible:
                v_r = self._mass_action_flux(
                    conc,
                    reaction.products,
                    reaction.catalysts,
                    reaction.reverse_rate,
                    reaction.weight,
                )
            net = v_f - v_r
            if net == 0.0:
                continue
            for sid, nu in reaction.substrates.items():
                if sid in dydt and not self.network.registry.get(sid).locked:
                    dydt[sid] -= nu * net
            for pid, nu in reaction.products.items():
                if pid in dydt and not self.network.registry.get(pid).locked:
                    dydt[pid] += nu * net


    def __call__(self, t: float, y: Sequence[float]) -> List[float]:
        """Evaluate dy/dt at time *t* for state vector *y*."""
        conc = {nid: max(0.0, float(val)) for nid, val in zip(self._order, y)}
        dydt = {nid: 0.0 for nid in self._order}

        # --- stoichiometric reaction channels (Phase-2 bridge) -------------
        self._apply_stoichiometric_fluxes(conc, dydt)

        # --- Phase-3 spatial diffusion ------------------------------------
        if self.spatial is not None:
            self.spatial.apply_transport_ode(conc, dydt)

        # --- Phase-3 central-dogma delayed expression ---------------------
        if self.dogma is not None:
            self.dogma.apply_ode_contributions(t, conc, dydt)

        for nid in self._order:
            entity = self.network.registry.get(nid)
            if entity.locked:
                dydt[nid] = 0.0
                continue

            dydt[nid] += entity.kinetics.production_rate
            dydt[nid] -= entity.kinetics.degradation_rate * conc[nid]

            if isinstance(entity, RNA) and entity.source_gene_id:
                if self.dogma is None or not self.dogma.skips_direct_expression(nid):
                    gene_id = entity.source_gene_id
                    if gene_id in self.network:
                        gene = self.network.registry.get(gene_id)
                        if isinstance(gene, Gene):
                            gate = 1.0 if gene.is_active else gene.kinetics.basal_activity
                            gene_level = conc.get(gene_id, gene.concentration)
                            dydt[nid] += (
                                gene.transcription_rate
                                * gene.promoter_strength
                                * gate
                                * (gene_level / (gene_level + 0.5))
                            )

            if entity.entity_type is EntityType.PROTEIN:
                if self.dogma is None or not self.dogma.skips_direct_expression(nid):
                    rna_id = getattr(entity, "source_rna_id", None)
                    if rna_id and rna_id in conc:
                        rna = self.network.registry.get(rna_id)
                        if isinstance(rna, RNA) and rna.is_coding:
                            dydt[nid] += rna.translation_rate * conc[rna_id]

            for edge in self.network.in_edges(nid):
                if not edge.active or edge.source_id not in conc:
                    continue
                if edge.edge_id in self._reaction_edge_ids:
                    continue
                if edge.metadata.get("spatial_class") == "diffusion":
                    continue
                src = conc[edge.source_id]
                nu_src = _coeff(edge.metadata, "stoichiometry_source", default=1.0)
                nu_tgt = _coeff(edge.metadata, "stoichiometry_target", default=1.0)
                src_term = _safe_power(src, nu_src)
                src_entity = self.network.registry.get(edge.source_id)
                kcat = max(src_entity.kinetics.vmax, 0.0)

                if edge.interaction_type is InteractionType.TRANSCRIPTION:
                    dydt[nid] += edge.rate_constant * edge.hill_activation(src) * nu_tgt
                elif edge.interaction_type is InteractionType.TRANSLATION:
                    dydt[nid] += edge.rate_constant * src_term * nu_tgt
                elif edge.interaction_type is InteractionType.DEGRADATION:
                    dydt[nid] -= edge.rate_constant * src_term * conc[nid] * nu_tgt
                elif edge.interaction_type is InteractionType.BINDING:
                    affinity = max(src_entity.kinetics.binding_affinity, 0.0)
                    dydt[nid] -= edge.rate_constant * affinity * src_term * conc[nid] * nu_tgt
                elif edge.interaction_type is InteractionType.TRANSLOCATION:
                    continue
                elif edge.interaction_type is InteractionType.CATALYSIS:
                    flux = edge.rate_constant * edge.weight * src_term * max(kcat, 0.0)
                    km = max(src_entity.kinetics.km, 1e-9)
                    sat = conc[nid] / (conc[nid] + km)
                    dydt[nid] += nu_tgt * flux * (0.5 + 0.5 * sat)
                elif edge.interaction_type.is_inhibitory:
                    dydt[nid] -= edge.rate_constant * edge.hill_activation(src) * nu_tgt
                    dydt[nid] -= (
                        0.1
                        * edge.rate_constant
                        * (1.0 - edge.hill_inhibition(src))
                        * conc[nid]
                        * nu_tgt
                    )
                else:
                    dydt[nid] += (
                        edge.rate_constant
                        * edge.hill_activation(src)
                        * nu_tgt
                        * max(kcat, 1e-12)
                    )

            if isinstance(entity, Complex):
                missing = [m for m in entity.members if m not in conc]
                if not missing:
                    prod = entity.association_rate
                    for member_id, stoich in entity.members.items():
                        prod *= _safe_power(conc[member_id], stoich)
                    diss = entity.dissociation_rate * conc[nid]
                    net = prod - diss
                    dydt[nid] += net
                    for member_id, stoich in entity.members.items():
                        if member_id in dydt and not self.network.registry.get(member_id).locked:
                            dydt[member_id] -= stoich * net

            if isinstance(entity, Receptor) and entity.internalisation_rate > 0.0:
                dydt[nid] -= entity.internalisation_rate * entity.bound_fraction * conc[nid]

            if not math.isfinite(dydt[nid]):
                dydt[nid] = 0.0

        return [dydt[nid] for nid in self._order]


def _vec_add(a: Sequence[float], b: Sequence[float]) -> List[float]:
    return [x + y for x, y in zip(a, b)]


def _vec_axpy(a: Sequence[float], s: float, b: Sequence[float]) -> List[float]:
    """a + s*b"""
    return [x + s * y for x, y in zip(a, b)]


def _rk4_step(f: Callable[[float, Sequence[float]], List[float]], t: float, y: Sequence[float], dt: float) -> List[float]:
    """
    Classical fourth-order Runge–Kutta step.

        k1 = f(t, y)
        k2 = f(t + dt/2, y + dt/2 · k1)
        k3 = f(t + dt/2, y + dt/2 · k2)
        k4 = f(t + dt,   y + dt · k3)
        y' = y + dt/6 · (k1 + 2 k2 + 2 k3 + k4)
    """
    k1 = f(t, y)
    k2 = f(t + 0.5 * dt, _vec_axpy(y, 0.5 * dt, k1))
    k3 = f(t + 0.5 * dt, _vec_axpy(y, 0.5 * dt, k2))
    k4 = f(t + dt, _vec_axpy(y, dt, k3))
    increment = [
        (dt / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i])
        for i in range(len(y))
    ]
    return _vec_add(y, increment)


def _heun_adaptive_step(
    f: Callable[[float, Sequence[float]], List[float]],
    t: float,
    y: Sequence[float],
    dt: float,
    rtol: float,
    atol: float,
) -> Tuple[List[float], float, float]:
    """
    Embedded Heun (order 2) vs Euler (order 1) error estimate.

    Returns ``(y_accepted_or_same, suggested_dt, error_norm)``.
    Caller rejects the step when error_norm > 1.
    """
    k1 = f(t, y)
    y_euler = _vec_axpy(y, dt, k1)
    k2 = f(t + dt, y_euler)
    y_heun = [
        y[i] + 0.5 * dt * (k1[i] + k2[i])
        for i in range(len(y))
    ]
    # Mixed relative/absolute error norm
    err_sq = 0.0
    for i in range(len(y)):
        scale = atol + rtol * max(abs(y[i]), abs(y_heun[i]))
        diff = y_heun[i] - y_euler[i]
        err_sq += (diff / scale) ** 2
    err = math.sqrt(err_sq / max(len(y), 1))
    # PI-lite step size controller
    if err == 0.0:
        new_dt = dt * 2.0
    else:
        new_dt = dt * max(0.2, min(5.0, 0.9 * (1.0 / err) ** 0.5))
    return y_heun, new_dt, err


class ODESimulator:
    """Deterministic continuous-time simulator using mass-action / Hill RHS."""

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        dogma: Optional["CentralDogmaEngine"] = None,
        spatial: Optional["SpatialCompartmentModel"] = None,
    ) -> None:
        issues = network.validate()
        if issues:
            raise ValueError("Network validation failed:\n  - " + "\n  - ".join(issues))
        self.network = network
        self.rhs = MassActionRHS(network, dogma=dogma, spatial=spatial)

    def attach_dogma(self, dogma: "CentralDogmaEngine") -> None:
        self.rhs.attach_dogma(dogma)

    def attach_spatial(self, spatial: "SpatialCompartmentModel") -> None:
        self.rhs.attach_spatial(spatial)

    def run(
        self,
        config: SimulationConfig,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> TrajectoryResult:
        hooks = list(perturbation_hooks or [])
        self.rhs.rebuild()
        if self.rhs.dogma is not None:
            self.rhs.dogma.reset()
        times: List[float] = []
        concentrations: List[Dict[str, float]] = []
        boolean_states: List[Dict[str, int]] = []
        t = config.t_start
        dt = config.dt
        step_index = 0
        wall0 = time.perf_counter()
        y = self.rhs.pack()

        def sync_and_record() -> None:
            self.rhs.unpack(y, clamp=config.clamp_nonnegative)
            for entity in self.network.registry.entities():
                if entity.entity_type is EntityType.COMPARTMENT:
                    continue
                entity.sync_boolean_from_concentration(config.sync_threshold)
            times.append(t)
            concentrations.append(self.network.registry.concentrations())
            boolean_states.append(
                {eid: st.value for eid, st in self.network.registry.boolean_states().items()}
            )

        sync_and_record()

        while t < config.t_end - 1e-15:
            state = SimulationState(
                network=self.network,
                time=t,
                step_index=step_index,
                backend=SimulatorBackend.ODE,
                extras={"dt": dt},
            )
            for hook in hooks:
                hook(state, t)
            # Hooks may alter concentrations — refresh y
            y = self.rhs.pack()
            remaining = config.t_end - t
            local_dt = min(dt, remaining)

            if config.stepper is ODEStepper.RK4:
                y = _rk4_step(self.rhs, t, y, local_dt)
                if config.clamp_nonnegative:
                    y = [max(0.0, v) for v in y]
                t += local_dt
                step_index += 1
                if step_index % config.record_every == 0:
                    sync_and_record()
            elif config.stepper is ODEStepper.HEUN_ADAPTIVE:
                y_candidate, suggested_dt, err = _heun_adaptive_step(
                    self.rhs,
                    t,
                    y,
                    local_dt,
                    config.relative_tolerance,
                    config.absolute_tolerance,
                )
                if err <= 1.0 or local_dt <= config.min_dt * (1.0 + 1e-12):
                    y = y_candidate
                    if config.clamp_nonnegative:
                        y = [max(0.0, v) for v in y]
                    t += local_dt
                    step_index += 1
                    dt = min(config.max_dt, max(config.min_dt, suggested_dt))
                    if step_index % config.record_every == 0:
                        sync_and_record()
                else:
                    dt = min(config.max_dt, max(config.min_dt, suggested_dt))
            else:
                raise ValueError(f"Unknown stepper {config.stepper!r}")

        # Ensure final sample at t_end
        if not times or times[-1] < config.t_end - 1e-12:
            sync_and_record()

        return TrajectoryResult(
            times=times,
            concentrations=concentrations,
            boolean_states=boolean_states,
            backend=SimulatorBackend.ODE,
            metadata={
                "n_steps": step_index,
                "wall_time_s": time.perf_counter() - wall0,
                "n_species": len(self.rhs.species),
                "stepper": config.stepper.value,
            },
        )


class DualEngineSimulator:
    """
    Facade that owns a network and can dispatch to Boolean or ODE backends,
    optionally chaining Boolean attractor discovery → ODE refinement.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        dogma: Optional["CentralDogmaEngine"] = None,
        spatial: Optional["SpatialCompartmentModel"] = None,
        plugins: Optional["PluginRegistry"] = None,
    ) -> None:
        self.network = network
        self.boolean = BooleanSimulator(network, dogma=dogma)
        self.ode = ODESimulator(network, dogma=dogma, spatial=spatial)
        self._hooks: List[PerturbationHook] = []
        self.plugins: Optional["PluginRegistry"] = None
        if plugins is not None:
            self.attach_plugins(plugins)

    def attach_dogma(self, dogma: "CentralDogmaEngine") -> None:
        self.boolean.attach_dogma(dogma)
        self.ode.attach_dogma(dogma)

    def attach_spatial(self, spatial: "SpatialCompartmentModel") -> None:
        self.ode.attach_spatial(spatial)

    def attach_plugins(self, registry: "PluginRegistry") -> None:
        """Bind a Phase-6 plugin registry (step hooks + before/after run)."""
        self.plugins = registry
        for hook in registry.collect_step_hooks():
            self.add_hook(hook)

    def add_hook(self, hook: PerturbationHook) -> None:
        self._hooks.append(hook)

    def clear_hooks(self) -> None:
        self._hooks.clear()

    def run_boolean(
        self,
        config: Optional[SimulationConfig] = None,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> TrajectoryResult:
        cfg = config or SimulationConfig()
        if self.plugins is not None:
            self.plugins.before_run(self, cfg)
        hooks = list(self._hooks) + list(perturbation_hooks or [])
        traj = self.boolean.run(cfg, hooks)
        if self.plugins is not None:
            self.plugins.after_run(self, traj)
            scores = self.plugins.collect_scores(traj)
            if scores:
                traj.metadata["plugin_scores"] = scores
        return traj

    def run_ode(
        self,
        config: Optional[SimulationConfig] = None,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> TrajectoryResult:
        cfg = config or SimulationConfig()
        if self.plugins is not None:
            self.plugins.before_run(self, cfg)
        hooks = list(self._hooks) + list(perturbation_hooks or [])
        traj = self.ode.run(cfg, hooks)
        if self.plugins is not None:
            self.plugins.after_run(self, traj)
            scores = self.plugins.collect_scores(traj)
            if scores:
                traj.metadata["plugin_scores"] = scores
        return traj

    def run(
        self,
        backend: SimulatorBackend,
        config: Optional[SimulationConfig] = None,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> TrajectoryResult:
        if backend is SimulatorBackend.BOOLEAN:
            return self.run_boolean(config, perturbation_hooks)
        if backend is SimulatorBackend.ODE:
            return self.run_ode(config, perturbation_hooks)
        raise ValueError(f"Unsupported backend {backend!r}")

    def boolean_then_ode(
        self,
        boolean_config: SimulationConfig,
        ode_config: SimulationConfig,
        perturbation_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> Tuple[TrajectoryResult, TrajectoryResult]:
        """
        Hybrid workflow: relax Boolean logic to an attractor-ish state, lift
        concentrations from Boolean levels, then integrate ODEs from that IC.
        """
        hooks = list(self._hooks) + list(perturbation_hooks or [])
        bool_traj = self.boolean.run(boolean_config, hooks)
        for entity in self.network.registry.entities():
            if entity.entity_type is EntityType.COMPARTMENT:
                continue
            entity.sync_concentration_from_boolean(on_level=1.0, off_level=0.0)
        ode_traj = self.ode.run(ode_config, hooks)
        return bool_traj, ode_traj
