"""
Parameter estimation & optimization for CISTRON Phase 8.

Pure-Python solvers that fit kinetic rate parameters to target trajectory
data (experimental or simulated time series):

* Nelder–Mead simplex
* Levenberg–Marquardt (damped Gauss–Newton for least squares)
* Differential evolution (global stochastic search)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import logging
import math
import random

from cistron.sensitivity import ParameterSpec, _run_with_params, _set_params
from cistron.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from cistron.storage import deserialize_network, serialize_network
from cistron.topology import SignalingNetwork

logger = logging.getLogger(__name__)

ObjectiveFn = Callable[[Sequence[float]], float]


# ---------------------------------------------------------------------------
# Residuals / loss
# ---------------------------------------------------------------------------


@dataclass
class FitTarget:
    """Observed concentration series for one entity."""

    entity_id: str
    times: List[float]
    values: List[float]
    weight: float = 1.0

    def __post_init__(self) -> None:
        if len(self.times) != len(self.values):
            raise ValueError("FitTarget times/values length mismatch")
        if self.weight < 0.0:
            raise ValueError("weight must be non-negative")
        if any(t != t or v != v for t, v in zip(self.times, self.values)):  # NaN check
            raise ValueError("FitTarget contains NaN")


def interpolate_series(
    times: Sequence[float],
    values: Sequence[float],
    query_t: float,
) -> float:
    """Piecewise-linear interpolation; clamps outside the window."""
    if not times:
        return 0.0
    if query_t <= times[0]:
        return float(values[0])
    if query_t >= times[-1]:
        return float(values[-1])
    for i in range(1, len(times)):
        if times[i] >= query_t:
            t0, t1 = times[i - 1], times[i]
            v0, v1 = values[i - 1], values[i]
            if abs(t1 - t0) < 1e-15:
                return float(v1)
            w = (query_t - t0) / (t1 - t0)
            return float(v0 * (1.0 - w) + v1 * w)
    return float(values[-1])


def trajectory_from_targets(targets: Sequence[FitTarget]) -> Dict[str, FitTarget]:
    return {t.entity_id: t for t in targets}


class TrajectoryLoss:
    """
    Weighted SSE between simulated trajectories and :class:`FitTarget` panels.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        specs: Sequence[ParameterSpec],
        targets: Sequence[FitTarget],
        *,
        config: Optional[SimulationConfig] = None,
    ) -> None:
        self.network_payload = serialize_network(network)
        self.specs = list(specs)
        self.targets = list(targets)
        self.config = config or SimulationConfig(t_end=20.0, dt=0.2, record_every=5)
        if not self.specs:
            raise ValueError("specs must be non-empty")
        if not self.targets:
            raise ValueError("targets must be non-empty")

    def residuals(self, values: Sequence[float]) -> List[float]:
        clipped = [spec.clip(v) for spec, v in zip(self.specs, values)]
        traj = _run_with_params(self.network_payload, self.config, self.specs, clipped)
        res: List[float] = []
        for target in self.targets:
            sim_series = traj.series(target.entity_id)
            sim_times = traj.times
            w = math.sqrt(max(target.weight, 0.0))
            for t_obs, y_obs in zip(target.times, target.values):
                y_hat = interpolate_series(sim_times, sim_series, t_obs) if sim_series else 0.0
                res.append(w * (y_hat - y_obs))
        return res

    def __call__(self, values: Sequence[float]) -> float:
        res = self.residuals(values)
        return sum(r * r for r in res)

    def nominal_values(self) -> List[float]:
        net = deserialize_network(self.network_payload)
        out = []
        for spec in self.specs:
            ent = net.registry.get(spec.entity_id)
            out.append(float(getattr(ent.kinetics, spec.field)))
        return out


# ---------------------------------------------------------------------------
# Nelder–Mead
# ---------------------------------------------------------------------------


@dataclass
class OptimizeResult:
    x: List[float]
    fun: float
    nit: int
    nfev: int
    success: bool
    message: str
    method: str
    history: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "x": list(self.x),
            "fun": self.fun,
            "nit": self.nit,
            "nfev": self.nfev,
            "success": self.success,
            "message": self.message,
            "method": self.method,
            "history": list(self.history),
            "metadata": dict(self.metadata),
        }


def nelder_mead(
    objective: ObjectiveFn,
    x0: Sequence[float],
    *,
    bounds: Optional[Sequence[Tuple[float, float]]] = None,
    max_iter: int = 200,
    fatol: float = 1e-8,
    xatol: float = 1e-6,
    adaptive: bool = True,
) -> OptimizeResult:
    """
    Nelder–Mead simplex minimization with optional box bounds (projection).
    """
    n = len(x0)
    if n < 1:
        raise ValueError("x0 must be non-empty")

    def project(x: List[float]) -> List[float]:
        if bounds is None:
            return x
        out = []
        for i, v in enumerate(x):
            lo, hi = bounds[i]
            out.append(max(lo, min(hi, v)))
        return out

    # Standard / adaptive coefficients
    if adaptive and n >= 1:
        alpha, gamma, rho, sigma = 1.0, 1.0 + 2.0 / n, 0.75 - 1.0 / (2.0 * n), 1.0 - 1.0 / n
    else:
        alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5

    # Initial simplex
    simplex = [project(list(x0))]
    for i in range(n):
        y = list(x0)
        step = 0.05 * abs(y[i]) if abs(y[i]) > 1e-8 else 0.05
        y[i] += step
        simplex.append(project(y))

    scores = [float(objective(p)) for p in simplex]
    nfev = len(scores)
    history = [min(scores)]

    for it in range(max_iter):
        order = sorted(range(n + 1), key=lambda i: scores[i])
        simplex = [simplex[i] for i in order]
        scores = [scores[i] for i in order]
        best, worst = scores[0], scores[-1]
        history.append(best)

        # Convergence: score spread and simplex size
        if abs(worst - best) < fatol:
            return OptimizeResult(
                project(simplex[0]), best, it + 1, nfev, True, "fatol reached", "nelder_mead", history
            )
        size = 0.0
        for i in range(1, n + 1):
            size += math.sqrt(sum((simplex[i][j] - simplex[0][j]) ** 2 for j in range(n)))
        if size / n < xatol:
            return OptimizeResult(
                project(simplex[0]), best, it + 1, nfev, True, "xatol reached", "nelder_mead", history
            )

        # Centroid of all but worst
        centroid = [0.0] * n
        for i in range(n):
            for j in range(n):
                centroid[j] += simplex[i][j]
        centroid = [c / n for c in centroid]

        # Reflect
        reflected = project([centroid[j] + alpha * (centroid[j] - simplex[-1][j]) for j in range(n)])
        f_r = float(objective(reflected))
        nfev += 1

        if scores[0] <= f_r < scores[-2]:
            simplex[-1] = reflected
            scores[-1] = f_r
            continue

        # Expand
        if f_r < scores[0]:
            expanded = project([centroid[j] + gamma * (reflected[j] - centroid[j]) for j in range(n)])
            f_e = float(objective(expanded))
            nfev += 1
            if f_e < f_r:
                simplex[-1] = expanded
                scores[-1] = f_e
            else:
                simplex[-1] = reflected
                scores[-1] = f_r
            continue

        # Contract
        contracted = project([centroid[j] + rho * (simplex[-1][j] - centroid[j]) for j in range(n)])
        f_c = float(objective(contracted))
        nfev += 1
        if f_c < scores[-1]:
            simplex[-1] = contracted
            scores[-1] = f_c
            continue

        # Shrink toward best
        for i in range(1, n + 1):
            simplex[i] = project(
                [simplex[0][j] + sigma * (simplex[i][j] - simplex[0][j]) for j in range(n)]
            )
            scores[i] = float(objective(simplex[i]))
            nfev += 1

    order = sorted(range(n + 1), key=lambda i: scores[i])
    return OptimizeResult(
        project(simplex[order[0]]),
        scores[order[0]],
        max_iter,
        nfev,
        False,
        "max_iter reached",
        "nelder_mead",
        history,
    )


# ---------------------------------------------------------------------------
# Levenberg–Marquardt
# ---------------------------------------------------------------------------


def levenberg_marquardt(
    residuals_fn: Callable[[Sequence[float]], List[float]],
    x0: Sequence[float],
    *,
    bounds: Optional[Sequence[Tuple[float, float]]] = None,
    max_iter: int = 50,
    ftol: float = 1e-8,
    step: float = 1e-4,
    lambda0: float = 1e-2,
) -> OptimizeResult:
    """
    Damped Gauss–Newton / Levenberg–Marquardt for nonlinear least squares.

    Jacobian via forward finite differences.
    """
    n = len(x0)

    def project(x: List[float]) -> List[float]:
        if bounds is None:
            return x
        return [max(bounds[i][0], min(bounds[i][1], x[i])) for i in range(n)]

    def sse(x: Sequence[float]) -> Tuple[float, List[float]]:
        r = residuals_fn(x)
        return sum(v * v for v in r), r

    x = project(list(x0))
    f, r = sse(x)
    nfev = 1
    lam = lambda0
    history = [f]
    m = len(r)

    for it in range(max_iter):
        # Jacobian m×n
        J = [[0.0 for _ in range(n)] for _ in range(m)]
        for j in range(n):
            xj = list(x)
            h = step * max(abs(xj[j]), 1.0)
            xj[j] = xj[j] + h
            xj = project(xj)
            h_eff = xj[j] - x[j]
            if abs(h_eff) < 1e-15:
                continue
            _, rj = sse(xj)
            nfev += 1
            for i in range(m):
                J[i][j] = (rj[i] - r[i]) / h_eff

        # JᵀJ + λ diag(JᵀJ) and Jᵀr
        jtj = [[0.0 for _ in range(n)] for _ in range(n)]
        jtr = [0.0] * n
        for i in range(m):
            for a in range(n):
                jtr[a] += J[i][a] * r[i]
                for b in range(n):
                    jtj[a][b] += J[i][a] * J[i][b]
        for a in range(n):
            jtj[a][a] *= 1.0 + lam
            jtj[a][a] += 1e-12

        # Solve (JᵀJ+λI) δ = -Jᵀr via Gaussian elimination
        delta = _solve_linear(jtj, [-v for v in jtr])
        if delta is None:
            lam *= 10.0
            continue

        x_trial = project([x[j] + delta[j] for j in range(n)])
        f_trial, r_trial = sse(x_trial)
        nfev += 1
        history.append(min(f, f_trial))

        if f_trial < f:
            # Accept
            gain = f - f_trial
            x, f, r = x_trial, f_trial, r_trial
            lam = max(lam * 0.3, 1e-10)
            if gain < ftol * max(1.0, f):
                return OptimizeResult(x, f, it + 1, nfev, True, "ftol reached", "levenberg_marquardt", history)
        else:
            lam = min(lam * 10.0, 1e8)

    return OptimizeResult(x, f, max_iter, nfev, False, "max_iter reached", "levenberg_marquardt", history)


def _solve_linear(a: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-15:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        piv = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= piv
        for row in range(n):
            if row == col:
                continue
            factor = m[row][col]
            for j in range(col, n + 1):
                m[row][j] -= factor * m[col][j]
    return [m[i][n] for i in range(n)]


# ---------------------------------------------------------------------------
# Differential evolution
# ---------------------------------------------------------------------------


def differential_evolution(
    objective: ObjectiveFn,
    bounds: Sequence[Tuple[float, float]],
    *,
    max_iter: int = 40,
    popsize: int = 12,
    mutation: float = 0.7,
    recombination: float = 0.9,
    seed: int = 0,
) -> OptimizeResult:
    """Simple /DE/rand/1/bin evolutionary optimizer."""
    n = len(bounds)
    if n < 1:
        raise ValueError("bounds must be non-empty")
    rng = random.Random(seed)
    pop_n = max(popsize, 5)
    # Init population
    pop = []
    for _ in range(pop_n):
        pop.append([bounds[j][0] + rng.random() * (bounds[j][1] - bounds[j][0]) for j in range(n)])
    fitness = [float(objective(ind)) for ind in pop]
    nfev = len(fitness)
    history = [min(fitness)]

    for it in range(max_iter):
        for i in range(pop_n):
            idxs = list(range(pop_n))
            idxs.remove(i)
            a, b, c = (pop[k] for k in rng.sample(idxs, 3))
            mutant = []
            for j in range(n):
                v = a[j] + mutation * (b[j] - c[j])
                v = max(bounds[j][0], min(bounds[j][1], v))
                mutant.append(v)
            trial = []
            j_rand = rng.randrange(n)
            for j in range(n):
                if rng.random() < recombination or j == j_rand:
                    trial.append(mutant[j])
                else:
                    trial.append(pop[i][j])
            f_trial = float(objective(trial))
            nfev += 1
            if f_trial <= fitness[i]:
                pop[i] = trial
                fitness[i] = f_trial
        history.append(min(fitness))

    best_i = min(range(pop_n), key=lambda i: fitness[i])
    return OptimizeResult(
        pop[best_i],
        fitness[best_i],
        max_iter,
        nfev,
        True,
        "completed",
        "differential_evolution",
        history,
        metadata={"popsize": pop_n},
    )


# ---------------------------------------------------------------------------
# High-level estimator
# ---------------------------------------------------------------------------


class ParameterEstimator:
    """
    Fit :class:`ParameterSpec` values so simulated trajectories match targets.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        specs: Sequence[ParameterSpec],
        targets: Sequence[FitTarget],
        *,
        config: Optional[SimulationConfig] = None,
    ) -> None:
        self.loss = TrajectoryLoss(network, specs, targets, config=config)
        self.specs = list(specs)
        self.bounds = [(s.lower, s.upper) for s in self.specs]

    def fit(
        self,
        *,
        method: str = "nelder_mead",
        x0: Optional[Sequence[float]] = None,
        **kwargs: Any,
    ) -> OptimizeResult:
        start = list(x0) if x0 is not None else self.loss.nominal_values()
        start = [spec.clip(v) for spec, v in zip(self.specs, start)]

        if method == "nelder_mead":
            result = nelder_mead(self.loss, start, bounds=self.bounds, **{
                k: kwargs[k] for k in ("max_iter", "fatol", "xatol", "adaptive") if k in kwargs
            })
        elif method in {"levenberg_marquardt", "lm"}:
            result = levenberg_marquardt(
                self.loss.residuals,
                start,
                bounds=self.bounds,
                **{k: kwargs[k] for k in ("max_iter", "ftol", "step", "lambda0") if k in kwargs},
            )
        elif method in {"differential_evolution", "de"}:
            result = differential_evolution(
                self.loss,
                self.bounds,
                **{k: kwargs[k] for k in ("max_iter", "popsize", "mutation", "recombination", "seed") if k in kwargs},
            )
        else:
            raise ValueError("method must be nelder_mead|levenberg_marquardt|differential_evolution")

        result.metadata["parameter_labels"] = [s.label for s in self.specs]
        result.metadata["fitted"] = {
            self.specs[i].label: result.x[i] for i in range(len(self.specs))
        }
        return result

    def apply_result(self, network: SignalingNetwork, result: OptimizeResult) -> SignalingNetwork:
        """Write fitted parameters onto ``network`` in-place and return it."""
        _set_params(network, self.specs, result.x)
        return network
