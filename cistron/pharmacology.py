"""
Advanced pharmacodynamics engine for CISTRON Phase 4.

Provides:

* Explicit competitive / non-competitive / uncompetitive / allosteric
  (inhibition & activation) transforms that rewrite kinetic parameters
  consumed by :class:`~cistron.simulation.MassActionRHS`.
* One-compartment pharmacokinetic clearance curves with multi-dose and
  washout windows ``[t_start, t_end]``.
* Analytical dose–response (IC₅₀ / EC₅₀) sweeps.
* Combination synergy scores via Bliss independence and Loewe additivity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import copy
import logging
import math

from cistron.components import KineticParameters
from cistron.perturbation import InhibitionModel, Perturbation, PerturbationManager, clamp01
from cistron.simulation import (
    DualEngineSimulator,
    PerturbationHook,
    SimulationConfig,
    SimulationState,
    TrajectoryResult,
)
from cistron.topology import SignalingNetwork

logger = logging.getLogger(__name__)

NetworkFactory = Callable[[], SignalingNetwork]


class Mechanism(Enum):
    """Pharmacodynamic interaction class."""

    COMPETITIVE = "competitive"
    NONCOMPETITIVE = "noncompetitive"
    UNCOMPETITIVE = "uncompetitive"
    ALLOSTERIC_INHIBITION = "allosteric_inhibition"
    ALLOSTERIC_ACTIVATION = "allosteric_activation"


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if abs(den) < 1e-15:
        return default
    return num / den


def _clamp_pos(x: float, eps: float = 1e-12) -> float:
    if not math.isfinite(x):
        return eps
    return max(eps, x)


# ---------------------------------------------------------------------------
# Pharmacokinetics
# ---------------------------------------------------------------------------


@dataclass
class PharmacokineticProfile:
    """
    One-compartment linear PK with instantaneous IV boluses (superposition).

        C(t) = Σ_i (F · Dose_i / V) · exp(−k_el · (t − t_i))    for t ≥ t_i

    Oral first-order absorption uses a two-exponential Bateman form when
    ``ka > 0`` and ``ka ≠ kel``.
    """

    dose: float = 1.0
    volume: float = 1.0
    kel: float = 0.15
    bioavailability: float = 1.0
    ka: float = 0.0
    dosing_times: List[float] = field(default_factory=lambda: [0.0])
    hard_washout: bool = False
    """If True, force C→0 after the drug's ``t_end`` rather than natural clearance."""

    def __post_init__(self) -> None:
        if self.dose < 0.0:
            raise ValueError("dose must be non-negative")
        if self.volume <= 0.0:
            raise ValueError("volume must be positive")
        if self.kel < 0.0:
            raise ValueError("kel must be non-negative")
        if self.ka < 0.0:
            raise ValueError("ka must be non-negative")
        if not 0.0 <= self.bioavailability <= 1.0:
            raise ValueError("bioavailability must be in [0, 1]")
        self.dosing_times = sorted(float(t) for t in self.dosing_times)

    @property
    def half_life(self) -> float:
        if self.kel <= 0.0:
            return float("inf")
        return math.log(2.0) / self.kel

    def cmax_iv(self) -> float:
        return self.bioavailability * self.dose / self.volume

    def concentration(self, t: float, *, active_until: Optional[float] = None) -> float:
        if self.hard_washout and active_until is not None and t > active_until + 1e-15:
            return 0.0
        total = 0.0
        amp = self.bioavailability * self.dose / self.volume
        for t_dose in self.dosing_times:
            if active_until is not None and t_dose > active_until + 1e-15:
                continue
            dt = t - t_dose
            if dt < -1e-15:
                continue
            if self.ka <= 0.0 or abs(self.ka - self.kel) < 1e-12:
                total += amp * math.exp(-self.kel * max(dt, 0.0))
            else:
                # Bateman: C = F·Dose·ka / (V·(ka−kel)) · (e^{−kel·t} − e^{−ka·t})
                coeff = amp * self.ka / (self.ka - self.kel)
                total += coeff * (math.exp(-self.kel * dt) - math.exp(-self.ka * dt))
        return max(0.0, total)

    def auc(self, t_end: float, n_steps: int = 500) -> float:
        if t_end <= 0.0:
            return 0.0
        dt = t_end / n_steps
        acc = 0.0
        for i in range(n_steps + 1):
            t = i * dt
            w = 0.5 if i in (0, n_steps) else 1.0
            acc += w * self.concentration(t)
        return acc * dt


# ---------------------------------------------------------------------------
# Effect equations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KineticEffect:
    """Multiplicative transforms applied to baseline kinetics."""

    vmax_scale: float = 1.0
    km_scale: float = 1.0
    binding_scale: float = 1.0
    production_scale: float = 1.0
    activity_factor: float = 1.0

    def apply(self, base: KineticParameters) -> KineticParameters:
        return base.with_updates(
            vmax=max(0.0, base.vmax * self.vmax_scale),
            km=_clamp_pos(base.km * self.km_scale),
            binding_affinity=max(0.0, base.binding_affinity * self.binding_scale),
            production_rate=max(0.0, base.production_rate * self.production_scale),
        )


def effect_from_mechanism(
    mechanism: Mechanism,
    drug_conc: float,
    *,
    ki: float,
    km: float = 1.0,
    substrate_conc: float = 0.0,
    hill: float = 1.0,
    efficacy: float = 1.0,
    ka_allo: Optional[float] = None,
) -> KineticEffect:
    """
    Map free drug concentration onto kinetic scales.

    Affinity / velocity floors prevent zero-division during MassActionRHS
    power-law evaluation.
    """
    if drug_conc <= 0.0 or ki <= 0.0:
        return KineticEffect()
    n = max(hill, 1e-6)
    i_over_ki = drug_conc / ki

    if mechanism is Mechanism.COMPETITIVE:
        # Classic: Km↑, Vmax unchanged; activity factor for edge rates
        km_scale = 1.0 + i_over_ki
        factor = 1.0 / (1.0 + drug_conc / (ki * (1.0 + max(substrate_conc, 0.0) / max(km, 1e-12))))
        return KineticEffect(km_scale=km_scale, activity_factor=factor, vmax_scale=1.0)

    if mechanism is Mechanism.NONCOMPETITIVE:
        factor = 1.0 / (1.0 + i_over_ki)
        return KineticEffect(vmax_scale=factor, production_scale=factor, activity_factor=factor)

    if mechanism is Mechanism.UNCOMPETITIVE:
        if substrate_conc <= 0.0:
            return KineticEffect()
        factor = 1.0 / (1.0 + drug_conc / (ki * (1.0 + km / substrate_conc)))
        km_scale = 1.0 / (1.0 + i_over_ki)
        return KineticEffect(
            vmax_scale=factor,
            km_scale=km_scale,
            production_scale=factor,
            activity_factor=factor,
        )

    if mechanism is Mechanism.ALLOSTERIC_INHIBITION:
        factor = 1.0 / (1.0 + i_over_ki**n)
        km_scale = 1.0 + 0.25 * (i_over_ki**n)
        return KineticEffect(
            vmax_scale=factor,
            km_scale=km_scale,
            production_scale=factor,
            activity_factor=factor,
            binding_scale=factor,
        )

    if mechanism is Mechanism.ALLOSTERIC_ACTIVATION:
        ka = ka_allo if ka_allo is not None else ki
        sat = (drug_conc**n) / ((ka**n) + (drug_conc**n))
        boost = 1.0 + max(0.0, efficacy) * sat
        # Slight Km improvement under activators
        km_scale = 1.0 / (1.0 + 0.25 * sat)
        return KineticEffect(
            vmax_scale=boost,
            km_scale=km_scale,
            production_scale=boost,
            activity_factor=boost,
            binding_scale=boost,
        )

    raise ValueError(f"Unknown mechanism {mechanism!r}")


def mechanism_to_inhibition_model(mechanism: Mechanism) -> InhibitionModel:
    mapping = {
        Mechanism.COMPETITIVE: InhibitionModel.COMPETITIVE,
        Mechanism.NONCOMPETITIVE: InhibitionModel.NONCOMPETITIVE,
        Mechanism.UNCOMPETITIVE: InhibitionModel.UNCOMPETITIVE,
        Mechanism.ALLOSTERIC_INHIBITION: InhibitionModel.ALLOSTERIC,
        Mechanism.ALLOSTERIC_ACTIVATION: InhibitionModel.ALLOSTERIC,
    }
    return mapping[mechanism]


# ---------------------------------------------------------------------------
# Drug agent (PK + PD perturbation)
# ---------------------------------------------------------------------------


@dataclass
class DrugAgent(Perturbation):
    """
    Time-resolved drug with PK clearance and mechanism-specific PD transforms.

    Compatible with MassActionRHS hooks: at each step ``t`` the free drug
    concentration is computed from :class:`PharmacokineticProfile`, converted
    into kinetic scales, and written onto the target entity / edge rates.
    """

    target_id: str
    mechanism: Mechanism = Mechanism.COMPETITIVE
    name: str = ""
    ki: float = 1.0
    km: float = 1.0
    hill: float = 1.0
    efficacy: float = 1.0
    ka_allo: Optional[float] = None
    substrate_id: Optional[str] = None
    edge_ids: List[str] = field(default_factory=list)
    pk: PharmacokineticProfile = field(default_factory=PharmacokineticProfile)
    plateau_concentration: Optional[float] = None
    """If set, bypass PK and hold a constant free level while active."""
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base_kinetics: Optional[KineticParameters] = field(default=None, init=False, repr=False)
    _base_rates: Dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"agent[{self.mechanism.value}]:{self.target_id}"
        if self.ki <= 0.0:
            raise ValueError("ki must be positive")
        if self.km <= 0.0:
            raise ValueError("km must be positive")
        if self.hill <= 0.0:
            raise ValueError("hill must be positive")
        if self.efficacy < 0.0:
            raise ValueError("efficacy must be non-negative")
        # Align PK dosing onset with t_start when only defaults supplied
        if self.pk.dosing_times == [0.0] and self.t_start > 0.0:
            self.pk.dosing_times = [self.t_start]

    def free_concentration(self, t: float) -> float:
        if not self.is_active(t):
            if self.t_end is not None and t > self.t_end and not self.pk.hard_washout:
                # Natural clearance after washout window — allow remaining PK decay
                return self.pk.concentration(t, active_until=self.t_end)
            return 0.0
        if self.plateau_concentration is not None:
            return max(0.0, self.plateau_concentration)
        return self.pk.concentration(t, active_until=self.t_end)

    def _cache(self, state: SimulationState) -> None:
        if self._base_kinetics is None:
            self._base_kinetics = state.entity(self.target_id).kinetics
        if not self._base_rates:
            for eid in self.edge_ids:
                self._base_rates[eid] = state.network.get_edge(eid).rate_constant

    def _restore(self, state: SimulationState) -> None:
        if self._base_kinetics is not None:
            entity = state.entity(self.target_id)
            was_locked = entity.locked
            entity.locked = False
            entity.kinetics = self._base_kinetics
            entity.metadata.pop("drug_free_conc", None)
            entity.metadata.pop("drug_activity_factor", None)
            entity.metadata.pop("drug_mechanism", None)
            entity.locked = was_locked
        for eid, rate in self._base_rates.items():
            state.network.get_edge(eid).rate_constant = rate
        self.applied = False

    def apply(self, state: SimulationState, t: float) -> None:
        self._cache(state)

        # After hard washout end — full restore
        if (
            self.t_end is not None
            and t > self.t_end + 1e-15
            and self.pk.hard_washout
            and self.applied
        ):
            self._restore(state)
            return

        drug = self.free_concentration(t)
        if drug <= 0.0 and not self.is_active(t):
            if self.applied and self.t_end is not None and t > self.t_end:
                # Soft washout: continue decaying PD until negligible
                if drug < 1e-9:
                    self._restore(state)
                    return
            elif not self.is_active(t):
                return

        substrate = 0.0
        if self.substrate_id is not None:
            substrate = max(0.0, state.entity(self.substrate_id).concentration)

        effect = effect_from_mechanism(
            self.mechanism,
            drug,
            ki=self.ki,
            km=self.km,
            substrate_conc=substrate,
            hill=self.hill,
            efficacy=self.efficacy,
            ka_allo=self.ka_allo,
        )

        entity = state.entity(self.target_id)
        assert self._base_kinetics is not None
        was_locked = entity.locked
        entity.locked = False
        entity.kinetics = effect.apply(self._base_kinetics)
        entity.metadata["drug_free_conc"] = drug
        entity.metadata["drug_activity_factor"] = effect.activity_factor
        entity.metadata["drug_mechanism"] = self.mechanism.value
        entity.locked = was_locked

        for eid, base_rate in self._base_rates.items():
            state.network.get_edge(eid).rate_constant = max(
                0.0, base_rate * effect.activity_factor
            )

        self.applied = True
        state.extras[f"agent:{self.name}"] = {
            "concentration": drug,
            "activity_factor": effect.activity_factor,
            "vmax_scale": effect.vmax_scale,
            "km_scale": effect.km_scale,
            "mechanism": self.mechanism.value,
        }


# ---------------------------------------------------------------------------
# Dose–response
# ---------------------------------------------------------------------------


@dataclass
class DoseResponseCurve:
    """Empirical dose–response with interpolated potency metrics."""

    doses: List[float]
    responses: List[float]
    readout_id: str
    mode: str  # "inhibition" | "activation"
    baseline: float
    ic50: Optional[float] = None
    ec50: Optional[float] = None
    hill_estimate: Optional[float] = None
    emax: Optional[float] = None
    emin: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "doses": list(self.doses),
            "responses": list(self.responses),
            "readout_id": self.readout_id,
            "mode": self.mode,
            "baseline": self.baseline,
            "ic50": self.ic50,
            "ec50": self.ec50,
            "hill_estimate": self.hill_estimate,
            "emax": self.emax,
            "emin": self.emin,
        }


def _interpolate_threshold(
    doses: Sequence[float],
    values: Sequence[float],
    threshold: float,
    *,
    decreasing: bool,
) -> Optional[float]:
    """Log-linear interpolation of dose where ``values`` cross ``threshold``."""
    if len(doses) != len(values) or len(doses) < 2:
        return None
    for i in range(len(doses) - 1):
        y0, y1 = values[i], values[i + 1]
        crossed = (y0 - threshold) * (y1 - threshold) <= 0.0 and y0 != y1
        if not crossed:
            continue
        if decreasing and y0 < y1:
            continue
        if not decreasing and y0 > y1:
            continue
        d0, d1 = max(doses[i], 1e-15), max(doses[i + 1], 1e-15)
        frac = (threshold - y0) / (y1 - y0)
        log_d = math.log(d0) + frac * (math.log(d1) - math.log(d0))
        return math.exp(log_d)
    return None


def estimate_hill(
    doses: Sequence[float],
    fractional_effect: Sequence[float],
) -> Optional[float]:
    """
    Rough Hill slope from mid-curve logit–log dose regression.

    Uses points with effect in (0.05, 0.95).
    """
    xs: List[float] = []
    ys: List[float] = []
    for d, e in zip(doses, fractional_effect):
        if d <= 0.0 or not (0.05 < e < 0.95):
            continue
        xs.append(math.log(d))
        ys.append(math.log(e / (1.0 - e)))
    if len(xs) < 2:
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if abs(den) < 1e-15:
        return None
    return abs(num / den)


class DoseResponseModeler:
    """
    Sweep plateau drug concentrations and extract IC₅₀ / EC₅₀ from ODE endpoints.
    """

    def __init__(
        self,
        network_factory: NetworkFactory,
        *,
        config: Optional[SimulationConfig] = None,
    ) -> None:
        self.network_factory = network_factory
        self.config = config or SimulationConfig(t_end=40.0, dt=0.1, record_every=20)

    def sweep(
        self,
        *,
        target_id: str,
        readout_id: str,
        doses: Sequence[float],
        mechanism: Mechanism = Mechanism.COMPETITIVE,
        ki: float = 1.0,
        mode: str = "inhibition",
        readout_fn: Optional[Callable[[TrajectoryResult], float]] = None,
        extra_hooks: Optional[Sequence[PerturbationHook]] = None,
    ) -> DoseResponseCurve:
        if mode not in {"inhibition", "activation"}:
            raise ValueError("mode must be 'inhibition' or 'activation'")
        dose_list = [float(d) for d in doses]
        if any(d < 0.0 for d in dose_list):
            raise ValueError("doses must be non-negative")

        responses: List[float] = []
        for dose in dose_list:
            net = self.network_factory()
            # Resolve names → ids when factory rebuilds UUIDs
            tid = target_id if target_id in net.registry else _name_to_id(net, target_id)
            rid = readout_id if readout_id in net.registry else _name_to_id(net, readout_id)
            agent = DrugAgent(
                target_id=tid,
                mechanism=mechanism,
                ki=ki,
                plateau_concentration=dose,
                t_start=0.0,
                t_end=None,
                pk=PharmacokineticProfile(dose=dose, kel=0.0, dosing_times=[0.0]),
            )
            engine = DualEngineSimulator(net)
            hooks = [agent.as_hook()] + list(extra_hooks or [])
            traj = engine.run_ode(self.config, perturbation_hooks=hooks)
            if readout_fn is not None:
                responses.append(float(readout_fn(traj)))
            else:
                responses.append(float(traj.final_concentrations().get(rid, 0.0)))

        baseline = responses[0] if dose_list and dose_list[0] == 0.0 else max(responses + [0.0])
        emin = min(responses)
        emax = max(responses)
        span = max(emax - emin, 1e-12)

        if mode == "inhibition":
            # Fractional inhibition relative to baseline (zero-dose)
            frac = [clamp01((baseline - r) / max(baseline - emin, 1e-12)) for r in responses]
            half = baseline - 0.5 * (baseline - emin)
            ic50 = _interpolate_threshold(dose_list, responses, half, decreasing=True)
            hill = estimate_hill(dose_list, frac)
            return DoseResponseCurve(
                doses=dose_list,
                responses=responses,
                readout_id=readout_id,
                mode=mode,
                baseline=baseline,
                ic50=ic50,
                ec50=None,
                hill_estimate=hill,
                emax=emax,
                emin=emin,
            )

        frac = [clamp01((r - baseline) / span) for r in responses]
        half = baseline + 0.5 * (emax - baseline)
        ec50 = _interpolate_threshold(dose_list, responses, half, decreasing=False)
        hill = estimate_hill(dose_list, frac)
        return DoseResponseCurve(
            doses=dose_list,
            responses=responses,
            readout_id=readout_id,
            mode=mode,
            baseline=baseline,
            ic50=None,
            ec50=ec50,
            hill_estimate=hill,
            emax=emax,
            emin=emin,
        )


def _name_to_id(network: SignalingNetwork, name: str) -> str:
    for ent in network.registry.entities():
        if ent.name == name:
            return ent.entity_id
    raise KeyError(f"Entity {name!r} not found in network")


# ---------------------------------------------------------------------------
# Combination synergy
# ---------------------------------------------------------------------------


@dataclass
class SynergyResult:
    """Bliss / Loewe scores for a two-drug combination."""

    effect_a: float
    effect_b: float
    effect_ab: float
    bliss_expected: float
    bliss_score: float
    loewe_ci: Optional[float]
    interpretation: str
    doses: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "effect_a": self.effect_a,
            "effect_b": self.effect_b,
            "effect_ab": self.effect_ab,
            "bliss_expected": self.bliss_expected,
            "bliss_score": self.bliss_score,
            "loewe_ci": self.loewe_ci,
            "interpretation": self.interpretation,
            "doses": dict(self.doses),
        }


def bliss_independence(effect_a: float, effect_b: float) -> float:
    """Expected combined fractional effect under Bliss independence."""
    ea = clamp01(effect_a)
    eb = clamp01(effect_b)
    return ea + eb - ea * eb


def loewe_combination_index(
    dose_a: float,
    dose_b: float,
    mono_a_potent_dose: Optional[float],
    mono_b_potent_dose: Optional[float],
) -> Optional[float]:
    """
    Loewe CI = d_a/D_a + d_b/D_b where D_* are mono doses giving the combo effect.

    CI < 1 synergy, CI ≈ 1 additive, CI > 1 antagonism.
    """
    if mono_a_potent_dose is None or mono_b_potent_dose is None:
        return None
    if mono_a_potent_dose <= 0.0 or mono_b_potent_dose <= 0.0:
        return None
    return dose_a / mono_a_potent_dose + dose_b / mono_b_potent_dose


def interpret_synergy(bliss_score: float, loewe_ci: Optional[float]) -> str:
    if loewe_ci is not None:
        if loewe_ci < 0.9 and bliss_score > 0.05:
            return "synergy"
        if loewe_ci > 1.1 and bliss_score < -0.05:
            return "antagonism"
        return "additive"
    if bliss_score > 0.05:
        return "synergy"
    if bliss_score < -0.05:
        return "antagonism"
    return "additive"


class CombinationSynergyCalculator:
    """
    Simulate single agents and combinations to score Bliss / Loewe synergy.
    """

    def __init__(
        self,
        network_factory: NetworkFactory,
        *,
        config: Optional[SimulationConfig] = None,
    ) -> None:
        self.network_factory = network_factory
        self.config = config or SimulationConfig(t_end=40.0, dt=0.1, record_every=20)

    def _run_agents(self, agents: Sequence[DrugAgent], readout_id: str) -> float:
        net = self.network_factory()
        resolved: List[DrugAgent] = []
        for agent in agents:
            a = copy.deepcopy(agent)
            if a.target_id not in net.registry:
                a.target_id = _name_to_id(net, a.target_id)
            resolved.append(a)
        rid = readout_id if readout_id in net.registry else _name_to_id(net, readout_id)
        engine = DualEngineSimulator(net)
        traj = engine.run_ode(
            self.config,
            perturbation_hooks=[a.as_hook() for a in resolved],
        )
        return float(traj.final_concentrations().get(rid, 0.0))

    def score(
        self,
        agent_a: DrugAgent,
        agent_b: DrugAgent,
        *,
        readout_id: str,
        baseline: Optional[float] = None,
        dose_a: Optional[float] = None,
        dose_b: Optional[float] = None,
        ic50_a: Optional[float] = None,
        ic50_b: Optional[float] = None,
    ) -> SynergyResult:
        """
        Fractional inhibition effects relative to untreated baseline.

        When ``ic50_*`` are supplied, Loewe CI uses those as D_a / D_b for the
        observed combination effect level (approximation when isoboles unavailable).
        """
        if baseline is None:
            baseline = self._run_agents([], readout_id)

        ra = self._run_agents([agent_a], readout_id)
        rb = self._run_agents([agent_b], readout_id)
        rab = self._run_agents([agent_a, agent_b], readout_id)

        def frac(r: float) -> float:
            return clamp01((baseline - r) / max(baseline, 1e-12))

        ea, eb, eab = frac(ra), frac(rb), frac(rab)
        expected = bliss_independence(ea, eb)
        bliss_score = eab - expected

        da = dose_a if dose_a is not None else (
            agent_a.plateau_concentration
            if agent_a.plateau_concentration is not None
            else agent_a.pk.dose
        )
        db = dose_b if dose_b is not None else (
            agent_b.plateau_concentration
            if agent_b.plateau_concentration is not None
            else agent_b.pk.dose
        )
        ci = loewe_combination_index(da, db, ic50_a, ic50_b)
        return SynergyResult(
            effect_a=ea,
            effect_b=eb,
            effect_ab=eab,
            bliss_expected=expected,
            bliss_score=bliss_score,
            loewe_ci=ci,
            interpretation=interpret_synergy(bliss_score, ci),
            doses={"a": da, "b": db},
        )


class PharmacologyEngine:
    """
    Facade bundling drug agents, dose–response, and synergy tooling.
    """

    def __init__(self, network_factory: Optional[NetworkFactory] = None) -> None:
        self.network_factory = network_factory
        self.agents: List[DrugAgent] = []

    def add_agent(self, agent: DrugAgent) -> "PharmacologyEngine":
        self.agents.append(agent)
        return self

    def manager(self) -> PerturbationManager:
        mgr = PerturbationManager()
        mgr.extend(self.agents)
        return mgr

    def load_into(self, engine: DualEngineSimulator) -> PerturbationManager:
        mgr = self.manager()
        for hook in mgr.hooks():
            engine.add_hook(hook)
        return mgr

    def dose_response(self, **kwargs: Any) -> DoseResponseCurve:
        if self.network_factory is None:
            raise RuntimeError("network_factory required for dose_response")
        return DoseResponseModeler(self.network_factory).sweep(**kwargs)

    def synergy(self, agent_a: DrugAgent, agent_b: DrugAgent, **kwargs: Any) -> SynergyResult:
        if self.network_factory is None:
            raise RuntimeError("network_factory required for synergy")
        return CombinationSynergyCalculator(self.network_factory).score(
            agent_a, agent_b, **kwargs
        )
