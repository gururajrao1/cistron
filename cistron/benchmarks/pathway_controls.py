"""OMOP-style positive/negative control harness for pathway predictions.

Methodology follows the pharmacovigilance reference-set tradition (OMOP
165+/234- over 4 HOIs, EU-ADR 44+/50-) and the paperswithcode ranking
convention (AUROC + AUPRC): curated condition queries are labels, the
Hill-cube readout activity is the score. This guards pipeline integrity
(resolver + engine + topology) — it is NOT a clinical-validity claim.

Known-weak spot (documented, not hidden): the TNBC PI3K arm readout AKT1
scores ~0.0 under the default EGF clamp while the MAPK arm (MAPK1/MYC)
responds strongly. AKT1 is therefore excluded from the positive set until
the PI3K branch is re-driven.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import time

from cistron.data.resolver import resolve_condition_network
from cistron.engine import HillCubeConfig, HillCubeEngine

#: (condition query, readout symbol, label 1=positive / 0=negative,
#:  minimum score for positives; None = must stay ~0 for negatives)
CONTROL_CASES: Tuple[Tuple[str, str, int, Optional[float]], ...] = (
    ("Hypoxia-induced angiogenesis", "VEGFA", 1, 0.40),
    ("Hypoxia-induced angiogenesis", "GLUT1", 1, 0.40),
    ("Alzheimer's amyloid stress", "NFKB1", 1, 0.50),
    ("Alzheimer's amyloid stress", "TNF", 1, 0.40),
    ("Triple-negative breast cancer EGFR survival", "MAPK1", 1, 0.50),
    ("Triple-negative breast cancer EGFR survival", "MYC", 1, 0.40),
    ("Radiation DNA damage p53 response", "CDKN1A", 1, 0.40),
    ("Radiation DNA damage p53 response", "BAX", 1, 0.40),
    ("Glaucoma oxidative stress", "HMOX1", 1, 0.40),
    ("LPS inflammatory cytokine storm", "IL6", 1, 0.40),
    ("Hypoxia-induced angiogenesis", "TNF", 0, None),
    ("Hypoxia-induced angiogenesis", "MAPK1", 0, None),
    ("Radiation DNA damage p53 response", "VEGFA", 0, None),
    ("Radiation DNA damage p53 response", "TNF", 0, None),
    ("LPS inflammatory cytokine storm", "VEGFA", 0, None),
    ("LPS inflammatory cytokine storm", "MAPK1", 0, None),
    ("Triple-negative breast cancer EGFR survival", "TNF", 0, None),
    ("Alzheimer's amyloid stress", "VEGFA", 0, None),
)

#: Regression-gate floors for the control set above.
MIN_AUROC = 0.95
MIN_AUPRC = 0.95
#: Per-case wall budget (offline resolve + 60-min Hill-cube run).
MAX_CASE_MS = 15_000.0


def _run_query_once(
    query: str, *, t_end: float = 60.0
) -> Tuple[Dict[str, float], set]:
    """Resolve one condition offline and run the Hill-cube engine once."""
    resolved = resolve_condition_network(query, use_omnipath=False)
    engine = HillCubeEngine(
        resolved.graph,
        config=HillCubeConfig(
            t_end=float(t_end), dense_output_points=61, method="LSODA"
        ),
    )
    for symbol, value in resolved.default_clamps.items():
        if symbol in engine.symbols:
            engine.clamp(symbol, float(value))
    final = engine.simulate(t_end=float(t_end)).final()
    return dict(final), set(resolved.graph.nodes)


def score_control(
    query: str,
    readout: str,
    *,
    t_end: float = 60.0,
) -> float:
    """Resolve one condition offline and return the readout final activity.

    Readouts absent from the resolved graph score 0.0 (negative controls).
    """
    final, nodes = _run_query_once(query, t_end=t_end)
    if readout not in nodes:
        return 0.0
    return max(0.0, min(1.5, float(final.get(readout, 0.0))))


def auc_roc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Rank-based AUROC (Mann-Whitney, averaged ties)."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    n_pos = sum(1 for label in labels if label == 1)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum = sum(rank for rank, label in zip(ranks, labels) if label == 1)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def average_precision(scores: Sequence[float], labels: Sequence[int]) -> float:
    """AUPRC as average precision over the score ranking."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    n_pos = sum(1 for label in labels if label == 1)
    if n_pos == 0:
        return 0.0
    hits = 0
    total = 0.0
    for rank, idx in enumerate(order, 1):
        if labels[idx] == 1:
            hits += 1
            total += hits / rank
    return total / n_pos


@dataclass
class ControlResult:
    query: str
    readout: str
    label: int
    score: float
    min_score: Optional[float]
    elapsed_ms: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "readout": self.readout,
            "label": self.label,
            "score": self.score,
            "min_score": self.min_score,
            "elapsed_ms": self.elapsed_ms,
        }


def evaluate_controls(
    cases: Sequence[Tuple[str, str, int, Optional[float]]] = CONTROL_CASES,
    *,
    t_end: float = 60.0,
) -> Dict[str, Any]:
    """Score every control case once and summarize ranking quality."""
    results: List[ControlResult] = []
    finals: Dict[str, Tuple[Dict[str, float], set]] = {}
    for query, readout, label, min_score in cases:
        t0 = time.perf_counter()
        if query not in finals:
            finals[query] = _run_query_once(query, t_end=t_end)
        final, nodes = finals[query]
        score = (
            max(0.0, min(1.5, float(final.get(readout, 0.0))))
            if readout in nodes
            else 0.0
        )
        results.append(
            ControlResult(
                query=query,
                readout=readout,
                label=label,
                score=score,
                min_score=min_score,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )
        )
    scores = [r.score for r in results]
    labels = [r.label for r in results]
    return {
        "cases": [r.as_dict() for r in results],
        "auroc": auc_roc(scores, labels),
        "auprc": average_precision(scores, labels),
        "n_pos": sum(labels),
        "n_neg": len(labels) - sum(labels),
        "max_case_ms": max((r.elapsed_ms for r in results), default=0.0),
    }


def check_gates(report: Mapping[str, Any]) -> List[str]:
    """Return human-readable gate failures (empty when green)."""
    failures: List[str] = []
    if float(report.get("auroc", 0.0)) < MIN_AUROC:
        failures.append(
            f"auroc {float(report.get('auroc', 0.0)):.3f} < {MIN_AUROC}"
        )
    if float(report.get("auprc", 0.0)) < MIN_AUPRC:
        failures.append(
            f"auprc {float(report.get('auprc', 0.0)):.3f} < {MIN_AUPRC}"
        )
    for case in report.get("cases", []):  # type: ignore[union-attr]
        if case["label"] == 1 and case["min_score"] is not None:
            if float(case["score"]) < float(case["min_score"]):
                failures.append(
                    f"positive {case['query']!r}->{case['readout']} "
                    f"score {case['score']:.3f} < {case['min_score']}"
                )
        if case["label"] == 0 and float(case["score"]) > 1e-9:
            failures.append(
                f"negative {case['query']!r}->{case['readout']} "
                f"score {case['score']:.3f} != 0"
            )
        if float(case["elapsed_ms"]) > MAX_CASE_MS:
            failures.append(
                f"case {case['query']!r}->{case['readout']} "
                f"{case['elapsed_ms']:.0f}ms > {MAX_CASE_MS:.0f}ms budget"
            )
    return failures


__all__ = [
    "CONTROL_CASES",
    "MIN_AUROC",
    "MIN_AUPRC",
    "MAX_CASE_MS",
    "ControlResult",
    "auc_roc",
    "average_precision",
    "check_gates",
    "evaluate_controls",
    "score_control",
]
