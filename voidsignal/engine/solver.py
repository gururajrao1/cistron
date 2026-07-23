"""
Kraeutler Logic-Based Hill-Cube ODE engine for CausalActivityGraph.

Integrates OmniPath / SIGNOR activity-flow graphs with continuous Boolean
Hill cubes, VIPER/PROGENy footprint priors, VCF LoF knockouts, and PK/PD
occupancy scaling — separate from :class:`~voidsignal.simulation.MassActionRHS`
(which remains untouched).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

import numpy as np
from scipy.integrate import solve_ivp

from voidsignal.models.graph import (
    ActivityFlowEdge,
    CausalActivityGraph,
    GraphNode,
    MechanismKind,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HILL_N = 3.0
DEFAULT_EC50 = 0.5
DEFAULT_T_END_MIN = 60.0

MASTER_REGULATORS = frozenset({"HIF1A", "TP53", "P53", "STAT3", "STAT1", "MYC", "NFKB1"})
STRUCTURAL_OUTPUT_GENES = frozenset({"VEGFA", "VEGF", "GLUT1", "SLC2A1", "LDHA", "PDK1", "BNIP3"})

# Curated VIPER-style regulon weights for hypoxia / stress demos
DEFAULT_REGULONS: Dict[str, Dict[str, float]] = {
    "HIF1A": {"VEGFA": 1.0, "GLUT1": 1.0, "EGLN1": 0.6, "LDHA": 0.8, "PDK1": 0.7},
    "TP53": {"CDKN1A": 1.0, "BAX": 0.9, "MDM2": 0.7, "GADD45A": 0.6},
    "STAT3": {"MYC": 0.8, "BCL2": 0.7, "VEGFA": 0.5},
}


# ---------------------------------------------------------------------------
# Hill cubes & continuous logic
# ---------------------------------------------------------------------------


def hill_activation(x: float, *, n: float = DEFAULT_HILL_N, ec50: float = DEFAULT_EC50) -> float:
    """f(x) = x^n / (x^n + EC50^n), clamped to [0, 1]."""
    x = max(0.0, float(x))
    if x <= 0.0:
        return 0.0
    xn = x**n
    kn = ec50**n
    denom = xn + kn
    if denom <= 0.0:
        return 0.0
    return min(1.0, max(0.0, xn / denom))


def hill_inhibition(x: float, *, n: float = DEFAULT_HILL_N, ec50: float = DEFAULT_EC50) -> float:
    """f(x) = 1 − x^n / (x^n + EC50^n)."""
    return 1.0 - hill_activation(x, n=n, ec50=ec50)


def logic_or(a: float, b: float) -> float:
    """Probabilistic OR: a + b − a·b."""
    a = min(1.0, max(0.0, a))
    b = min(1.0, max(0.0, b))
    return a + b - a * b


def logic_and(a: float, b: float) -> float:
    """AND: a · b."""
    return min(1.0, max(0.0, a)) * min(1.0, max(0.0, b))


def logic_or_reduce(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    acc = float(values[0])
    for v in values[1:]:
        acc = logic_or(acc, v)
    return acc


def logic_and_reduce(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    acc = 1.0
    for v in values:
        acc = logic_and(acc, v)
    return acc


def inhibitory_dominance(activation: float, inhibition: float) -> float:
    """f(A_act, B_inh) = f(A_act) · (1 − f(B_inh))."""
    return min(1.0, max(0.0, activation)) * (1.0 - min(1.0, max(0.0, inhibition)))


def combine_inputs(
    activations: Sequence[float],
    inhibitions: Sequence[float],
    *,
    gate: str = "or",
) -> float:
    """
    Multi-input continuous Boolean.

    * ``or`` (default): OR of activators, OR of inhibitors, then ANDNOT.
    * ``and``: AND of activators (co-complex), then ANDNOT inhibitors.
    """
    gate_l = (gate or "or").lower()
    if gate_l == "and":
        act = logic_and_reduce(list(activations)) if activations else 0.0
    else:
        act = logic_or_reduce(list(activations)) if activations else 0.0
    inh = logic_or_reduce(list(inhibitions)) if inhibitions else 0.0

    if activations and inhibitions:
        return inhibitory_dominance(act, inh)
    if activations:
        return act
    if inhibitions:
        # Pure repression of constitutive basal (=1)
        return inhibitory_dominance(1.0, inh)
    # No regulators → constitutive driver (environmental / housekeeping)
    return 1.0


# ---------------------------------------------------------------------------
# Perturbation / footprint payloads
# ---------------------------------------------------------------------------


@dataclass
class DrugDose:
    """PK/PD occupancy against one target node."""

    target: str
    c_drug: float
    ki: float

    def __post_init__(self) -> None:
        self.target = self.target.strip()
        self.c_drug = max(0.0, float(self.c_drug))
        self.ki = max(1e-15, float(self.ki))  # avoid zero-division

    def occupancy(self) -> float:
        """C / (C + Ki) ∈ [0, 1)."""
        return self.c_drug / (self.c_drug + self.ki)

    def capacity_scale(self) -> float:
        """1 − C/(C+Ki)."""
        return 1.0 - self.occupancy()


@dataclass
class FootprintPriors:
    """
    VIPER/PROGENy-style multi-omics overlay.

    Attributes
    ----------
    expression :
        Gene expression vector ``E_g`` (arbitrary non-negative scale).
    regulons :
        Master-regulator → {target → weight} matrix ``M_{k,g}``.
    fold_changes :
        log2 fold-change (or linear FC) for structural / output genes.
        Capacity becomes ``w_i *= 2^{FC_i}`` (clipped).
    """

    expression: Dict[str, float] = field(default_factory=dict)
    regulons: Dict[str, Dict[str, float]] = field(default_factory=dict)
    fold_changes: Dict[str, float] = field(default_factory=dict)


@dataclass
class HillCubeResult:
    """Trajectory bundle from :meth:`HillCubeEngine.simulate`."""

    times: np.ndarray
    states: Dict[str, np.ndarray]
    symbols: List[str]
    success: bool
    message: str
    weights: Dict[str, float]
    y0: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def final(self) -> Dict[str, float]:
        return {s: float(self.states[s][-1]) for s in self.symbols}

    def series(self, symbol: str) -> np.ndarray:
        return self.states[symbol]


# Serialization / scrubber contract alias
SimulationResult = HillCubeResult


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class HillCubeConfig:
    """Integrator / Hill-function configuration."""

    hill_n: float = DEFAULT_HILL_N
    ec50: float = DEFAULT_EC50
    t_start: float = 0.0
    t_end: float = DEFAULT_T_END_MIN
    method: str = "RK45"
    rtol: float = 1e-5
    atol: float = 1e-7
    max_step: float = 1.0
    dense_output_points: int = 121
    default_gate: str = "or"


class HillCubeEngine:
    """
    Kraeutler normalized Hill-cube ODE solver over a :class:`CausalActivityGraph`.

        dy_i/dt = (1/τ_i) · (w_i · f(inputs) − y_i)

    with continuous OR / AND / inhibitory-dominance gates and optional
    VIPER footprint + PK/PD + LoF overlays.
    """

    def __init__(
        self,
        graph: CausalActivityGraph,
        *,
        config: Optional[HillCubeConfig] = None,
    ) -> None:
        self.graph = graph
        self.config = config or HillCubeConfig()
        self.symbols: List[str] = sorted(graph.nodes.keys())
        self._index = {s: i for i, s in enumerate(self.symbols)}
        self._incoming: Dict[str, List[ActivityFlowEdge]] = {s: [] for s in self.symbols}
        for edge in graph.edges:
            if edge.target in self._incoming and edge.source in self._index:
                self._incoming[edge.target].append(edge)

        # Mutable capacity weights (start from graph node activity_weight)
        self.weights: Dict[str, float] = {
            s: float(graph.nodes[s].activity_weight) for s in self.symbols
        }
        self.tau: Dict[str, float] = {
            s: max(1e-6, float(graph.nodes[s].tau_min)) for s in self.symbols
        }
        self.gates: Dict[str, str] = {
            s: str(graph.nodes[s].metadata.get("logic_gate", self.config.default_gate))
            for s in self.symbols
        }
        # Clamped environmental / experimental drivers (dy/dt = 0)
        self.clamped: Dict[str, float] = {}
        self.knockouts: set[str] = set()
        self.y0_override: Dict[str, float] = {}
        self._drugs: List[DrugDose] = []
        self._footprint_meta: Dict[str, Any] = {}

    # -- perturbations -------------------------------------------------------

    def clamp(self, symbol: str, value: float) -> None:
        """Hold a node at a fixed activity (e.g. environmental O₂)."""
        sym = symbol.strip()
        if sym not in self._index:
            raise KeyError(f"Unknown node {sym!r}")
        self.clamped[sym] = min(1.0, max(0.0, float(value)))

    def knockout(self, symbols: Iterable[str]) -> None:
        """Loss-of-function / VCF null: enforce w_i = 0."""
        for raw in symbols:
            sym = raw.strip()
            if sym not in self._index:
                continue
            self.knockouts.add(sym)
            self.weights[sym] = 0.0

    def apply_drug(self, dose: DrugDose) -> None:
        """Scale target capacity by 1 − C/(C+Ki)."""
        sym = dose.target
        if sym not in self._index:
            return
        if sym in self.knockouts:
            self.weights[sym] = 0.0
            return
        self._drugs.append(dose)
        base = float(self.graph.nodes[sym].activity_weight)
        # Stack multiple drugs multiplicatively
        scale = dose.capacity_scale()
        self.weights[sym] = max(0.0, min(1.0, self.weights[sym] * scale))
        # Recompute from base × all doses if re-applied
        w = base
        for d in self._drugs:
            if d.target == sym:
                w *= d.capacity_scale()
        if sym in self.knockouts:
            w = 0.0
        self.weights[sym] = max(0.0, min(1.0, w))

    def apply_drugs(self, doses: Sequence[DrugDose]) -> None:
        for d in doses:
            self.apply_drug(d)

    def apply_footprints(self, priors: FootprintPriors) -> None:
        """
        VIPER/PROGENy overlay:

        * Master regulators → y_k(t0) from renormalised regulon score S_k
        * Structural genes → w_i ← w_structural · 2^{FC_i}
        """
        regulons = priors.regulons or DEFAULT_REGULONS
        expression = {k.strip(): max(0.0, float(v)) for k, v in priors.expression.items()}
        scores: Dict[str, float] = {}

        for tf, targets in regulons.items():
            tf_u = tf.strip()
            if tf_u not in self._index and tf_u.upper() not in self._index:
                # try case-insensitive
                match = next((s for s in self.symbols if s.upper() == tf_u.upper()), None)
                if match is None:
                    continue
                tf_u = match
            # Restrict to detected targets present in expression or graph
            detected = {
                g: float(w)
                for g, w in targets.items()
                if g in expression or g in self._index
            }
            if not detected:
                continue
            abs_sum = sum(abs(w) for w in detected.values()) or 1.0
            m_prime = {g: w / abs_sum for g, w in detected.items()}
            score = 0.0
            for g, w in m_prime.items():
                e = expression.get(g)
                if e is None:
                    # Fallback: use graph initial concentration as proxy expression
                    e = float(self.graph.nodes[g].initial_concentration) if g in self.graph.nodes else 0.0
                score += w * e
            # Map raw score into [0, 1]
            y0 = min(1.0, max(0.0, score if score <= 1.0 else math.tanh(score)))
            self.y0_override[tf_u] = y0
            scores[tf_u] = score

        for gene, fc in priors.fold_changes.items():
            sym = gene.strip()
            match = next((s for s in self.symbols if s.upper() == sym.upper()), None)
            if match is None:
                continue
            if match.upper() not in {g.upper() for g in STRUCTURAL_OUTPUT_GENES} and match not in STRUCTURAL_OUTPUT_GENES:
                # Still allow explicit FC on listed structural set only
                if match.upper() not in STRUCTURAL_OUTPUT_GENES and match not in {"VEGFA", "GLUT1"}:
                    continue
            if match in self.knockouts:
                self.weights[match] = 0.0
                continue
            structural_w = float(self.graph.nodes[match].activity_weight)
            scaled = structural_w * (2.0 ** float(fc))
            self.weights[match] = max(0.0, min(1.0, scaled))

        self._footprint_meta = {"viper_scores": scores, "n_expression": len(expression)}

    # -- RHS -----------------------------------------------------------------

    def _f_inputs(self, symbol: str, y: np.ndarray) -> float:
        acts: List[float] = []
        inhs: List[float] = []
        n = self.config.hill_n
        ec = self.config.ec50
        for edge in self._incoming[symbol]:
            src_y = float(y[self._index[edge.source]])
            if edge.sign > 0:
                acts.append(hill_activation(src_y, n=n, ec50=ec))
            else:
                # Inhibition uses activation Hill of the suppressor as occupancy
                inhs.append(hill_activation(src_y, n=n, ec50=ec))
        return combine_inputs(acts, inhs, gate=self.gates.get(symbol, "or"))

    def _rhs(self, _t: float, y: np.ndarray) -> np.ndarray:
        dy = np.zeros_like(y)
        for sym, i in self._index.items():
            if sym in self.clamped:
                dy[i] = 0.0
                continue
            tau = self.tau[sym]
            w = self.weights[sym]
            if sym in self.knockouts:
                w = 0.0
            f_in = self._f_inputs(sym, y)
            target = w * f_in
            dy[i] = (1.0 / tau) * (target - float(y[i]))
        return dy

    def _y0(self) -> np.ndarray:
        y0 = np.zeros(len(self.symbols), dtype=float)
        for sym, i in self._index.items():
            if sym in self.clamped:
                y0[i] = self.clamped[sym]
            elif sym in self.y0_override:
                y0[i] = self.y0_override[sym]
            else:
                y0[i] = min(1.0, max(0.0, float(self.graph.nodes[sym].initial_concentration)))
            if sym in self.knockouts:
                y0[i] = 0.0
        return y0

    def simulate(
        self,
        *,
        t_end: Optional[float] = None,
        method: Optional[str] = None,
    ) -> HillCubeResult:
        """Integrate with ``scipy.integrate.solve_ivp`` and clamp y ∈ [0, 1]."""
        cfg = self.config
        t0 = float(cfg.t_start)
        t1 = float(t_end if t_end is not None else cfg.t_end)
        meth = method or cfg.method
        y0 = self._y0()

        # Enforce clamps in y0
        for sym, val in self.clamped.items():
            y0[self._index[sym]] = val

        t_eval = np.linspace(t0, t1, max(2, int(cfg.dense_output_points)))

        def wrapped(t: float, y: np.ndarray) -> np.ndarray:
            # Soft clamp state before evaluating (numerical safety)
            y_c = np.clip(y, 0.0, 1.0)
            for sym, val in self.clamped.items():
                y_c[self._index[sym]] = val
            for sym in self.knockouts:
                y_c[self._index[sym]] = 0.0
            return self._rhs(t, y_c)

        sol = solve_ivp(
            wrapped,
            (t0, t1),
            y0,
            method=meth,
            t_eval=t_eval,
            rtol=cfg.rtol,
            atol=cfg.atol,
            max_step=cfg.max_step,
            dense_output=False,
        )

        ys = np.clip(sol.y, 0.0, 1.0)
        # Re-apply clamps / knockouts on output
        for sym, val in self.clamped.items():
            ys[self._index[sym], :] = val
        for sym in self.knockouts:
            ys[self._index[sym], :] = 0.0

        states = {s: ys[i].copy() for s, i in self._index.items()}
        return HillCubeResult(
            times=sol.t.copy(),
            states=states,
            symbols=list(self.symbols),
            success=bool(sol.success),
            message=str(sol.message),
            weights=dict(self.weights),
            y0={s: float(y0[i]) for s, i in self._index.items()},
            metadata={
                "method": meth,
                "t_end": t1,
                "knockouts": sorted(self.knockouts),
                "clamped": dict(self.clamped),
                "drugs": [
                    {"target": d.target, "c_drug": d.c_drug, "ki": d.ki, "scale": d.capacity_scale()}
                    for d in self._drugs
                ],
                "footprint": dict(self._footprint_meta),
                "n_eval": int(getattr(sol, "nfev", 0) or 0),
            },
        )


def simulate_graph(
    graph: CausalActivityGraph,
    *,
    clamp: Optional[Mapping[str, float]] = None,
    knockouts: Optional[Sequence[str]] = None,
    drugs: Optional[Sequence[DrugDose]] = None,
    footprints: Optional[FootprintPriors] = None,
    config: Optional[HillCubeConfig] = None,
    t_end: Optional[float] = None,
) -> HillCubeResult:
    """Convenience: build engine, apply overlays, integrate."""
    eng = HillCubeEngine(graph, config=config)
    if clamp:
        for k, v in clamp.items():
            if k in eng._index:
                eng.clamp(k, v)
    if knockouts:
        eng.knockout(knockouts)
    if drugs:
        eng.apply_drugs(list(drugs))
    if footprints:
        eng.apply_footprints(footprints)
    return eng.simulate(t_end=t_end)


__all__ = [
    "DEFAULT_EC50",
    "DEFAULT_HILL_N",
    "DEFAULT_REGULONS",
    "DEFAULT_T_END_MIN",
    "DrugDose",
    "FootprintPriors",
    "HillCubeConfig",
    "HillCubeEngine",
    "HillCubeResult",
    "MASTER_REGULATORS",
    "STRUCTURAL_OUTPUT_GENES",
    "combine_inputs",
    "hill_activation",
    "hill_inhibition",
    "inhibitory_dominance",
    "logic_and",
    "logic_or",
    "simulate_graph",
]
