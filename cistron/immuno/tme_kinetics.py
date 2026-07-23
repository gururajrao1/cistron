"""
Tumor microenvironment (TME) multi-population kinetics.

Tracks Tumor, CTL, Treg, MDSC populations with TGF-β / IL-10 / VEGF cytokine
feedback, optionally injecting nodes into a SignalingNetwork for MassActionRHS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import math

from cistron.components import KineticParameters, Protein
from cistron.immuno.checkpoints import CheckpointState, evaluate_checkpoints, CheckpointConfig
from cistron.perturbation import Perturbation
from cistron.simulation import SimulationState
from cistron.topology import InteractionType, SignalingNetwork


@dataclass
class TMEState:
    """Instantaneous TME compartment abundances (relative units)."""

    tumor: float = 1.0
    ctl: float = 0.6
    treg: float = 0.3
    mdsc: float = 0.25
    tgfb: float = 0.4
    il10: float = 0.35
    vegf: float = 0.5
    time: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "tumor": self.tumor,
            "ctl": self.ctl,
            "treg": self.treg,
            "mdsc": self.mdsc,
            "tgfb": self.tgfb,
            "il10": self.il10,
            "vegf": self.vegf,
            "time": self.time,
        }

    def vector(self) -> List[float]:
        return [self.tumor, self.ctl, self.treg, self.mdsc, self.tgfb, self.il10, self.vegf]

    @classmethod
    def from_vector(cls, y: Sequence[float], t: float = 0.0) -> "TMEState":
        return cls(
            tumor=max(0.0, y[0]),
            ctl=max(0.0, y[1]),
            treg=max(0.0, y[2]),
            mdsc=max(0.0, y[3]),
            tgfb=max(0.0, y[4]),
            il10=max(0.0, y[5]),
            vegf=max(0.0, y[6]),
            time=t,
        )


@dataclass
class TMEParameters:
    """Rate constants for the TME ODE system."""

    # Tumor
    tumor_growth: float = 0.12
    tumor_carry: float = 3.0
    ctl_kill: float = 0.35
    # CTL
    ctl_priming: float = 0.18
    ctl_decay: float = 0.08
    ctl_exhaust_sens: float = 0.9
    # Treg / MDSC
    treg_recruit: float = 0.10
    treg_decay: float = 0.06
    mdsc_recruit: float = 0.12
    mdsc_decay: float = 0.05
    # Cytokines
    tgfb_prod: float = 0.15
    tgfb_clear: float = 0.10
    il10_prod: float = 0.12
    il10_clear: float = 0.10
    vegf_prod: float = 0.14
    vegf_clear: float = 0.09
    # Suppression strengths
    tgfb_suppress_ctl: float = 0.55
    il10_suppress_ctl: float = 0.45
    mdsc_suppress_ctl: float = 0.50
    treg_suppress_ctl: float = 0.40
    vegf_boost_mdsc: float = 0.35
    # Antigen / exhaustion external drives
    antigen_drive: float = 0.5
    epsilon_exhaustion: float = 0.0


def tme_rhs(state: TMEState, params: TMEParameters) -> List[float]:
    """
    Continuous TME mass-action / logistic RHS.

    Tumor logistic growth minus CTL killing.
    CTL priming by antigen, suppressed by TGF-β/IL-10/Treg/MDSC and ε.
    Treg/MDSC recruited by tumor + VEGF; cytokines produced by suppressors / tumor.
    """
    T, C, R, M, tgfb, il10, vegf = state.vector()
    p = params
    eps = max(0.0, min(1.0, p.epsilon_exhaustion))
    antigen = max(0.0, p.antigen_drive)

    suppress = (
        1.0
        + p.tgfb_suppress_ctl * tgfb
        + p.il10_suppress_ctl * il10
        + p.mdsc_suppress_ctl * M
        + p.treg_suppress_ctl * R
    )
    ctl_eff = C / suppress * max(0.05, 1.0 - p.ctl_exhaust_sens * eps)

    dT = p.tumor_growth * T * (1.0 - T / max(1e-6, p.tumor_carry)) - p.ctl_kill * ctl_eff * T
    dC = (
        p.ctl_priming * antigen * (T / (1.0 + T)) * max(0.05, 1.0 - eps)
        - p.ctl_decay * C * (1.0 + 0.5 * tgfb + 0.4 * il10)
    )
    dR = p.treg_recruit * T * tgfb / (1.0 + tgfb) - p.treg_decay * R
    dM = (
        p.mdsc_recruit * T * (1.0 + p.vegf_boost_mdsc * vegf) / (1.0 + vegf)
        - p.mdsc_decay * M
    )
    d_tgfb = p.tgfb_prod * (0.4 * T + 0.8 * R + 0.5 * M) - p.tgfb_clear * tgfb
    d_il10 = p.il10_prod * (0.5 * R + 0.7 * M) - p.il10_clear * il10
    d_vegf = p.vegf_prod * (0.9 * T + 0.3 * M) - p.vegf_clear * vegf
    return [dT, dC, dR, dM, d_tgfb, d_il10, d_vegf]


def _rk4_step(y: List[float], t: float, dt: float, params: TMEParameters) -> List[float]:
    s0 = TMEState.from_vector(y, t)
    k1 = tme_rhs(s0, params)
    s2 = TMEState.from_vector([y[i] + 0.5 * dt * k1[i] for i in range(7)], t + 0.5 * dt)
    k2 = tme_rhs(s2, params)
    s3 = TMEState.from_vector([y[i] + 0.5 * dt * k2[i] for i in range(7)], t + 0.5 * dt)
    k3 = tme_rhs(s3, params)
    s4 = TMEState.from_vector([y[i] + dt * k3[i] for i in range(7)], t + dt)
    k4 = tme_rhs(s4, params)
    return [
        max(0.0, y[i] + (dt / 6.0) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]))
        for i in range(7)
    ]


@dataclass
class TMETrajectory:
    """Discrete TME integration result."""

    times: List[float]
    states: List[TMEState]

    def __len__(self) -> int:
        return len(self.times)

    def final(self) -> TMEState:
        return self.states[-1]

    def series(self, key: str) -> List[float]:
        return [float(s.as_dict()[key]) for s in self.states]


class TMESimulator:
    """Standalone RK4 integrator for the TME population model."""

    def __init__(self, params: Optional[TMEParameters] = None) -> None:
        self.params = params or TMEParameters()

    def run(
        self,
        initial: Optional[TMEState] = None,
        *,
        t_end: float = 40.0,
        dt: float = 0.25,
        checkpoint: Optional[CheckpointState] = None,
        antigen_drive: Optional[float] = None,
    ) -> TMETrajectory:
        params = TMEParameters(**{**self.params.__dict__})
        if checkpoint is not None:
            params.epsilon_exhaustion = checkpoint.epsilon_exhaustion
        if antigen_drive is not None:
            params.antigen_drive = antigen_drive

        state0 = initial or TMEState()
        y = state0.vector()
        times = [0.0]
        states = [TMEState.from_vector(y, 0.0)]
        t = 0.0
        n_steps = max(1, int(math.ceil(t_end / dt)))
        for _ in range(n_steps):
            y = _rk4_step(y, t, dt, params)
            t = min(t_end, t + dt)
            times.append(t)
            states.append(TMEState.from_vector(y, t))
            if t >= t_end - 1e-12:
                break
        return TMETrajectory(times=times, states=states)


# ---------------------------------------------------------------------------
# Network injection / MassActionRHS coupling
# ---------------------------------------------------------------------------

_TME_NODES = ("TUMOR", "CTL", "Treg", "MDSC", "TGFb", "IL10", "VEGF")


def inject_tme_nodes(
    network: SignalingNetwork,
    initial: Optional[TMEState] = None,
) -> Dict[str, str]:
    """Create TME population / cytokine nodes on a signaling network."""
    init = initial or TMEState()
    conc = {
        "TUMOR": init.tumor,
        "CTL": init.ctl,
        "Treg": init.treg,
        "MDSC": init.mdsc,
        "TGFb": init.tgfb,
        "IL10": init.il10,
        "VEGF": init.vegf,
    }
    ids: Dict[str, str] = {}
    for name in _TME_NODES:
        found = None
        for ent in network.registry.entities():
            if ent.name.upper() == name.upper():
                found = ent.entity_id
                break
        if found is None:
            node = Protein(
                name=name,
                concentration=conc[name],
                kinetics=KineticParameters(
                    production_rate=0.05,
                    degradation_rate=0.07,
                    basal_activity=0.05,
                    vmax=1.0,
                    km=1.0,
                ),
                metadata={"tme_population": True},
            )
            # Populations are advanced by TMEPerturbation, not MassActionRHS.
            node.locked = True
            network.add_node(node)
            ids[name] = node.entity_id
        else:
            ids[name] = found
            ent = network.registry.get(found)
            ent.concentration = conc[name]
            ent.locked = True
            ent.metadata["tme_population"] = True

    def _link(a: str, b: str, kind: InteractionType, rate: float) -> None:
        sa, sb = ids[a], ids[b]
        for e in network.out_edges(sa):
            if e.target_id == sb:
                return
        network.connect(sa, sb, kind, rate_constant=rate)

    _link("CTL", "TUMOR", InteractionType.INHIBITION, 1.0)
    _link("Treg", "CTL", InteractionType.INHIBITION, 0.7)
    _link("MDSC", "CTL", InteractionType.INHIBITION, 0.8)
    _link("TGFb", "CTL", InteractionType.INHIBITION, 0.6)
    _link("IL10", "CTL", InteractionType.INHIBITION, 0.5)
    _link("TUMOR", "VEGF", InteractionType.ACTIVATION, 0.5)
    _link("VEGF", "MDSC", InteractionType.ACTIVATION, 0.6)
    _link("TUMOR", "TGFb", InteractionType.ACTIVATION, 0.4)
    return ids


def sync_state_to_network(network: SignalingNetwork, ids: Mapping[str, str], state: TMEState) -> None:
    mapping = {
        "TUMOR": state.tumor,
        "CTL": state.ctl,
        "Treg": state.treg,
        "MDSC": state.mdsc,
        "TGFb": state.tgfb,
        "IL10": state.il10,
        "VEGF": state.vegf,
    }
    for name, val in mapping.items():
        eid = ids.get(name)
        if eid is None:
            continue
        ent = network.registry.get(eid)
        # Cytokine-driven kinetic nudges on CTL / tumor
        if name == "CTL":
            suppress = 1.0 + 0.25 * state.tgfb + 0.2 * state.il10
            k = ent.kinetics
            ent.kinetics = k.with_updates(
                vmax=max(0.08, 1.0 / suppress),
                production_rate=max(0.03, 0.06 / suppress),
                degradation_rate=max(0.02, min(0.15, 0.04 * suppress)),
            )
            ent.concentration = max(0.05, val)
        elif name == "TUMOR":
            k = ent.kinetics
            kill = 0.04 * (1.0 + 0.8 * state.ctl / (1.0 + state.treg + state.mdsc))
            ent.kinetics = k.with_updates(degradation_rate=max(0.01, kill))
            ent.concentration = val
        else:
            ent.concentration = val


@dataclass
class TMEPerturbation(Perturbation):
    """
    Advance an internal TME integrator each ODE step and push populations
    onto network node concentrations / kinetics.
    """

    network: SignalingNetwork = field(repr=False)
    params: TMEParameters = field(default_factory=TMEParameters)
    initial: TMEState = field(default_factory=TMEState)
    node_ids: Dict[str, str] = field(default_factory=dict)
    checkpoint_config: Optional[CheckpointConfig] = None
    name: str = "tme_kinetics"
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _y: List[float] = field(default_factory=list, init=False, repr=False)
    _t_last: float = field(default=0.0, init=False, repr=False)
    _history: List[TMEState] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.node_ids:
            self.node_ids = inject_tme_nodes(self.network, self.initial)
        self._y = self.initial.vector()
        self._t_last = 0.0
        self._history = [TMEState.from_vector(self._y, 0.0)]

    @property
    def history(self) -> List[TMEState]:
        return list(self._history)

    def apply(self, state: SimulationState, t: float) -> None:
        if t < self.t_start:
            return
        if self.t_end is not None and t > self.t_end:
            return

        params = TMEParameters(**{**self.params.__dict__})
        if self.checkpoint_config is not None:
            ck = evaluate_checkpoints(self.checkpoint_config)
            params.epsilon_exhaustion = ck.epsilon_exhaustion

        dt = max(1e-6, t - self._t_last) if t > self._t_last else 0.05
        if t > self._t_last:
            # sub-step for stability if ODE dt is large
            remaining = dt
            while remaining > 1e-12:
                step = min(0.25, remaining)
                self._y = _rk4_step(self._y, self._t_last, step, params)
                self._t_last += step
                remaining -= step
            st = TMEState.from_vector(self._y, t)
            self._history.append(st)
            sync_state_to_network(state.network, self.node_ids, st)
            self.applied = True


def make_demo_tme_params(*, exhausted: bool = False) -> TMEParameters:
    return TMEParameters(
        antigen_drive=0.7,
        epsilon_exhaustion=0.65 if exhausted else 0.15,
        tumor_growth=0.14,
        ctl_kill=0.4,
    )
