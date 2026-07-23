"""UX translator smoke — plain-language metrics without mutating raw floats."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from cistron import __version__
from cistron.ui.translator import (
    build_executive_summary,
    compose_progressive_brief,
    translate_metric,
)


def main() -> int:
    print(f"CISTRON {__version__} - UX translator smoke demo")
    print("=" * 60)

    for key, val in (
        ("HSI", 0.73),
        ("LAS", 0.52),
        ("PDS", 0.41),
        ("DG", -16.16),
        ("KI", 1.4e-12),
        ("PSI", 0.55),
    ):
        t = translate_metric(key, val)
        print(
            f"[{key}] raw={t.raw_value!r} -> {t.short_label}: "
            f"{t.badge_label} ({t.display_value}) tone={t.badge_tone.value}"
        )
        assert t.raw_value == val

    summary = build_executive_summary(
        hsi=0.353,
        hsi_pre=0.730,
        las=0.521,
        readout="ERK",
        readout_pre=1.35,
        readout_post=0.68,
        objective_met=True,
        patient_id="CLIN_MULTIHIT_01",
    )
    print("---")
    print(summary.sentence)
    md = compose_progressive_brief(
        executive=summary,
        body_markdown="## Raw Results\n\nHSI=0.353 LAS=0.521 matrix=[[...]]\n",
    )
    assert "Executive Summary" in md and "<details>" in md
    print("---")
    print(md[:500])
    print("=" * 60)
    print("UX translator demo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
