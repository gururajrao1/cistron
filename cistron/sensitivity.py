"""
Global & local sensitivity analysis for CISTRON Phase 8.

Measures how kinetic-parameter uncertainty propagates into trajectory outputs:

* **Local** — centred finite-difference ∂Y/∂k matrices at the nominal point.
* **Morris** — elementary-effects screening (μ*, σ) over the parameter hypercube.
* **Sobol-style** — first-order and total-effect variance decomposition via a
  Saltelli-like sample design (pure Python).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import logging
import math
import random

from cistron.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from cistron.storage import deserialize_network, serialize_network
from cistron.topology import SignalingNetwork

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParameterSpec:
    """Identifiable kinetic parameter on a network entity."""

    entity_id: str
    field: str
    lower: float
    upper: float
    name: str = ""

    def __post_init__(self) -> None:
        if self.upper <= self.lower:
            raise ValueError(f"Invalid bounds for {self.label}: [{self.lower}, {self.upper}]")
        if self.lower < 0.0:
            raise ValueError("lower bound must be non-negative")

    @property
    def label(self) -> str:
        return self.name or f"{self.entity_id}.{self.field}"

    def clip(self, value: float) -> float:
        return max(self.lower, min(self.upper, float(value)))

    def unit_to_value(self, u: float) -> float:
        """Map u∈[0,1] onto [lower, upper] in log-space when span > 0."""
        u = max(0.0, min(1.0, u))
        if self.lower <= 0.0:
            return self.lower + u * (self.upper - self.lower)
        log_lo = math.log(self.lower)
        log_hi = math.log(self.upper)
        return math.exp(log_lo + u * (log_hi - log_lo))

    def value_to_unit(self, value: float) -> float:
        v = self.clip(value)
        if self.lower <= 0.0:
            return (v - self.lower) / (self.upper - self.lower)
        log_lo = math.log(self.lower)
        log_hi = math.log(self.upper)
        if abs(log_hi - log_lo) < 1e-15:
            return 0.0
        return (math.log(v) - log_lo) / (log_hi - log_lo)


def discover_parameters(
    network: SignalingNetwork,
    *,
    fields: Sequence[str] = ("vmax", "km"),
    entity_ids: Optional[Sequence[str]] = None,
    relative_span: float = 0.5,
    min_lower: float = 1e-6,
) -> List[ParameterSpec]:
    """
    Auto-build specs centred on current kinetics with ±``relative_span`` log span.
    """
    if relative_span <= 0.0 or relative_span >= 1.0:
        raise ValueError("relative_span must be in (0, 1)")
    specs: List[ParameterSpec] = []
    targets = list(entity_ids) if entity_ids is not None else list(network.nodes())
    for eid in targets:
        if eid not in network.registry:
            continue
        ent = network.registry.get(eid)
        for fname in fields:
            base = float(getattr(ent.kinetics, fname, 0.0))
            if base <= 0.0:
                continue
            lo = max(min_lower, base * (1.0 - relative_span))
            hi = base * (1.0 + relative_span)
            if hi <= lo:
                hi = lo * 1.5
            specs.append(
                ParameterSpec(
                    entity_id=eid,
                    field=fname,
                    lower=lo,
                    upper=hi,
                    name=f"{ent.name}.{fname}",
                )
            )
    return specs


def _set_params(network: SignalingNetwork, specs: Sequence[ParameterSpec], values: Sequence[float]) -> None:
    if len(specs) != len(values):
        raise ValueError("specs/values length mismatch")
    for spec, val in zip(specs, values):
        if spec.entity_id not in network.registry:
            continue
        ent = network.registry.get(spec.entity_id)
        was = ent.locked
        ent.locked = False
        ent.kinetics = ent.kinetics.with_updates(**{spec.field: spec.clip(val)})
        ent.locked = was


def _run_with_params(
    network_payload: Dict[str, Any],
    config: SimulationConfig,
    specs: Sequence[ParameterSpec],
    values: Sequence[float],
) -> TrajectoryResult:
    net = deserialize_network(network_payload)
    _set_params(net, specs, values)
    return DualEngineSimulator(net).run_ode(config)


def scalar_output(
    traj: TrajectoryResult,
    entity_id: str,
    *,
    mode: str = "final",
    burn_in_frac: float = 0.5,
) -> float:
    """Reduce a trajectory to a scalar QoI."""
    series = traj.series(entity_id)
    if not series:
        return 0.0
    if mode == "final":
        return float(series[-1])
    if mode == "mean":
        n = max(1, int(math.ceil(len(series) * (1.0 - burn_in_frac))))
        window = series[-n:]
        return sum(window) / len(window)
    if mode == "auc":
        times = traj.times
        if len(times) < 2:
            return float(series[-1])
        acc = 0.0
        for i in range(1, min(len(times), len(series))):
            acc += 0.5 * (series[i] + series[i - 1]) * (times[i] - times[i - 1])
        return acc
    raise ValueError("mode must be final|mean|auc")


# ---------------------------------------------------------------------------
# Local sensitivity
# ---------------------------------------------------------------------------


@dataclass
class LocalSensitivityResult:
    parameters: List[str]
    outputs: List[str]
    matrix: List[List[float]]
    """matrix[output_idx][param_idx] = ∂Y/∂k (absolute)."""
    normalized: List[List[float]]
    """Elasticity (k/Y)·∂Y/∂k when Y≠0."""
    nominal_outputs: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "parameters": list(self.parameters),
            "outputs": list(self.outputs),
            "matrix": [row[:] for row in self.matrix],
            "normalized": [row[:] for row in self.normalized],
            "nominal_outputs": dict(self.nominal_outputs),
            "metadata": dict(self.metadata),
        }


class LocalSensitivityAnalyzer:
    """Centred finite-difference local sensitivity at the nominal kinetics."""

    def __init__(
        self,
        network: SignalingNetwork,
        specs: Sequence[ParameterSpec],
        *,
        config: Optional[SimulationConfig] = None,
        relative_step: float = 1e-3,
    ) -> None:
        self.network_payload = serialize_network(network)
        self.specs = list(specs)
        self.config = config or SimulationConfig(t_end=15.0, dt=0.2, record_every=10)
        if relative_step <= 0.0:
            raise ValueError("relative_step must be positive")
        self.relative_step = relative_step

    def _nominal_values(self) -> List[float]:
        net = deserialize_network(self.network_payload)
        vals = []
        for spec in self.specs:
            ent = net.registry.get(spec.entity_id)
            vals.append(float(getattr(ent.kinetics, spec.field)))
        return vals

    def analyze(
        self,
        output_ids: Sequence[str],
        *,
        mode: str = "final",
    ) -> LocalSensitivityResult:
        nominal = self._nominal_values()
        y0_traj = _run_with_params(self.network_payload, self.config, self.specs, nominal)
        y0 = {oid: scalar_output(y0_traj, oid, mode=mode) for oid in output_ids}

        matrix = [[0.0 for _ in self.specs] for _ in output_ids]
        normalized = [[0.0 for _ in self.specs] for _ in output_ids]

        for j, spec in enumerate(self.specs):
            k = nominal[j]
            step = max(abs(k) * self.relative_step, 1e-9)
            plus = list(nominal)
            minus = list(nominal)
            plus[j] = spec.clip(k + step)
            minus[j] = spec.clip(k - step)
            # Actual step after clipping
            dk = plus[j] - minus[j]
            if abs(dk) < 1e-15:
                continue
            yp = _run_with_params(self.network_payload, self.config, self.specs, plus)
            ym = _run_with_params(self.network_payload, self.config, self.specs, minus)
            for i, oid in enumerate(output_ids):
                dy = scalar_output(yp, oid, mode=mode) - scalar_output(ym, oid, mode=mode)
                s = dy / dk
                matrix[i][j] = s
                ynom = y0[oid]
                if abs(ynom) > 1e-15 and abs(k) > 1e-15:
                    normalized[i][j] = s * (k / ynom)
                else:
                    normalized[i][j] = 0.0

        return LocalSensitivityResult(
            parameters=[s.label for s in self.specs],
            outputs=list(output_ids),
            matrix=matrix,
            normalized=normalized,
            nominal_outputs=y0,
            metadata={"relative_step": self.relative_step, "mode": mode},
        )


# ---------------------------------------------------------------------------
# Morris elementary effects
# ---------------------------------------------------------------------------


@dataclass
class MorrisResult:
    parameters: List[str]
    mu: List[float]
    mu_star: List[float]
    sigma: List[float]
    n_trajectories: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        rows = []
        for i, name in enumerate(self.parameters):
            rows.append(
                {
                    "parameter": name,
                    "mu": self.mu[i],
                    "mu_star": self.mu_star[i],
                    "sigma": self.sigma[i],
                }
            )
        rows.sort(key=lambda r: r["mu_star"], reverse=True)
        return {
            "n_trajectories": self.n_trajectories,
            "ranking": rows,
            "metadata": dict(self.metadata),
        }


class MorrisAnalyzer:
    """
    Morris screening: r trajectories of length k+1 on a p-level grid.

    Elementary effect for parameter j::

        EE_j = (Y(x + Δ e_j) − Y(x)) / Δ
    """

    def __init__(
        self,
        network: SignalingNetwork,
        specs: Sequence[ParameterSpec],
        *,
        config: Optional[SimulationConfig] = None,
        levels: int = 8,
        seed: int = 0,
    ) -> None:
        self.network_payload = serialize_network(network)
        self.specs = list(specs)
        self.config = config or SimulationConfig(t_end=15.0, dt=0.2, record_every=10)
        if levels < 4:
            raise ValueError("levels must be ≥ 4")
        self.levels = levels
        self.seed = seed

    def analyze(
        self,
        output_id: str,
        *,
        n_trajectories: int = 10,
        mode: str = "final",
    ) -> MorrisResult:
        if n_trajectories < 1:
            raise ValueError("n_trajectories must be ≥ 1")
        k = len(self.specs)
        if k == 0:
            return MorrisResult([], [], [], [], 0)

        rng = random.Random(self.seed)
        # Grid step Δ = levels / (2*(levels-1)) in unit space (classic Morris)
        delta = self.levels / (2.0 * (self.levels - 1))
        ees: List[List[float]] = [[] for _ in range(k)]

        for _ in range(n_trajectories):
            # Start on grid in [0, 1-Δ]
            x = []
            for _j in range(k):
                # discrete levels 0..levels-1 mapped to unit, then clamp so x+Δ≤1
                max_idx = self.levels - 2
                idx = rng.randint(0, max(0, max_idx))
                x.append(idx / (self.levels - 1))
            # Random permutation of parameter order
            order = list(range(k))
            rng.shuffle(order)
            values = [self.specs[j].unit_to_value(x[j]) for j in range(k)]
            y_prev = scalar_output(
                _run_with_params(self.network_payload, self.config, self.specs, values),
                output_id,
                mode=mode,
            )
            for j in order:
                x_new = list(x)
                x_new[j] = min(1.0, x[j] + delta)
                values_new = [self.specs[i].unit_to_value(x_new[i]) for i in range(k)]
                y_new = scalar_output(
                    _run_with_params(self.network_payload, self.config, self.specs, values_new),
                    output_id,
                    mode=mode,
                )
                # Δ in value space
                v0 = self.specs[j].unit_to_value(x[j])
                v1 = self.specs[j].unit_to_value(x_new[j])
                dv = v1 - v0
                ee = (y_new - y_prev) / dv if abs(dv) > 1e-15 else 0.0
                ees[j].append(ee)
                x = x_new
                y_prev = y_new

        mu, mu_star, sigma = [], [], []
        for j in range(k):
            samples = ees[j]
            if not samples:
                mu.append(0.0)
                mu_star.append(0.0)
                sigma.append(0.0)
                continue
            m = sum(samples) / len(samples)
            ms = sum(abs(e) for e in samples) / len(samples)
            var = sum((e - m) ** 2 for e in samples) / max(len(samples) - 1, 1)
            mu.append(m)
            mu_star.append(ms)
            sigma.append(math.sqrt(max(var, 0.0)))

        return MorrisResult(
            parameters=[s.label for s in self.specs],
            mu=mu,
            mu_star=mu_star,
            sigma=sigma,
            n_trajectories=n_trajectories,
            metadata={"levels": self.levels, "delta_unit": delta, "output_id": output_id, "mode": mode},
        )


# ---------------------------------------------------------------------------
# Sobol-style variance decomposition
# ---------------------------------------------------------------------------


@dataclass
class SobolResult:
    parameters: List[str]
    first_order: List[float]
    total_order: List[float]
    output_variance: float
    n_base: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        rows = []
        for i, name in enumerate(self.parameters):
            rows.append(
                {
                    "parameter": name,
                    "S1": self.first_order[i],
                    "ST": self.total_order[i],
                }
            )
        rows.sort(key=lambda r: r["ST"], reverse=True)
        return {
            "output_variance": self.output_variance,
            "n_base": self.n_base,
            "ranking": rows,
            "metadata": dict(self.metadata),
        }


def _sobol_matrices(
    specs: Sequence[ParameterSpec],
    n: int,
    rng: random.Random,
) -> Tuple[List[List[float]], List[List[float]]]:
    """Return A, B as n×k matrices of physical parameter values."""
    k = len(specs)
    A, B = [], []
    for _ in range(n):
        A.append([specs[j].unit_to_value(rng.random()) for j in range(k)])
        B.append([specs[j].unit_to_value(rng.random()) for j in range(k)])
    return A, B


class SobolAnalyzer:
    """
    Saltelli-style first-order (S1) and total-effect (ST) indices.

    Uses N(k+2) model evaluations: Y_A, Y_B, and Y_{A_B^{(j)}} for each j.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        specs: Sequence[ParameterSpec],
        *,
        config: Optional[SimulationConfig] = None,
        seed: int = 0,
    ) -> None:
        self.network_payload = serialize_network(network)
        self.specs = list(specs)
        self.config = config or SimulationConfig(t_end=15.0, dt=0.2, record_every=10)
        self.seed = seed

    def analyze(
        self,
        output_id: str,
        *,
        n_base: int = 32,
        mode: str = "final",
    ) -> SobolResult:
        k = len(self.specs)
        if k == 0:
            return SobolResult([], [], [], 0.0, n_base)
        if n_base < 4:
            raise ValueError("n_base must be ≥ 4")

        rng = random.Random(self.seed)
        A, B = _sobol_matrices(self.specs, n_base, rng)

        def eval_rows(rows: Sequence[Sequence[float]]) -> List[float]:
            out = []
            for vals in rows:
                traj = _run_with_params(self.network_payload, self.config, self.specs, vals)
                out.append(scalar_output(traj, output_id, mode=mode))
            return out

        y_a = eval_rows(A)
        y_b = eval_rows(B)

        # Total variance from pooled A∪B
        pooled = y_a + y_b
        mu = sum(pooled) / len(pooled)
        var_y = sum((y - mu) ** 2 for y in pooled) / max(len(pooled) - 1, 1)
        if var_y < 1e-18:
            return SobolResult(
                [s.label for s in self.specs],
                [0.0] * k,
                [0.0] * k,
                0.0,
                n_base,
                metadata={"note": "near-zero output variance", "mode": mode},
            )

        s1 = [0.0] * k
        st = [0.0] * k
        for j in range(k):
            # A_B^(j): all from A except j-th from B
            ab = []
            for i in range(n_base):
                row = list(A[i])
                row[j] = B[i][j]
                ab.append(row)
            y_ab = eval_rows(ab)
            # First-order: V_j ≈ (1/N) Σ Y_B (Y_{A_B^j} − Y_A)  (Saltelli 2010 variant)
            # Using Jansen estimators for numerical stability:
            # ST_j = (1/(2N)) Σ (Y_A − Y_{A_B^j})² / Var
            # S1_j = Var − (1/(2N)) Σ (Y_B − Y_{A_B^j})²  all / Var
            st_num = sum((y_a[i] - y_ab[i]) ** 2 for i in range(n_base)) / (2.0 * n_base)
            s1_num = var_y - sum((y_b[i] - y_ab[i]) ** 2 for i in range(n_base)) / (2.0 * n_base)
            st[j] = max(0.0, min(1.5, st_num / var_y))
            s1[j] = max(0.0, min(1.5, s1_num / var_y))

        return SobolResult(
            parameters=[s.label for s in self.specs],
            first_order=s1,
            total_order=st,
            output_variance=var_y,
            n_base=n_base,
            metadata={"mode": mode, "output_id": output_id, "seed": self.seed},
        )


class SensitivityEngine:
    """Facade over local, Morris, and Sobol analyzers."""

    def __init__(
        self,
        network: SignalingNetwork,
        specs: Optional[Sequence[ParameterSpec]] = None,
        *,
        config: Optional[SimulationConfig] = None,
    ) -> None:
        self.network = network
        self.specs = list(specs) if specs is not None else discover_parameters(network)
        self.config = config or SimulationConfig(t_end=15.0, dt=0.2, record_every=10)

    def local(self, output_ids: Sequence[str], **kwargs: Any) -> LocalSensitivityResult:
        return LocalSensitivityAnalyzer(
            self.network, self.specs, config=self.config
        ).analyze(output_ids, **kwargs)

    def morris(self, output_id: str, **kwargs: Any) -> MorrisResult:
        return MorrisAnalyzer(
            self.network, self.specs, config=self.config, seed=int(kwargs.pop("seed", 0))
        ).analyze(output_id, **kwargs)

    def sobol(self, output_id: str, **kwargs: Any) -> SobolResult:
        return SobolAnalyzer(
            self.network, self.specs, config=self.config, seed=int(kwargs.pop("seed", 0))
        ).analyze(output_id, **kwargs)
