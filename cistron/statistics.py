"""
Statistical verification engine for CISTRON Phase 6.

Pure-Python hypothesis testing, effect sizes, confidence intervals, and a
lightweight Bayesian-style kinetic parameter audit for steady-state stability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import logging
import math
import random

from cistron.components import KineticParameters, Protein
from cistron.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from cistron.topology import SignalingNetwork

logger = logging.getLogger(__name__)

NetworkFactory = Callable[[], SignalingNetwork]


# ---------------------------------------------------------------------------
# Safe descriptive stats
# ---------------------------------------------------------------------------


def _finite(xs: Iterable[float]) -> List[float]:
    out: List[float] = []
    for x in xs:
        try:
            v = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return out


def mean(xs: Sequence[float]) -> float:
    vals = _finite(xs)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def variance(xs: Sequence[float], *, sample: bool = True) -> float:
    vals = _finite(xs)
    n = len(vals)
    if n == 0:
        return 0.0
    if n == 1:
        return 0.0
    mu = sum(vals) / n
    ss = sum((x - mu) ** 2 for x in vals)
    denom = (n - 1) if sample else n
    return ss / denom if denom > 0 else 0.0


def std(xs: Sequence[float], *, sample: bool = True) -> float:
    return math.sqrt(max(variance(xs, sample=sample), 0.0))


def median(xs: Sequence[float]) -> float:
    vals = sorted(_finite(xs))
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


# ---------------------------------------------------------------------------
# Special functions (Abramowitz & Stegun approximations)
# ---------------------------------------------------------------------------


def _erf(x: float) -> float:
    # A&S 7.1.26
    sign = 1.0 if x >= 0 else -1.0
    ax = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-ax * ax)
    return sign * y


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + _erf(z / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Approximate inverse CDF of N(0,1) (Beasley–Springer–Moro style)."""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    if abs(p - 0.5) < 1e-15:
        return 0.0
    # Rational approximation for central region
    a = [ -3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
          1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00 ]
    b = [ -5.447590067507237e01, 1.615858368580577e02, -1.556989798598866e02,
          6.680131188771972e01, -1.328068155288572e01 ]
    c = [ -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
          -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00 ]
    d = [ 7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
          3.754408661907416e00 ]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)


def students_t_cdf(t: float, df: float) -> float:
    """
    Approximate two-sided building block: P(T ≤ t) for Student's t.

    Uses a normal approximation with df-correction for large df and a
    continued-fraction style regularised incomplete-beta transform for small df.
    """
    if df <= 0.0:
        return normal_cdf(t)
    if df > 1e6:
        return normal_cdf(t)
    # Regularised incomplete beta via continued fraction
    x = df / (df + t * t)
    # I_x(df/2, 1/2)
    a = 0.5 * df
    b = 0.5
    ib = _regularised_incomplete_beta(x, a, b) if 0.0 < x < 1.0 else (0.0 if x <= 0 else 1.0)
    if t >= 0.0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib


def _regularised_incomplete_beta(x: float, a: float, b: float) -> float:
    """Continued-fraction approx of Ix(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # Use symmetry
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularised_incomplete_beta(1.0 - x, b, a)
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(max(x, 1e-300)) * a + math.log(max(1.0 - x, 1e-300)) * b - ln_beta) / a
    # Lentz continued fraction
    tiny = 1e-30
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        # even step
        aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        # odd step
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return max(0.0, min(1.0, front * h))


# ---------------------------------------------------------------------------
# Effect sizes & tests
# ---------------------------------------------------------------------------


@dataclass
class EffectSize:
    cohens_d: float
    hedges_g: float
    interpretation: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cohens_d": self.cohens_d,
            "hedges_g": self.hedges_g,
            "interpretation": self.interpretation,
        }


def interpret_cohens_d(d: float) -> str:
    ad = abs(d)
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"


def cohens_d(control: Sequence[float], treated: Sequence[float]) -> EffectSize:
    """Pooled-SD Cohen's d with Hedges' small-sample correction."""
    a = _finite(control)
    b = _finite(treated)
    n1, n2 = len(a), len(b)
    if n1 < 1 or n2 < 1:
        return EffectSize(0.0, 0.0, "undefined")
    m1, m2 = mean(a), mean(b)
    s1, s2 = variance(a), variance(b)
    denom_n = n1 + n2 - 2
    if denom_n <= 0:
        pooled = 0.0
    else:
        pooled = math.sqrt(max(0.0, ((n1 - 1) * s1 + (n2 - 1) * s2) / denom_n))
    if pooled < 1e-15:
        d = 0.0 if abs(m2 - m1) < 1e-15 else (math.copysign(10.0, m2 - m1))
    else:
        d = (m2 - m1) / pooled
    # Hedges g
    df = max(n1 + n2 - 2, 1)
    j = 1.0 - 3.0 / (4.0 * df - 1.0) if df > 1 else 1.0
    g = d * j
    return EffectSize(cohens_d=d, hedges_g=g, interpretation=interpret_cohens_d(d))


@dataclass
class ConfidenceInterval:
    low: float
    high: float
    mean: float
    level: float
    n: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "mean": self.mean,
            "level": self.level,
            "n": self.n,
        }


def mean_confidence_interval(
    xs: Sequence[float],
    *,
    level: float = 0.95,
) -> ConfidenceInterval:
    """Normal/t hybrid CI for the mean; empty → (0,0)."""
    vals = _finite(xs)
    n = len(vals)
    if n == 0:
        return ConfidenceInterval(0.0, 0.0, 0.0, level, 0)
    mu = mean(vals)
    if n == 1:
        return ConfidenceInterval(mu, mu, mu, level, 1)
    s = std(vals)
    se = s / math.sqrt(n) if s > 0.0 else 0.0
    alpha = 1.0 - level
    # Use normal critical value (conservative for large n; fine for Phase-6)
    z = normal_ppf(1.0 - alpha / 2.0)
    if not math.isfinite(z):
        z = 1.96
    return ConfidenceInterval(mu - z * se, mu + z * se, mu, level, n)


@dataclass
class HypothesisTestResult:
    statistic: float
    p_value: float
    df: float
    test: str
    alternative: str
    effect: EffectSize
    control_ci: ConfidenceInterval
    treated_ci: ConfidenceInterval
    significant: bool
    alpha: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "statistic": self.statistic,
            "p_value": self.p_value,
            "df": self.df,
            "test": self.test,
            "alternative": self.alternative,
            "effect": self.effect.as_dict(),
            "control_ci": self.control_ci.as_dict(),
            "treated_ci": self.treated_ci.as_dict(),
            "significant": self.significant,
            "alpha": self.alpha,
        }


def welch_ttest(
    control: Sequence[float],
    treated: Sequence[float],
    *,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> HypothesisTestResult:
    """Welch's t-test for unequal variances."""
    a = _finite(control)
    b = _finite(treated)
    effect = cohens_d(a, b)
    ci_a = mean_confidence_interval(a)
    ci_b = mean_confidence_interval(b)
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return HypothesisTestResult(
            statistic=0.0,
            p_value=1.0,
            df=0.0,
            test="welch_t",
            alternative=alternative,
            effect=effect,
            control_ci=ci_a,
            treated_ci=ci_b,
            significant=False,
            alpha=alpha,
        )
    m1, m2 = mean(a), mean(b)
    v1, v2 = variance(a), variance(b)
    se2 = v1 / n1 + v2 / n2
    if se2 <= 0.0:
        t_stat = 0.0 if abs(m2 - m1) < 1e-15 else math.copysign(1e6, m2 - m1)
        df = float(n1 + n2 - 2)
    else:
        t_stat = (m2 - m1) / math.sqrt(se2)
        num = se2 * se2
        den = 0.0
        if n1 > 1:
            den += (v1 / n1) ** 2 / (n1 - 1)
        if n2 > 1:
            den += (v2 / n2) ** 2 / (n2 - 1)
        df = num / den if den > 0.0 else float(n1 + n2 - 2)

    # two-sided p from t CDF
    cdf = students_t_cdf(abs(t_stat), max(df, 1e-6))
    p_two = max(0.0, min(1.0, 2.0 * (1.0 - cdf)))
    if alternative == "two-sided":
        p = p_two
    elif alternative == "greater":
        p = max(0.0, min(1.0, 1.0 - students_t_cdf(t_stat, max(df, 1e-6))))
    elif alternative == "less":
        p = max(0.0, min(1.0, students_t_cdf(t_stat, max(df, 1e-6))))
    else:
        raise ValueError("alternative must be two-sided|greater|less")

    return HypothesisTestResult(
        statistic=t_stat,
        p_value=p,
        df=df,
        test="welch_t",
        alternative=alternative,
        effect=effect,
        control_ci=ci_a,
        treated_ci=ci_b,
        significant=p < alpha,
        alpha=alpha,
    )


def paired_ttest(
    control: Sequence[float],
    treated: Sequence[float],
    *,
    alpha: float = 0.05,
) -> HypothesisTestResult:
    """Paired t-test on aligned samples (min length)."""
    a = _finite(control)
    b = _finite(treated)
    n = min(len(a), len(b))
    diffs = [b[i] - a[i] for i in range(n)]
    effect = cohens_d(a[:n], b[:n])
    ci_a = mean_confidence_interval(a[:n])
    ci_b = mean_confidence_interval(b[:n])
    if n < 2:
        return HypothesisTestResult(
            0.0, 1.0, 0.0, "paired_t", "two-sided", effect, ci_a, ci_b, False, alpha
        )
    mu = mean(diffs)
    s = std(diffs)
    se = s / math.sqrt(n) if s > 0.0 else 0.0
    t_stat = mu / se if se > 0.0 else (0.0 if abs(mu) < 1e-15 else math.copysign(1e6, mu))
    df = float(n - 1)
    p = max(0.0, min(1.0, 2.0 * (1.0 - students_t_cdf(abs(t_stat), df))))
    return HypothesisTestResult(
        t_stat, p, df, "paired_t", "two-sided", effect, ci_a, ci_b, p < alpha, alpha
    )


def bootstrap_mean_ci(
    xs: Sequence[float],
    *,
    level: float = 0.95,
    n_boot: int = 1000,
    seed: int = 0,
) -> ConfidenceInterval:
    vals = _finite(xs)
    if not vals:
        return ConfidenceInterval(0.0, 0.0, 0.0, level, 0)
    rng = random.Random(seed)
    means = []
    n = len(vals)
    for _ in range(n_boot):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        means.append(mean(sample))
    means.sort()
    alpha = 1.0 - level
    lo_i = int(math.floor(alpha / 2.0 * (n_boot - 1)))
    hi_i = int(math.ceil((1.0 - alpha / 2.0) * (n_boot - 1)))
    hi_i = min(hi_i, n_boot - 1)
    return ConfidenceInterval(means[lo_i], means[hi_i], mean(vals), level, n)


# ---------------------------------------------------------------------------
# Trajectory comparison
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryComparison:
    entity_id: str
    test: HypothesisTestResult
    control_final: float
    treated_final: float
    relative_change: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "test": self.test.as_dict(),
            "control_final": self.control_final,
            "treated_final": self.treated_final,
            "relative_change": self.relative_change,
        }


def extract_series(
    trajectory: TrajectoryResult,
    entity_id: str,
    *,
    burn_in: float = 0.0,
) -> List[float]:
    """Concentration time series after optional burn-in time."""
    out: List[float] = []
    for t, sample in zip(trajectory.times, trajectory.concentrations):
        if t + 1e-15 < burn_in:
            continue
        out.append(float(sample.get(entity_id, 0.0)))
    return out


def compare_trajectories(
    control: TrajectoryResult,
    treated: TrajectoryResult,
    entity_id: str,
    *,
    burn_in: float = 0.0,
    paired: bool = False,
    alpha: float = 0.05,
) -> TrajectoryComparison:
    """
    Compare control vs treated series for one entity.

    Uses Welch (default) or paired t-test; empty/invariant series yield p=1.
    """
    a = extract_series(control, entity_id, burn_in=burn_in)
    b = extract_series(treated, entity_id, burn_in=burn_in)
    if paired:
        test = paired_ttest(a, b, alpha=alpha)
    else:
        test = welch_ttest(a, b, alpha=alpha)
    cf = a[-1] if a else 0.0
    tf = b[-1] if b else 0.0
    rel = (tf - cf) / abs(cf) if abs(cf) > 1e-15 else (0.0 if abs(tf) < 1e-15 else math.copysign(1.0, tf))
    return TrajectoryComparison(entity_id, test, cf, tf, rel)


# ---------------------------------------------------------------------------
# Bayesian-style kinetic parameter audit
# ---------------------------------------------------------------------------


@dataclass
class ParameterPerturbation:
    entity_id: str
    param: str
    base_value: float
    sampled_value: float


@dataclass
class StabilityBound:
    entity_id: str
    mean_ss: float
    std_ss: float
    low: float
    high: float
    cv: float


@dataclass
class BayesianAuditReport:
    n_samples: int
    noise_sigma: float
    bounds: List[StabilityBound]
    perturbations: List[List[ParameterPerturbation]]
    unstable_entities: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_samples": self.n_samples,
            "noise_sigma": self.noise_sigma,
            "bounds": [
                {
                    "entity_id": b.entity_id,
                    "mean_ss": b.mean_ss,
                    "std_ss": b.std_ss,
                    "low": b.low,
                    "high": b.high,
                    "cv": b.cv,
                }
                for b in self.bounds
            ],
            "unstable_entities": list(self.unstable_entities),
            "metadata": dict(self.metadata),
        }


class BayesianParameterAuditor:
    """
    Lightweight Monte-Carlo audit of kinetic constant noise.

    Draws log-normal multipliers on ``vmax`` / ``km`` (and optionally
    degradation/production), re-simulates, and reports steady-state bounds.
    """

    def __init__(
        self,
        network_factory: NetworkFactory,
        *,
        config: Optional[SimulationConfig] = None,
        params: Sequence[str] = ("vmax", "km"),
        noise_sigma: float = 0.15,
        seed: int = 0,
    ) -> None:
        self.network_factory = network_factory
        self.config = config or SimulationConfig(t_end=25.0, dt=0.2, record_every=25)
        self.params = tuple(params)
        self.noise_sigma = float(noise_sigma)
        self.seed = seed
        if self.noise_sigma < 0.0:
            raise ValueError("noise_sigma must be non-negative")

    def _perturb(self, network: SignalingNetwork, rng: random.Random) -> List[ParameterPerturbation]:
        log: List[ParameterPerturbation] = []
        for ent in network.registry.entities():
            if not isinstance(ent, Protein):
                continue
            k = ent.kinetics
            updates: Dict[str, float] = {}
            for pname in self.params:
                base = float(getattr(k, pname))
                if base <= 0.0:
                    continue
                # log-normal multiplicative noise
                eps = rng.gauss(0.0, self.noise_sigma)
                sampled = base * math.exp(eps)
                sampled = max(1e-12, sampled)
                updates[pname] = sampled
                log.append(
                    ParameterPerturbation(ent.entity_id, pname, base, sampled)
                )
            if updates:
                ent.kinetics = k.with_updates(**updates)
        return log

    def run(self, *, n_samples: int = 40, cv_threshold: float = 0.35) -> BayesianAuditReport:
        if n_samples < 2:
            raise ValueError("n_samples must be ≥ 2")
        rng = random.Random(self.seed)
        # entity_id → list of steady-state (final) concentrations
        finals: Dict[str, List[float]] = {}
        pert_log: List[List[ParameterPerturbation]] = []

        for _ in range(n_samples):
            net = self.network_factory()
            pert_log.append(self._perturb(net, rng))
            traj = DualEngineSimulator(net).run_ode(self.config)
            final = traj.final_concentrations()
            for eid, val in final.items():
                finals.setdefault(eid, []).append(float(val))

        bounds: List[StabilityBound] = []
        unstable: List[str] = []
        for eid, series in finals.items():
            mu = mean(series)
            sd = std(series)
            ci = mean_confidence_interval(series, level=0.95)
            cv = (sd / abs(mu)) if abs(mu) > 1e-15 else (0.0 if sd < 1e-15 else float("inf"))
            if not math.isfinite(cv):
                cv = 1e6
            b = StabilityBound(eid, mu, sd, ci.low, ci.high, cv)
            bounds.append(b)
            if cv > cv_threshold:
                unstable.append(eid)

        return BayesianAuditReport(
            n_samples=n_samples,
            noise_sigma=self.noise_sigma,
            bounds=bounds,
            perturbations=pert_log,
            unstable_entities=unstable,
            metadata={"params": list(self.params), "cv_threshold": cv_threshold},
        )


class StatisticalVerificationEngine:
    """Facade bundling trajectory tests and kinetic audits."""

    def compare(
        self,
        control: TrajectoryResult,
        treated: TrajectoryResult,
        entity_ids: Sequence[str],
        **kwargs: Any,
    ) -> List[TrajectoryComparison]:
        return [compare_trajectories(control, treated, eid, **kwargs) for eid in entity_ids]

    def audit_kinetics(
        self,
        network_factory: NetworkFactory,
        **kwargs: Any,
    ) -> BayesianAuditReport:
        auditor = BayesianParameterAuditor(network_factory, **{
            k: v for k, v in kwargs.items() if k in {"config", "params", "noise_sigma", "seed"}
        })
        n_samples = int(kwargs.get("n_samples", 40))
        cv_threshold = float(kwargs.get("cv_threshold", 0.35))
        return auditor.run(n_samples=n_samples, cv_threshold=cv_threshold)
