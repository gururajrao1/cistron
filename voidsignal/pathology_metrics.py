"""
Dysregulation & pathway collapse metrics for VOIDSIGNAL Phase 7.

Quantifies network-level health versus pathological drift:

* **Homeostatic Shift Index (HSI)** — divergence of steady-state trajectories
  from a physiological baseline.
* **Pathway Dysregulation Score (PDS)** — composite scores over functional
  subnetworks (e.g. survival vs apoptosis).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import logging
import math

from voidsignal.simulation import TrajectoryResult
from voidsignal.statistics import mean, std
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)


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


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if abs(den) < 1e-15:
        return default
    return num / den


def steady_state_window(
    trajectory: TrajectoryResult,
    entity_id: str,
    *,
    frac: float = 0.25,
) -> List[float]:
    """
    Return the last ``frac`` fraction of the concentration series as a
    steady-state sample window.
    """
    series = trajectory.series(entity_id)
    if not series:
        return []
    n = max(1, int(math.ceil(len(series) * frac)))
    return series[-n:]


def relative_l2(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """√Σ ((b−a)/max(|a|,ε))² / √N  — scale-free vector distance."""
    keys = sorted(set(a) | set(b))
    if not keys:
        return 0.0
    acc = 0.0
    for k in keys:
        av = float(a.get(k, 0.0))
        bv = float(b.get(k, 0.0))
        scale = max(abs(av), 1e-6)
        d = (bv - av) / scale
        acc += d * d
    return math.sqrt(acc / len(keys))


# ---------------------------------------------------------------------------
# Homeostatic Shift Index
# ---------------------------------------------------------------------------


@dataclass
class NodeShift:
    entity_id: str
    name: str
    baseline_ss: float
    disease_ss: float
    absolute_delta: float
    relative_delta: float
    contribution: float


@dataclass
class HomeostaticShiftReport:
    """
    Network-level HSI ∈ [0, ∞); 0 ≈ perfect homeostasis match.

    ``hsi`` is the mean absolute relative steady-state deviation across nodes,
    optionally weighted. ``collapse_flag`` trips when HSI exceeds ``threshold``
    or when any critical node exceeds ``node_threshold``.
    """

    hsi: float
    weighted_hsi: float
    node_shifts: List[NodeShift]
    threshold: float
    collapse_flag: bool
    baseline_final: Dict[str, float]
    disease_final: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hsi": self.hsi,
            "weighted_hsi": self.weighted_hsi,
            "threshold": self.threshold,
            "collapse_flag": self.collapse_flag,
            "n_nodes": len(self.node_shifts),
            "top_shifts": [
                {
                    "entity_id": s.entity_id,
                    "name": s.name,
                    "relative_delta": s.relative_delta,
                    "contribution": s.contribution,
                }
                for s in self.node_shifts[:8]
            ],
            "metadata": dict(self.metadata),
        }


def homeostatic_shift_index(
    baseline: TrajectoryResult,
    disease: TrajectoryResult,
    network: SignalingNetwork,
    *,
    entity_ids: Optional[Sequence[str]] = None,
    ss_frac: float = 0.25,
    weights: Optional[Mapping[str, float]] = None,
    threshold: float = 0.75,
    node_threshold: float = 2.0,
) -> HomeostaticShiftReport:
    """
    Compute HSI between a healthy baseline trajectory and a disease trajectory.

    Per-node relative delta::

        δ_i = (μ_disease − μ_baseline) / max(|μ_baseline|, ε)

    HSI = mean(|δ_i|); weighted_HSI uses optional node weights (default 1).
    """
    ids = list(entity_ids) if entity_ids is not None else sorted(
        set(baseline.final_concentrations()) & set(disease.final_concentrations())
    )
    # Prefer intersection with network nodes
    ids = [i for i in ids if i in network.registry]
    shifts: List[NodeShift] = []
    abs_rels: List[float] = []
    w_abs: List[float] = []
    w_sum = 0.0

    base_final = baseline.final_concentrations()
    dis_final = disease.final_concentrations()

    for eid in ids:
        b_win = _finite(steady_state_window(baseline, eid, frac=ss_frac))
        d_win = _finite(steady_state_window(disease, eid, frac=ss_frac))
        b_mu = mean(b_win) if b_win else float(base_final.get(eid, 0.0))
        d_mu = mean(d_win) if d_win else float(dis_final.get(eid, 0.0))
        abs_d = d_mu - b_mu
        rel = abs_d / max(abs(b_mu), 1e-6)
        w = float((weights or {}).get(eid, 1.0))
        if w < 0.0:
            w = 0.0
        contrib = abs(rel) * w
        name = network.registry.get(eid).name if eid in network.registry else eid
        shifts.append(
            NodeShift(
                entity_id=eid,
                name=name,
                baseline_ss=b_mu,
                disease_ss=d_mu,
                absolute_delta=abs_d,
                relative_delta=rel,
                contribution=contrib,
            )
        )
        abs_rels.append(abs(rel))
        w_abs.append(contrib)
        w_sum += w

    shifts.sort(key=lambda s: abs(s.relative_delta), reverse=True)
    hsi = mean(abs_rels) if abs_rels else 0.0
    weighted = (sum(w_abs) / w_sum) if w_sum > 1e-15 else hsi
    collapse = hsi >= threshold or any(abs(s.relative_delta) >= node_threshold for s in shifts)

    # Also report vector L2 for metadata
    b_ss = {s.entity_id: s.baseline_ss for s in shifts}
    d_ss = {s.entity_id: s.disease_ss for s in shifts}

    return HomeostaticShiftReport(
        hsi=hsi,
        weighted_hsi=weighted,
        node_shifts=shifts,
        threshold=threshold,
        collapse_flag=collapse,
        baseline_final=dict(base_final),
        disease_final=dict(dis_final),
        metadata={
            "ss_frac": ss_frac,
            "relative_l2": relative_l2(b_ss, d_ss),
            "max_abs_rel": max(abs_rels) if abs_rels else 0.0,
        },
    )


# ---------------------------------------------------------------------------
# Pathway Dysregulation Score
# ---------------------------------------------------------------------------


@dataclass
class SubnetworkDefinition:
    """Named functional module for PDS calculation."""

    name: str
    member_ids: List[str]
    """Entity ids (preferred) or symbols resolved later."""
    polarity: float = 1.0
    """+1 for pro-pathology when elevated; −1 when elevation is protective."""
    weight: float = 1.0


# Canonical biology panels (symbols; resolved against a live network)
DEFAULT_SURVIVAL_PANEL = ("BCL2", "AKT", "PI3K", "ERK", "MEK", "RAS", "RAF", "EGFR")
DEFAULT_APOPTOSIS_PANEL = ("BAX", "BAK", "CASP3", "CASP8", "CASP9", "TP53", "CYCS")
DEFAULT_INFLAMMATION_PANEL = ("TNF", "IL6", "IL1B", "NFKB1", "CXCL8")
DEFAULT_METABOLIC_PANEL = ("INSR", "GLUT4", "SLC2A4", "INS", "GLUCOSE")


def resolve_panel(network: SignalingNetwork, symbols: Sequence[str]) -> List[str]:
    ids: List[str] = []
    for sym in symbols:
        if sym in network.registry:
            ids.append(sym)
            continue
        upper = sym.upper()
        for ent in network.registry.entities():
            if ent.name.upper() == upper or str(ent.metadata.get("gene_symbol", "")).upper() == upper:
                ids.append(ent.entity_id)
                break
    return ids


@dataclass
class PathwayScore:
    name: str
    score: float
    mean_activity: float
    n_members: int
    members_present: List[str]


@dataclass
class PathwayDysregulationReport:
    """
    Composite PDS and module-level scores.

    ``survival_apoptosis_ratio`` uses mean SS levels of the two panels.
    ``pds`` aggregates weighted absolute module deviations from baseline.
    """

    pds: float
    module_scores: List[PathwayScore]
    survival_apoptosis_ratio: Optional[float]
    baseline_ratio: Optional[float]
    collapse_flag: bool
    threshold: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pds": self.pds,
            "survival_apoptosis_ratio": self.survival_apoptosis_ratio,
            "baseline_ratio": self.baseline_ratio,
            "collapse_flag": self.collapse_flag,
            "threshold": self.threshold,
            "modules": [
                {
                    "name": m.name,
                    "score": m.score,
                    "mean_activity": m.mean_activity,
                    "n_members": m.n_members,
                }
                for m in self.module_scores
            ],
            "metadata": dict(self.metadata),
        }


def _panel_mean(traj: TrajectoryResult, member_ids: Sequence[str], *, ss_frac: float) -> float:
    vals = []
    for eid in member_ids:
        win = _finite(steady_state_window(traj, eid, frac=ss_frac))
        if win:
            vals.append(mean(win))
        else:
            finals = traj.final_concentrations()
            if eid in finals:
                vals.append(float(finals[eid]))
    return mean(vals) if vals else 0.0


def pathway_dysregulation_score(
    baseline: TrajectoryResult,
    disease: TrajectoryResult,
    network: SignalingNetwork,
    *,
    modules: Optional[Sequence[SubnetworkDefinition]] = None,
    ss_frac: float = 0.25,
    threshold: float = 1.0,
    survival_symbols: Sequence[str] = DEFAULT_SURVIVAL_PANEL,
    apoptosis_symbols: Sequence[str] = DEFAULT_APOPTOSIS_PANEL,
) -> PathwayDysregulationReport:
    """
    PDS = Σ_m w_m · |μ_m^dis − μ_m^base| / max(|μ_m^base|, ε)

    plus optional survival/apoptosis ratio diagnostics.
    """
    if modules is None:
        modules = [
            SubnetworkDefinition(
                "survival",
                resolve_panel(network, survival_symbols),
                polarity=1.0,
                weight=1.0,
            ),
            SubnetworkDefinition(
                "apoptosis",
                resolve_panel(network, apoptosis_symbols),
                polarity=-1.0,
                weight=1.0,
            ),
            SubnetworkDefinition(
                "inflammation",
                resolve_panel(network, DEFAULT_INFLAMMATION_PANEL),
                polarity=1.0,
                weight=0.8,
            ),
            SubnetworkDefinition(
                "metabolic",
                resolve_panel(network, DEFAULT_METABOLIC_PANEL),
                polarity=1.0,
                weight=0.8,
            ),
        ]

    module_scores: List[PathwayScore] = []
    weighted_acc = 0.0
    weight_sum = 0.0
    for mod in modules:
        members = [m for m in mod.member_ids if m in network.registry]
        if not members:
            continue
        mu_b = _panel_mean(baseline, members, ss_frac=ss_frac)
        mu_d = _panel_mean(disease, members, ss_frac=ss_frac)
        rel = abs(mu_d - mu_b) / max(abs(mu_b), 1e-6)
        # Signed score: polarity · (disease − baseline) / scale
        signed = mod.polarity * (mu_d - mu_b) / max(abs(mu_b), 1e-6)
        score = rel  # magnitude used in PDS aggregate
        module_scores.append(
            PathwayScore(
                name=mod.name,
                score=signed,
                mean_activity=mu_d,
                n_members=len(members),
                members_present=members,
            )
        )
        w = max(0.0, float(mod.weight))
        weighted_acc += w * score
        weight_sum += w

    pds = weighted_acc / weight_sum if weight_sum > 1e-15 else 0.0

    surv_ids = resolve_panel(network, survival_symbols)
    apo_ids = resolve_panel(network, apoptosis_symbols)
    surv_d = _panel_mean(disease, surv_ids, ss_frac=ss_frac) if surv_ids else None
    apo_d = _panel_mean(disease, apo_ids, ss_frac=ss_frac) if apo_ids else None
    surv_b = _panel_mean(baseline, surv_ids, ss_frac=ss_frac) if surv_ids else None
    apo_b = _panel_mean(baseline, apo_ids, ss_frac=ss_frac) if apo_ids else None

    ratio = None
    base_ratio = None
    if surv_d is not None and apo_d is not None:
        ratio = _safe_div(surv_d, max(apo_d, 1e-6), default=surv_d)
    if surv_b is not None and apo_b is not None:
        base_ratio = _safe_div(surv_b, max(apo_b, 1e-6), default=surv_b)

    return PathwayDysregulationReport(
        pds=pds,
        module_scores=module_scores,
        survival_apoptosis_ratio=ratio,
        baseline_ratio=base_ratio,
        collapse_flag=pds >= threshold,
        threshold=threshold,
        metadata={
            "ss_frac": ss_frac,
            "n_modules_scored": len(module_scores),
        },
    )


class PathologyMetricsEngine:
    """Facade combining HSI and PDS for disease-vs-baseline audits."""

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        hsi_threshold: float = 0.75,
        pds_threshold: float = 1.0,
    ) -> None:
        self.network = network
        self.hsi_threshold = hsi_threshold
        self.pds_threshold = pds_threshold

    def evaluate(
        self,
        baseline: TrajectoryResult,
        disease: TrajectoryResult,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        hsi = homeostatic_shift_index(
            baseline,
            disease,
            self.network,
            threshold=kwargs.get("hsi_threshold", self.hsi_threshold),
            ss_frac=kwargs.get("ss_frac", 0.25),
            entity_ids=kwargs.get("entity_ids"),
            weights=kwargs.get("weights"),
        )
        pds = pathway_dysregulation_score(
            baseline,
            disease,
            self.network,
            threshold=kwargs.get("pds_threshold", self.pds_threshold),
            ss_frac=kwargs.get("ss_frac", 0.25),
            modules=kwargs.get("modules"),
        )
        return {
            "homeostatic_shift": hsi.as_dict(),
            "pathway_dysregulation": pds.as_dict(),
            "pathology_flag": bool(hsi.collapse_flag or pds.collapse_flag),
        }
