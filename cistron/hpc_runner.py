"""
Parallel ensemble & Monte Carlo simulation for CISTRON Phase 8.

:class:`EnsembleRunner` executes many :class:`~cistron.simulation.DualEngineSimulator`
ODE runs via ``concurrent.futures`` process or thread pools, returning aggregated
confidence bands across time.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import logging
import math
import os
import random

from cistron.components import KineticParameters
from cistron.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from cistron.storage import deserialize_network, serialize_network
from cistron.topology import SignalingNetwork

logger = logging.getLogger(__name__)

ExecutorKind = str  # "process" | "thread" | "serial"


# ---------------------------------------------------------------------------
# Job payload (pickle-safe)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterDraw:
    """One kinetic override applied before a member run."""

    entity_id: str
    field: str
    value: float


@dataclass
class EnsembleMemberSpec:
    """Serializable description of one Monte Carlo member."""

    member_id: int
    seed: int
    initial_noise_sigma: float = 0.0
    lognormal_param_sigma: float = 0.0
    param_fields: Tuple[str, ...] = ("vmax", "km", "production_rate", "degradation_rate")
    entity_ids: Optional[Tuple[str, ...]] = None
    """If set, only these entities are randomized."""
    fixed_overrides: Tuple[ParameterDraw, ...] = ()


@dataclass
class EnsembleJob:
    network_payload: Dict[str, Any]
    config: Dict[str, Any]
    member: EnsembleMemberSpec


def _config_to_dict(cfg: SimulationConfig) -> Dict[str, Any]:
    return {
        "t_start": cfg.t_start,
        "t_end": cfg.t_end,
        "dt": cfg.dt,
        "record_every": cfg.record_every,
        "clamp_nonnegative": cfg.clamp_nonnegative,
        "stepper": cfg.stepper.value if hasattr(cfg.stepper, "value") else str(cfg.stepper),
        "sync_threshold": cfg.sync_threshold,
        "relative_tolerance": cfg.relative_tolerance,
        "absolute_tolerance": cfg.absolute_tolerance,
        "min_dt": cfg.min_dt,
        "max_dt": cfg.max_dt,
    }


def _config_from_dict(d: Mapping[str, Any]) -> SimulationConfig:
    from cistron.simulation import ODEStepper

    stepper_raw = d.get("stepper", "rk4")
    try:
        stepper = ODEStepper(stepper_raw)
    except Exception:
        stepper = ODEStepper.RK4
    return SimulationConfig(
        t_start=float(d.get("t_start", 0.0)),
        t_end=float(d.get("t_end", 100.0)),
        dt=float(d.get("dt", 0.1)),
        record_every=int(d.get("record_every", 1)),
        clamp_nonnegative=bool(d.get("clamp_nonnegative", True)),
        stepper=stepper,
        sync_threshold=float(d.get("sync_threshold", 0.5)),
        relative_tolerance=float(d.get("relative_tolerance", 1e-4)),
        absolute_tolerance=float(d.get("absolute_tolerance", 1e-7)),
        min_dt=float(d.get("min_dt", 1e-6)),
        max_dt=float(d.get("max_dt", 1.0)),
    )


def _apply_lognormal_noise(
    network: SignalingNetwork,
    rng: random.Random,
    *,
    sigma: float,
    fields: Sequence[str],
    entity_ids: Optional[Sequence[str]],
) -> List[ParameterDraw]:
    draws: List[ParameterDraw] = []
    if sigma <= 0.0:
        return draws
    targets = list(entity_ids) if entity_ids is not None else list(network.nodes())
    for eid in targets:
        if eid not in network.registry:
            continue
        ent = network.registry.get(eid)
        k = ent.kinetics
        updates: Dict[str, float] = {}
        for fname in fields:
            base = float(getattr(k, fname, 0.0))
            if base <= 0.0:
                continue
            val = base * math.exp(rng.gauss(0.0, sigma))
            val = max(1e-12, val)
            updates[fname] = val
            draws.append(ParameterDraw(eid, fname, val))
        if updates:
            was = ent.locked
            ent.locked = False
            ent.kinetics = k.with_updates(**updates)
            ent.locked = was
    return draws


def _apply_ic_noise(
    network: SignalingNetwork,
    rng: random.Random,
    *,
    sigma: float,
    entity_ids: Optional[Sequence[str]],
) -> None:
    if sigma <= 0.0:
        return
    targets = list(entity_ids) if entity_ids is not None else list(network.nodes())
    for eid in targets:
        if eid not in network.registry:
            continue
        ent = network.registry.get(eid)
        if ent.locked:
            continue
        c = max(0.0, ent.concentration)
        # multiplicative lognormal on positive IC; additive epsilon on zeros
        if c > 0.0:
            new_c = c * math.exp(rng.gauss(0.0, sigma))
        else:
            new_c = max(0.0, rng.gauss(0.0, sigma) * 0.01)
        ent.set_concentration(max(0.0, new_c))


def _apply_fixed_overrides(network: SignalingNetwork, overrides: Sequence[ParameterDraw]) -> None:
    for draw in overrides:
        if draw.entity_id not in network.registry:
            continue
        ent = network.registry.get(draw.entity_id)
        was = ent.locked
        ent.locked = False
        ent.kinetics = ent.kinetics.with_updates(**{draw.field: max(0.0, float(draw.value))})
        ent.locked = was


def ensemble_worker(job: EnsembleJob) -> Dict[str, Any]:
    """
    Module-level worker for ProcessPoolExecutor (must be picklable on Windows).
    """
    network = deserialize_network(job.network_payload)
    cfg = _config_from_dict(job.config)
    member = job.member
    rng = random.Random(member.seed)

    _apply_fixed_overrides(network, member.fixed_overrides)
    draws = _apply_lognormal_noise(
        network,
        rng,
        sigma=member.lognormal_param_sigma,
        fields=member.param_fields,
        entity_ids=member.entity_ids,
    )
    _apply_ic_noise(
        network,
        rng,
        sigma=member.initial_noise_sigma,
        entity_ids=member.entity_ids,
    )

    traj = DualEngineSimulator(network).run_ode(cfg)
    # Compact payload: times + concentrations only
    return {
        "member_id": member.member_id,
        "seed": member.seed,
        "times": list(traj.times),
        "concentrations": [dict(s) for s in traj.concentrations],
        "draws": [{"entity_id": d.entity_id, "field": d.field, "value": d.value} for d in draws],
        "error": None,
    }


def ensemble_worker_safe(job: EnsembleJob) -> Dict[str, Any]:
    """Worker wrapper that captures exceptions into the result dict."""
    try:
        return ensemble_worker(job)
    except Exception as exc:  # pragma: no cover - defensive for pool
        return {
            "member_id": job.member.member_id,
            "seed": job.member.seed,
            "times": [],
            "concentrations": [],
            "draws": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class ConfidenceBand:
    """Per-entity time series with mean and percentile envelope."""

    entity_id: str
    times: List[float]
    mean: List[float]
    std: List[float]
    low: List[float]
    high: List[float]
    level: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "times": list(self.times),
            "mean": list(self.mean),
            "std": list(self.std),
            "low": list(self.low),
            "high": list(self.high),
            "level": self.level,
        }


@dataclass
class EnsembleResult:
    n_members: int
    n_success: int
    times: List[float]
    bands: Dict[str, ConfidenceBand]
    member_finals: List[Dict[str, float]]
    errors: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def band(self, entity_id: str) -> ConfidenceBand:
        return self.bands[entity_id]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_members": self.n_members,
            "n_success": self.n_success,
            "times": list(self.times),
            "bands": {k: v.as_dict() for k, v in self.bands.items()},
            "n_errors": len(self.errors),
            "metadata": dict(self.metadata),
        }


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    q = max(0.0, min(1.0, q))
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    w = pos - lo
    return sorted_vals[lo] * (1.0 - w) + sorted_vals[hi] * w


def aggregate_ensemble(
    members: Sequence[Mapping[str, Any]],
    *,
    level: float = 0.95,
) -> EnsembleResult:
    """
    Align members on the first successful time grid and build confidence bands.
    """
    ok = [m for m in members if not m.get("error") and m.get("times")]
    errors = [str(m.get("error")) for m in members if m.get("error")]
    if not ok:
        return EnsembleResult(
            n_members=len(members),
            n_success=0,
            times=[],
            bands={},
            member_finals=[],
            errors=errors,
        )

    times = list(ok[0]["times"])
    t_len = len(times)
    # Collect entity keys
    entity_ids = sorted(ok[0]["concentrations"][0].keys()) if ok[0]["concentrations"] else []

    bands: Dict[str, ConfidenceBand] = {}
    alpha = 1.0 - level
    lo_q, hi_q = alpha / 2.0, 1.0 - alpha / 2.0

    for eid in entity_ids:
        series_matrix: List[List[float]] = []
        for m in ok:
            conc = m["concentrations"]
            # Truncate / pad to reference length
            row = []
            for i in range(t_len):
                if i < len(conc):
                    row.append(float(conc[i].get(eid, 0.0)))
                else:
                    row.append(float(conc[-1].get(eid, 0.0)) if conc else 0.0)
            series_matrix.append(row)

        means: List[float] = []
        stds: List[float] = []
        lows: List[float] = []
        highs: List[float] = []
        n = len(series_matrix)
        for i in range(t_len):
            col = [series_matrix[j][i] for j in range(n)]
            mu = sum(col) / n
            var = sum((x - mu) ** 2 for x in col) / max(n - 1, 1)
            sd = math.sqrt(max(var, 0.0))
            ordered = sorted(col)
            means.append(mu)
            stds.append(sd)
            lows.append(_percentile(ordered, lo_q))
            highs.append(_percentile(ordered, hi_q))
        bands[eid] = ConfidenceBand(eid, times, means, stds, lows, highs, level)

    finals = [dict(m["concentrations"][-1]) for m in ok if m["concentrations"]]
    return EnsembleResult(
        n_members=len(members),
        n_success=len(ok),
        times=times,
        bands=bands,
        member_finals=finals,
        errors=errors,
        metadata={"level": level},
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class EnsembleRunner:
    """
    Multi-process / multi-thread / serial Monte Carlo ensemble executor.

    Parameters
    ----------
    network :
        Baseline signalling network (cloned per member via serialization).
    config :
        ODE integration settings shared by all members.
    max_workers :
        Pool size; defaults to ``min(32, os.cpu_count() or 1)``.
    executor :
        ``"process"`` (default), ``"thread"``, or ``"serial"``.
        Prefer ``process`` for CPU-bound ODE; use ``serial`` in constrained
        test environments.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        config: Optional[SimulationConfig] = None,
        *,
        max_workers: Optional[int] = None,
        executor: ExecutorKind = "process",
    ) -> None:
        self.network = network
        self.config = config or SimulationConfig(t_end=20.0, dt=0.2, record_every=5)
        self.max_workers = max_workers
        if executor not in {"process", "thread", "serial"}:
            raise ValueError("executor must be process|thread|serial")
        self.executor = executor
        self._network_payload = serialize_network(network)
        self._config_dict = _config_to_dict(self.config)

    def _workers(self) -> int:
        if self.max_workers is not None:
            return max(1, int(self.max_workers))
        return max(1, min(32, os.cpu_count() or 1))

    def build_jobs(
        self,
        n_members: int,
        *,
        seed: int = 0,
        initial_noise_sigma: float = 0.1,
        lognormal_param_sigma: float = 0.15,
        param_fields: Sequence[str] = ("vmax", "km", "production_rate", "degradation_rate"),
        entity_ids: Optional[Sequence[str]] = None,
        fixed_overrides: Optional[Sequence[ParameterDraw]] = None,
    ) -> List[EnsembleJob]:
        if n_members < 1:
            raise ValueError("n_members must be ≥ 1")
        ents = tuple(entity_ids) if entity_ids is not None else None
        fixed = tuple(fixed_overrides or ())
        jobs: List[EnsembleJob] = []
        for i in range(n_members):
            member = EnsembleMemberSpec(
                member_id=i,
                seed=seed + i * 10007,
                initial_noise_sigma=initial_noise_sigma,
                lognormal_param_sigma=lognormal_param_sigma,
                param_fields=tuple(param_fields),
                entity_ids=ents,
                fixed_overrides=fixed,
            )
            jobs.append(
                EnsembleJob(
                    network_payload=self._network_payload,
                    config=self._config_dict,
                    member=member,
                )
            )
        return jobs

    def run_jobs(self, jobs: Sequence[EnsembleJob]) -> List[Dict[str, Any]]:
        if self.executor == "serial" or len(jobs) == 1:
            return [ensemble_worker_safe(j) for j in jobs]

        workers = min(self._workers(), len(jobs))
        results: List[Optional[Dict[str, Any]]] = [None] * len(jobs)
        pool_cls = ProcessPoolExecutor if self.executor == "process" else ThreadPoolExecutor
        with pool_cls(max_workers=workers) as pool:
            futures = {pool.submit(ensemble_worker_safe, job): idx for idx, job in enumerate(jobs)}
            for fut in as_completed(futures):
                idx = futures[fut]
                results[idx] = fut.result()
        return [r if r is not None else {"error": "missing", "times": [], "concentrations": []} for r in results]

    def monte_carlo(
        self,
        n_members: int,
        *,
        seed: int = 0,
        initial_noise_sigma: float = 0.1,
        lognormal_param_sigma: float = 0.15,
        level: float = 0.95,
        **kwargs: Any,
    ) -> EnsembleResult:
        """
        Run ``n_members`` randomized trajectories and return confidence bands.
        """
        jobs = self.build_jobs(
            n_members,
            seed=seed,
            initial_noise_sigma=initial_noise_sigma,
            lognormal_param_sigma=lognormal_param_sigma,
            **{k: kwargs[k] for k in ("param_fields", "entity_ids", "fixed_overrides") if k in kwargs},
        )
        raw = self.run_jobs(jobs)
        result = aggregate_ensemble(raw, level=level)
        result.metadata.update(
            {
                "seed": seed,
                "initial_noise_sigma": initial_noise_sigma,
                "lognormal_param_sigma": lognormal_param_sigma,
                "executor": self.executor,
                "n_workers": self._workers(),
            }
        )
        return result
