"""
VOIDSIGNAL Phase 10 — agent package.

Autonomous experiment planning, literature alignment, scientific report
synthesis, and causal biological explainability. Operates fully offline /
deterministically; optional LLM adapters may refine goal parsing when configured.
"""

from voidsignal.agent.causal_reasoner import (
    CausalBioReasoner,
    CausalChainStep,
    CausalExplanation,
    DeltaSummaryReport,
)
from voidsignal.agent.literature_reasoner import (
    CuratedEvidence,
    LiteratureAlignmentReport,
    LiteratureReasoner,
    literature_alignment_score,
)
from voidsignal.agent.planner import (
    BiologicalAgentPlanner,
    ExperimentPlan,
    ExperimentStep,
    GoalParseResult,
    PlanExecutionResult,
    ResearchGoal,
    StepKind,
    parse_research_goal,
)
from voidsignal.agent.reporter import (
    ReportContext,
    ScientificReportGenerator,
)

__all__ = [
    "BiologicalAgentPlanner",
    "CausalBioReasoner",
    "CausalChainStep",
    "CausalExplanation",
    "CuratedEvidence",
    "DeltaSummaryReport",
    "ExperimentPlan",
    "ExperimentStep",
    "GoalParseResult",
    "LiteratureAlignmentReport",
    "LiteratureReasoner",
    "PlanExecutionResult",
    "ReportContext",
    "ResearchGoal",
    "ScientificReportGenerator",
    "StepKind",
    "literature_alignment_score",
    "parse_research_goal",
]
