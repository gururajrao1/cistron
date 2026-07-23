"""Phase 10 live smoke demo — autonomous BiologicalAgentPlanner."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["CISTRON_HEADLESS"] = "1"

from cistron import BiologicalAgentPlanner, ResearchGoal, __version__


def main() -> int:
    print(f"CISTRON {__version__} — Phase 10 agent smoke demo")
    print("=" * 60)

    goal_text = (
        "Find a two-drug combination that "
        "halts ERK over-activation in a mutated EGFR background "
        "without exceeding the toxicity threshold"
    )
    defaults = ResearchGoal(
        text=goal_text,
        t_sim=16.0,
        dt=0.5,
        t_start=2.0,
        t_end=12.0,
        dose=2.0,
        ensemble_members=4,
        tox_threshold=8.0,
        drug_candidates=("MEK", "EGFR", "RAF"),
    )

    planner = BiologicalAgentPlanner()
    plan = planner.plan(goal_text, defaults=defaults)
    print(f"Hypothesis: {plan.hypothesis}")
    print(f"Parse confidence: {plan.parse.confidence:.2f}")
    print(f"Rules: {', '.join(plan.parse.matched_rules)}")
    print(f"Steps ({len(plan.steps)}):")
    for i, step in enumerate(plan.steps, 1):
        print(f"  {i}. {step.kind.value}: {step.description}")

    print("-" * 60)
    print("Executing autonomous campaign…")
    result = planner.run(goal_text, defaults=defaults, plan=plan)

    print(f"success={result.success} objective_met={result.objective_met}")
    if result.synergy:
        agents = " + ".join(a.name for a in result.best_agents)
        print(
            f"combo={agents} effect_ab={result.synergy.effect_ab:.3f} "
            f"bliss={result.synergy.bliss_score:.3f} ({result.synergy.interpretation})"
        )
    if result.hsi:
        print(f"HSI={result.hsi.hsi:.4f} collapse={result.hsi.collapse_flag}")
    if result.literature:
        print(f"LAS={result.literature.las:.4f}")
        print(f"  {result.literature.summary}")
    print(f"tox_events={len(result.tox_events)} tox_safe={result.tox_safe}")
    for note in result.notes:
        print(f"note: {note}")

    print("-" * 60)
    print("Report preview (first 1200 chars):")
    print(result.report_markdown[:1200])
    print("…")
    print("=" * 60)
    print("Phase 10 demo OK")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
