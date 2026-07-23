"""UX translator — plain-language metrics & progressive disclosure."""

from __future__ import annotations

import pytest

from voidsignal import __version__
from voidsignal.ui.translator import (
    METRIC_CATALOG,
    BadgeTone,
    MetricTranslator,
    annotate_abbreviations,
    build_executive_summary,
    compose_progressive_brief,
    get_human_context,
    normalize_metric_key,
    translate_metric,
    wrap_raw_telemetry,
)


def test_version_ux_layer() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0 and int(minor) >= 15


def test_catalog_covers_core_metrics() -> None:
    for key in ("HSI", "LAS", "DG", "KI", "PSI", "PDS"):
        assert key in METRIC_CATALOG
        d = get_human_context(key)
        assert d.short_label
        assert d.tooltip
        assert d.technical_name


def test_alias_normalization() -> None:
    assert normalize_metric_key("hsi") == "HSI"
    assert normalize_metric_key("ΔG") == "DG"
    assert normalize_metric_key("delta_g") == "DG"
    assert normalize_metric_key("K_i") == "KI"
    assert normalize_metric_key("Homeostatic Shift Index") == "HSI"


def test_hsi_badge_ladders() -> None:
    healthy = translate_metric("HSI", 0.12)
    assert healthy.badge_tone is BadgeTone.HEALTHY
    assert "Healthy" in healthy.badge_label
    assert healthy.raw_value == 0.12  # raw preserved

    moderate = translate_metric("HSI", 0.40)
    assert moderate.badge_tone is BadgeTone.MODERATE

    severe = translate_metric("HSI", 0.73)
    assert severe.badge_tone is BadgeTone.CRITICAL
    assert "Severe" in severe.badge_label


def test_las_dg_ki_psi_phrases() -> None:
    las = translate_metric("LAS", 0.82)
    assert "High" in las.badge_label

    dg = translate_metric("ΔG", -16.2)
    assert dg.key == "DG"
    assert "Strong Lock-and-Key" in dg.badge_label
    assert dg.raw_value == -16.2

    ki = translate_metric("Ki", 1.4e-12)
    assert ki.key == "KI"
    assert ki.raw_value == 1.4e-12
    assert "Nanomolar" in ki.badge_label

    psi = translate_metric("PSI", 0.55)
    assert "Mixed" in psi.badge_label or "splic" in psi.plain_phrase.lower()


def test_get_human_context_unknown_safe() -> None:
    d = get_human_context("NOT_A_REAL_METRIC_XYZ")
    assert "No glossary" in d.tooltip or d.key


def test_executive_summary_sentence() -> None:
    summary = build_executive_summary(
        hsi=0.73,
        hsi_pre=0.73,
        las=0.52,
        readout="ERK",
        readout_pre=1.35,
        readout_post=0.68,
        objective_met=True,
        patient_id="CLIN_MULTIHIT_01",
    )
    assert "73%" in summary.sentence or "dysregulation" in summary.sentence.lower()
    assert "ERK" in summary.sentence
    assert any(b.key == "HSI" for b in summary.badges)
    # Raw floats on badges unchanged
    hsi_badge = next(b for b in summary.badges if b.key == "HSI")
    assert hsi_badge.raw_value == 0.73


def test_progressive_brief_wraps_telemetry() -> None:
    summary = build_executive_summary(hsi=0.35, las=0.6)
    body = "## Results\n\nHSI=0.35 raw matrix [[1,2],[3,4]]\n"
    md = compose_progressive_brief(executive=summary, body_markdown=body)
    assert "Executive Summary" in md
    assert "<details>" in md
    assert "Show Raw Biophysical Telemetry" in md
    assert "Glossary" in md
    assert "Cellular Health" in md


def test_wrap_and_annotate_do_not_mutate_numbers() -> None:
    raw = "HSI=0.7302 and LAS=0.5206 with ΔG=-8.1"
    wrapped = wrap_raw_telemetry(raw)
    assert "0.7302" in wrapped and "0.5206" in wrapped and "-8.1" in wrapped
    annotated = annotate_abbreviations(raw)
    assert "0.7302" in annotated
    assert "Cellular Health" in annotated


def test_translator_facade() -> None:
    t = MetricTranslator()
    assert t.context("PDS").short_label.startswith("Pathway")
    cat = t.catalog()
    assert "HSI" in cat
    brief = t.progressive_brief("raw body", hsi=0.2, las=0.9)
    assert "Executive Summary" in brief
