"""OMOP-style control harness gate — pathway prediction ranking quality."""

from __future__ import annotations

import pytest

from cistron.benchmarks.pathway_controls import (
    CONTROL_CASES,
    MIN_AUROC,
    MIN_AUPRC,
    auc_roc,
    average_precision,
    check_gates,
    evaluate_controls,
)


def test_rank_metrics_sanity() -> None:
    assert auc_roc([0.9, 0.1, 0.8, 0.2], [1, 0, 1, 0]) == pytest.approx(1.0)
    assert auc_roc([0.1, 0.9, 0.2, 0.8], [1, 0, 1, 0]) == pytest.approx(0.0)
    assert average_precision([0.9, 0.1, 0.8, 0.2], [1, 0, 1, 0]) == pytest.approx(1.0)
    assert average_precision([0.1, 0.1, 0.1], [0, 0, 0]) == pytest.approx(0.0)


def test_control_harness_gate() -> None:
    report = evaluate_controls()
    assert report["n_pos"] >= 10 and report["n_neg"] >= 8
    assert report["auroc"] >= MIN_AUROC
    assert report["auprc"] >= MIN_AUPRC
    assert check_gates(report) == []
    assert len(report["cases"]) == len(CONTROL_CASES)
