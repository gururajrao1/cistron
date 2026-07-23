"""Phase 10 — autonomous agent planner, literature LAS, scientific reports."""

from __future__ import annotations

from cistron import (
    BiologicalAgentPlanner,
    LiteratureReasoner,
    ResearchGoal,
    ScientificReportGenerator,
    StepKind,
    __version__,
    literature_alignment_score,
    parse_research_goal,
)
from cistron.agent.literature_reasoner import default_mapk_corpus
from cistron.agent.reporter import ReportContext
from cistron.visualization.session import build_demo_mapk


RESEARCH_GOAL = (
    "Find a two-drug combination that "
    "halts ERK over-activation in a mutated EGFR background "
    "without exceeding the toxicity threshold"
)


def test_version_phase10() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0 and int(minor) >= 10


def test_parse_two_drug_erk_egfr_goal() -> None:
    parsed = parse_research_goal(RESEARCH_GOAL)
    assert parsed.goal.n_drugs == 2
    assert parsed.goal.readout == "ERK"
    assert "EGFR" in parsed.goal.oncogenes
    assert parsed.goal.disease == "cancer"
    assert parsed.goal.require_tox_safe is True
    assert parsed.confidence >= 0.5
    assert parsed.matched_rules


def test_literature_alignment_score_mapk() -> None:
    net, ids = build_demo_mapk()
    scores = {
        ids["MEK"]: 0.9,
        ids["EGFR"]: 0.85,
        ids["ERK"]: 0.4,
        ids["RAS"]: 0.7,
    }
    reasoner = LiteratureReasoner()
    report = reasoner.align(net, scores, synergy_pair=("MEK", "EGFR"))
    assert 0.0 <= report.las <= 1.0
    assert report.las >= 0.4
    assert report.synergy_alignment is not None
    assert report.target_alignments
    assert "LAS=" in report.summary

    direct = literature_alignment_score(
        scores,
        symbol_map={eid: net.registry.get(eid).name for eid in scores},
        evidence=default_mapk_corpus(),
        kegg_symbols={"EGFR", "MEK", "ERK", "RAS", "RAF"},
        synergy_pair=("MEK", "EGFR"),
    )
    assert direct.las > 0.0


def test_planner_end_to_end_fast() -> None:
    planner = BiologicalAgentPlanner()
    defaults = ResearchGoal(
        text=RESEARCH_GOAL,
        t_sim=12.0,
        dt=0.5,
        t_start=2.0,
        t_end=9.0,
        dose=2.0,
        ensemble_members=3,
        tox_threshold=8.0,
        drug_candidates=("MEK", "EGFR", "RAF"),
    )
    plan = planner.plan(RESEARCH_GOAL, defaults=defaults)
    assert any(s.kind is StepKind.DRUG_COMBINATION for s in plan.steps)
    assert "ERK" in plan.hypothesis

    result = planner.run(RESEARCH_GOAL, defaults=defaults, plan=plan)
    assert result.success is True
    assert result.baseline is not None and result.treated is not None
    assert result.synergy is not None
    assert len(result.best_agents) == 2
    assert result.hsi is not None
    assert result.literature is not None
    assert result.literature.las >= 0.0
    assert "## Abstract" in result.report_markdown
    assert "## Hypothesis" in result.report_markdown
    assert "## Literature Alignment" in result.report_markdown
    assert "AIScientistReasoner" in result.report_markdown
    payload = result.as_dict()
    assert payload["success"] is True
    assert payload["best_agents"]


def test_report_generator_monotherapy() -> None:
    planner = BiologicalAgentPlanner()
    text = "single-drug MEK inhibition of ERK in EGFR mutant cancer"
    defaults = ResearchGoal(
        text=text,
        n_drugs=1,
        t_sim=10.0,
        dt=0.5,
        t_start=1.0,
        t_end=8.0,
        ensemble_members=3,
        tox_threshold=10.0,
        drug_candidates=("MEK", "RAF"),
    )
    parsed = parse_research_goal(text, defaults=defaults)
    assert parsed.goal.n_drugs == 1
    result = planner.run(text, defaults=defaults)
    assert result.success
    md = ScientificReportGenerator().generate(
        ReportContext(plan=result.plan, result=result)
    )
    assert "Experimental Design" in md
    assert len(md) > 500
