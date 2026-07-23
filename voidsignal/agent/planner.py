"""
Autonomous experiment planner for VOIDSIGNAL Phase 10.

Maps natural-language or structured research goals onto executable simulation
pipelines spanning disease presets, pharmacology, ensembles, GAT prioritization,
toxicology, literature alignment, and report synthesis.

Runs fully deterministically without external LLM keys. Optional
:class:`LLMAdapter` instances may refine goal parsing when provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)
import copy
import logging
import re

from voidsignal.agent.literature_reasoner import LiteratureAlignmentReport, LiteratureReasoner
from voidsignal.agent.reporter import ReportContext, ScientificReportGenerator
from voidsignal.disease_models import CancerSignalingConfig, build_cancer_phenotype
from voidsignal.explainability import AIScientistReasoner
from voidsignal.graph_ml import build_graph_tensors
from voidsignal.hpc_runner import EnsembleResult, EnsembleRunner
from voidsignal.pathology_metrics import HomeostaticShiftReport, homeostatic_shift_index
from voidsignal.pharmacology import (
    DrugAgent,
    Mechanism,
    PharmacokineticProfile,
    SynergyResult,
    bliss_independence,
    interpret_synergy,
)
from voidsignal.predictive_models import TargetDiscoveryModel, TargetScore
from voidsignal.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from voidsignal.statistics import TrajectoryComparison, compare_trajectories
from voidsignal.topology import SignalingNetwork
from voidsignal.toxicology import (
    SafetyPathway,
    SafetyTarget,
    SafetyTargetPanel,
    ThresholdDirection,
    ToxicologyMonitor,
)
from voidsignal.visualization.session import build_demo_mapk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM adapter (optional)
# ---------------------------------------------------------------------------


class LLMAdapter(Protocol):
    """Pluggable language-model interface for goal refinement."""

    def complete(self, prompt: str, *, system: str = "") -> str:
        ...


# ---------------------------------------------------------------------------
# Goal / plan schema
# ---------------------------------------------------------------------------


class StepKind(str, Enum):
    PARSE_GOAL = "parse_goal"
    BUILD_NETWORK = "build_network"
    DISEASE_PRESET = "disease_preset"
    TARGET_PRIORITIZE = "target_prioritize"
    DRUG_MONOTHERAPY = "drug_monotherapy"
    DRUG_COMBINATION = "drug_combination"
    ENSEMBLE_SENSITIVITY = "ensemble_sensitivity"
    TOXICOLOGY_AUDIT = "toxicology_audit"
    STATISTICAL_AUDIT = "statistical_audit"
    LITERATURE_ALIGN = "literature_align"
    SYNTHESIZE_REPORT = "synthesize_report"


@dataclass
class ResearchGoal:
    """Structured biological objective consumed by the planner."""

    text: str
    readout: str = "ERK"
    oncogenes: Tuple[str, ...] = ("EGFR", "RAS")
    disease: str = "cancer"
    """``cancer`` | ``none``"""
    n_drugs: int = 2
    drug_candidates: Tuple[str, ...] = ("MEK", "EGFR", "RAF")
    dose: float = 1.5
    t_start: float = 5.0
    t_end: float = 40.0
    t_sim: float = 50.0
    dt: float = 0.5
    tox_threshold: float = 4.0
    halt_overactivation: bool = True
    require_tox_safe: bool = True
    ensemble_members: int = 6
    patient_id: str = "agent_case"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "readout": self.readout,
            "oncogenes": list(self.oncogenes),
            "disease": self.disease,
            "n_drugs": self.n_drugs,
            "drug_candidates": list(self.drug_candidates),
            "dose": self.dose,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "t_sim": self.t_sim,
            "tox_threshold": self.tox_threshold,
            "halt_overactivation": self.halt_overactivation,
            "require_tox_safe": self.require_tox_safe,
            "ensemble_members": self.ensemble_members,
            "patient_id": self.patient_id,
            "metadata": dict(self.metadata),
        }


@dataclass
class GoalParseResult:
    goal: ResearchGoal
    confidence: float
    matched_rules: List[str]
    llm_refined: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal.as_dict(),
            "confidence": self.confidence,
            "matched_rules": list(self.matched_rules),
            "llm_refined": self.llm_refined,
        }


@dataclass
class ExperimentStep:
    kind: StepKind
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    """``pending`` | ``running`` | ``done`` | ``skipped`` | ``failed``"""
    result_summary: str = ""
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "description": self.description,
            "params": dict(self.params),
            "status": self.status,
            "result_summary": self.result_summary,
            "artifacts": dict(self.artifacts),
        }


@dataclass
class ExperimentPlan:
    goal: ResearchGoal
    steps: List[ExperimentStep]
    hypothesis: str
    parse: GoalParseResult

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "goal": self.goal.as_dict(),
            "parse": self.parse.as_dict(),
            "steps": [s.as_dict() for s in self.steps],
        }


@dataclass
class PlanExecutionResult:
    plan: ExperimentPlan
    ids: Dict[str, str] = field(default_factory=dict)
    baseline: Optional[TrajectoryResult] = None
    disease: Optional[TrajectoryResult] = None
    treated: Optional[TrajectoryResult] = None
    best_agents: List[DrugAgent] = field(default_factory=list)
    synergy: Optional[SynergyResult] = None
    monotherapy_effects: Dict[str, float] = field(default_factory=dict)
    hsi: Optional[HomeostaticShiftReport] = None
    ensemble: Optional[EnsembleResult] = None
    tox_events: List[Dict[str, Any]] = field(default_factory=list)
    tox_safe: bool = True
    stats: List[TrajectoryComparison] = field(default_factory=list)
    target_scores: List[TargetScore] = field(default_factory=list)
    ai_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    literature: Optional[LiteratureAlignmentReport] = None
    report_markdown: str = ""
    success: bool = False
    objective_met: bool = False
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "objective_met": self.objective_met,
            "hypothesis": self.plan.hypothesis,
            "goal": self.plan.goal.as_dict(),
            "steps": [s.as_dict() for s in self.plan.steps],
            "best_agents": [
                {
                    "name": a.name,
                    "target_id": a.target_id,
                    "dose": a.plateau_concentration or a.pk.dose,
                    "mechanism": a.mechanism.value,
                    "t_start": a.t_start,
                    "t_end": a.t_end,
                }
                for a in self.best_agents
            ],
            "synergy": self.synergy.as_dict() if self.synergy else None,
            "monotherapy_effects": dict(self.monotherapy_effects),
            "hsi": self.hsi.as_dict() if self.hsi else None,
            "tox_events": list(self.tox_events),
            "tox_safe": self.tox_safe,
            "stats": [
                {
                    "entity_id": s.entity_id,
                    "p_value": s.test.p_value,
                    "effect": s.test.effect.cohens_d,
                    "relative_change": s.relative_change,
                    "significant": s.test.significant,
                }
                for s in self.stats
            ],
            "targets": [
                {"entity_id": t.entity_id, "name": t.name, "score": t.score}
                for t in self.target_scores[:8]
            ],
            "ai_recommendations": list(self.ai_recommendations),
            "literature": self.literature.as_dict() if self.literature else None,
            "report_markdown_chars": len(self.report_markdown),
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Deterministic NL → goal parser
# ---------------------------------------------------------------------------


_READOUT_ALIASES = {
    "erk": "ERK",
    "mapk": "ERK",
    "egfr": "EGFR",
    "ras": "RAS",
    "raf": "RAF",
    "mek": "MEK",
    "braf": "RAF",
}


def parse_research_goal(
    text: str,
    *,
    defaults: Optional[ResearchGoal] = None,
    llm: Optional[LLMAdapter] = None,
) -> GoalParseResult:
    """
    Rule-based goal parser with optional LLM refinement.

    Recognises drug-count, readout species, oncogene background, toxicity
    constraints, and disease context from free text.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Research goal text must be non-empty")

    base = defaults or ResearchGoal(text=raw)
    goal = ResearchGoal(
        text=raw,
        readout=base.readout,
        oncogenes=base.oncogenes,
        disease=base.disease,
        n_drugs=base.n_drugs,
        drug_candidates=base.drug_candidates,
        dose=base.dose,
        t_start=base.t_start,
        t_end=base.t_end,
        t_sim=base.t_sim,
        dt=base.dt,
        tox_threshold=base.tox_threshold,
        halt_overactivation=base.halt_overactivation,
        require_tox_safe=base.require_tox_safe,
        ensemble_members=base.ensemble_members,
        patient_id=base.patient_id,
    )
    rules: List[str] = []
    low = raw.lower()
    confidence = 0.45

    # Drug count
    if re.search(r"\b(two|2)[-\s]?drug\b", low) or "combination" in low or "combo" in low:
        goal.n_drugs = 2
        rules.append("n_drugs=2 from combination language")
        confidence += 0.12
    elif re.search(r"\b(single|mono|one|1)[-\s]?drug\b", low):
        goal.n_drugs = 1
        rules.append("n_drugs=1 from monotherapy language")
        confidence += 0.1
    elif re.search(r"\b(three|3)[-\s]?drug\b", low):
        goal.n_drugs = 3
        rules.append("n_drugs=3")
        confidence += 0.08

    # Readout
    for key, sym in _READOUT_ALIASES.items():
        if re.search(rf"\b{key}\b", low):
            if "over" in low or "halt" in low or "inhibit" in low or "reduc" in low:
                goal.readout = sym
                rules.append(f"readout={sym}")
                confidence += 0.1
                break
    if "erk" in low:
        goal.readout = "ERK"
        if "readout=ERK" not in rules:
            rules.append("readout=ERK")

    # Oncogene / disease background
    oncos: List[str] = []
    if "egfr" in low:
        oncos.append("EGFR")
    if re.search(r"\bras\b", low) or "kras" in low:
        oncos.append("RAS")
    if "raf" in low or "braf" in low:
        oncos.append("RAF")
    if oncos:
        goal.oncogenes = tuple(dict.fromkeys(oncos))
        rules.append(f"oncogenes={goal.oncogenes}")
        confidence += 0.1
    if "cancer" in low or "tumor" in low or "tumour" in low or "oncogen" in low or "mutat" in low:
        goal.disease = "cancer"
        rules.append("disease=cancer")
        confidence += 0.08
    if "wild-type" in low or "healthy" in low or "no disease" in low:
        goal.disease = "none"
        rules.append("disease=none")

    # Toxicity
    if "toxic" in low or "safety" in low or "adverse" in low:
        goal.require_tox_safe = True
        rules.append("require_tox_safe")
        confidence += 0.08
        m = re.search(r"threshold\s*[:=]?\s*([0-9]*\.?[0-9]+)", low)
        if m:
            goal.tox_threshold = float(m.group(1))
            rules.append(f"tox_threshold={goal.tox_threshold}")

    if "halt" in low or "suppress" in low or "reduc" in low or "over-activ" in low or "overactiv" in low:
        goal.halt_overactivation = True
        rules.append("halt_overactivation")
        confidence += 0.05

    # Candidate drugs mentioned explicitly
    cands = []
    for sym in ("MEK", "EGFR", "RAF", "RAS", "ERK"):
        if re.search(rf"\b{sym.lower()}\b", low) and sym != goal.readout:
            cands.append(sym)
    if cands:
        # Keep mentioned inhibitors first, pad with defaults
        merged = list(dict.fromkeys(cands + list(goal.drug_candidates)))
        goal.drug_candidates = tuple(merged[:5])
        rules.append(f"drug_candidates={goal.drug_candidates}")

    llm_refined = False
    if llm is not None:
        try:
            prompt = (
                "Extract JSON with keys readout,n_drugs,oncogenes,disease from goal:\n"
                f"{raw}\n"
                f"Current parse: {goal.as_dict()}"
            )
            reply = llm.complete(prompt, system="You refine VOIDSIGNAL research goals.")
            # Best-effort key=value scrape; ignore failures
            m = re.search(r"readout[\"'\s:=]+([A-Za-z0-9_]+)", reply, re.I)
            if m:
                goal.readout = m.group(1).upper()
                llm_refined = True
                rules.append("llm_refined_readout")
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLM goal refinement skipped: %s", exc)

    confidence = max(0.0, min(1.0, confidence))
    return GoalParseResult(goal=goal, confidence=confidence, matched_rules=rules, llm_refined=llm_refined)


def _formulate_hypothesis(goal: ResearchGoal) -> str:
    onco = "+".join(goal.oncogenes) if goal.oncogenes else "wild-type"
    if goal.n_drugs >= 2:
        return (
            f"In a {onco}-driven {goal.disease} signalling background, a dual "
            f"{'/'.join(goal.drug_candidates[:2])} inhibition regimen can suppress "
            f"{goal.readout} over-activation below pathogenic levels while respecting "
            f"toxicity threshold {goal.tox_threshold:g}."
        )
    return (
        f"Selective inhibition of {goal.drug_candidates[0]} in a {onco} background "
        f"will reduce steady-state {goal.readout} without breaching toxicity limits."
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class BiologicalAgentPlanner:
    """
    End-to-end autonomous experiment planner.

    Typical usage::

        planner = BiologicalAgentPlanner()
        result = planner.run(
            "Find a two-drug combination that halts ERK over-activation "
            "in a mutated EGFR background without exceeding the toxicity threshold"
        )
        print(result.report_markdown)
    """

    def __init__(
        self,
        *,
        network_factory: Optional[Callable[[], Tuple[SignalingNetwork, Dict[str, str]]]] = None,
        literature: Optional[LiteratureReasoner] = None,
        reporter: Optional[ScientificReportGenerator] = None,
        llm: Optional[LLMAdapter] = None,
        sim_config: Optional[SimulationConfig] = None,
    ) -> None:
        self.network_factory = network_factory or build_demo_mapk
        self.literature = literature or LiteratureReasoner()
        self.reporter = reporter or ScientificReportGenerator()
        self.llm = llm
        self.sim_config = sim_config

    # -- planning -----------------------------------------------------------

    def plan(self, goal_text: str, *, defaults: Optional[ResearchGoal] = None) -> ExperimentPlan:
        parse = parse_research_goal(goal_text, defaults=defaults, llm=self.llm)
        goal = parse.goal
        hypothesis = _formulate_hypothesis(goal)
        steps: List[ExperimentStep] = [
            ExperimentStep(
                StepKind.PARSE_GOAL,
                "Parse research objective into structured goal",
                {"confidence": parse.confidence},
            ),
            ExperimentStep(StepKind.BUILD_NETWORK, "Instantiate baseline signalling network"),
            ExperimentStep(
                StepKind.DISEASE_PRESET,
                f"Apply disease preset '{goal.disease}' with oncogenes {goal.oncogenes}",
                {"disease": goal.disease, "oncogenes": list(goal.oncogenes)},
            ),
            ExperimentStep(
                StepKind.TARGET_PRIORITIZE,
                "Rank therapeutic targets via GAT / AIScientistReasoner",
            ),
        ]
        if goal.n_drugs >= 2:
            steps.append(
                ExperimentStep(
                    StepKind.DRUG_COMBINATION,
                    "Screen two-drug combinations (Bliss/Loewe) under disease background",
                    {"candidates": list(goal.drug_candidates), "dose": goal.dose},
                )
            )
        else:
            steps.append(
                ExperimentStep(
                    StepKind.DRUG_MONOTHERAPY,
                    "Screen monotherapy doses against readout",
                    {"candidates": list(goal.drug_candidates), "dose": goal.dose},
                )
            )
        steps.extend(
            [
                ExperimentStep(
                    StepKind.ENSEMBLE_SENSITIVITY,
                    f"Monte Carlo ensemble (n={goal.ensemble_members}) for uncertainty bands",
                    {"n_members": goal.ensemble_members},
                ),
                ExperimentStep(
                    StepKind.TOXICOLOGY_AUDIT,
                    f"Audit trajectories against toxicity threshold {goal.tox_threshold:g}",
                    {"threshold": goal.tox_threshold},
                ),
                ExperimentStep(
                    StepKind.STATISTICAL_AUDIT,
                    "Welch t-tests on baseline vs treated readout windows",
                ),
                ExperimentStep(
                    StepKind.LITERATURE_ALIGN,
                    "Compute Literature Alignment Score against curated + KEGG evidence",
                ),
                ExperimentStep(
                    StepKind.SYNTHESIZE_REPORT,
                    "Generate Markdown scientific research brief",
                ),
            ]
        )
        return ExperimentPlan(goal=goal, steps=steps, hypothesis=hypothesis, parse=parse)

    # -- execution ----------------------------------------------------------

    def run(
        self,
        goal_text: str,
        *,
        defaults: Optional[ResearchGoal] = None,
        plan: Optional[ExperimentPlan] = None,
    ) -> PlanExecutionResult:
        experiment = plan or self.plan(goal_text, defaults=defaults)
        goal = experiment.goal
        cfg = self.sim_config or SimulationConfig(
            t_end=goal.t_sim,
            dt=goal.dt,
            record_every=max(1, int(round(1.0 / max(goal.dt, 1e-6)))),
        )
        result = PlanExecutionResult(plan=experiment)
        step_map = {s.kind: s for s in experiment.steps}

        def mark(kind: StepKind, status: str, summary: str = "", **artifacts: Any) -> None:
            st = step_map.get(kind)
            if st is None:
                return
            st.status = status
            st.result_summary = summary
            st.artifacts.update(artifacts)

        try:
            mark(StepKind.PARSE_GOAL, "done", f"confidence={experiment.parse.confidence:.2f}")

            template, ids = self.network_factory()
            result.ids = dict(ids)
            mark(StepKind.BUILD_NETWORK, "done", f"nodes={len(ids)}")

            # --- trajectories ---
            baseline_net = copy.deepcopy(template)
            result.baseline = DualEngineSimulator(baseline_net).run_ode(cfg)

            disease_net = copy.deepcopy(template)
            dis_engine = DualEngineSimulator(disease_net)
            if goal.disease == "cancer":
                pheno = build_cancer_phenotype(
                    disease_net,
                    CancerSignalingConfig(
                        oncogenes=goal.oncogenes,
                        expression_level=2.8,
                        attenuate_negative_feedback=True,
                        feedback_scale=0.05,
                        survival_nodes=(goal.readout,),
                        survival_production_boost=1.8,
                    ),
                )
                pheno.load_into(dis_engine)
                mark(StepKind.DISEASE_PRESET, "done", pheno.name)
            else:
                mark(StepKind.DISEASE_PRESET, "skipped", "no disease preset")
            result.disease = dis_engine.run_ode(cfg)

            # --- target prioritization ---
            tensors = build_graph_tensors(disease_net)
            model = TargetDiscoveryModel(seed=21, hidden_dim=12, embed_dim=6)
            scores = model.predict(tensors)
            result.target_scores = scores
            reasoner = AIScientistReasoner(model)
            ai = reasoner.recommend(tensors, disease_net, top_k=3, include_links=False)
            result.ai_recommendations = list(ai.get("recommendations") or [])
            mark(
                StepKind.TARGET_PRIORITIZE,
                "done",
                f"top={scores[0].name if scores else '?'}",
                top=[s.name for s in scores[:5]],
            )

            # Prefer GAT ranks intersecting requested candidates
            ranked_names = [s.name for s in scores]
            ordered_cands = list(
                dict.fromkeys(
                    [n for n in ranked_names if n in goal.drug_candidates]
                    + list(goal.drug_candidates)
                )
            )

            readout_id = ids.get(goal.readout)
            if readout_id is None:
                for e in disease_net.registry.entities():
                    if e.name == goal.readout:
                        readout_id = e.entity_id
                        break
            if readout_id is None:
                raise KeyError(f"Readout {goal.readout!r} not in network")

            # --- pharmacology (disease-aware DualEngine runs) ---
            cancer_cfg = CancerSignalingConfig(
                oncogenes=goal.oncogenes,
                expression_level=2.8,
                attenuate_negative_feedback=True,
                feedback_scale=0.05,
                survival_nodes=(goal.readout,),
                survival_production_boost=1.8,
            )

            def make_agent(target_name: str, dose: float) -> DrugAgent:
                tid = ids.get(target_name, target_name)
                if tid not in template.registry:
                    for e in template.registry.entities():
                        if e.name == target_name:
                            tid = e.entity_id
                            break
                edges = [
                    e.edge_id for e in template.active_edges() if e.source_id == tid
                ]
                return DrugAgent(
                    target_id=tid,
                    mechanism=Mechanism.COMPETITIVE,
                    name=f"agent:{target_name}",
                    ki=0.4,
                    plateau_concentration=dose,
                    t_start=goal.t_start,
                    t_end=goal.t_end,
                    edge_ids=list(edges),
                    pk=PharmacokineticProfile(
                        dose=dose,
                        kel=0.12,
                        dosing_times=[goal.t_start],
                        hard_washout=True,
                    ),
                )

            def open_disease_engine() -> Tuple[SignalingNetwork, DualEngineSimulator]:
                net = copy.deepcopy(template)
                eng = DualEngineSimulator(net)
                if goal.disease == "cancer":
                    build_cancer_phenotype(net, cancer_cfg).load_into(eng)
                return net, eng

            def clone_agent(proto: DrugAgent, net: SignalingNetwork) -> DrugAgent:
                agent = copy.deepcopy(proto)
                agent.edge_ids = [
                    e.edge_id for e in net.active_edges() if e.source_id == agent.target_id
                ]
                agent._base_kinetics = None  # noqa: SLF001
                agent._base_rates = {}  # noqa: SLF001
                agent.applied = False
                return agent

            def run_readout(agents: Sequence[DrugAgent]) -> float:
                _net, eng = open_disease_engine()
                for proto in agents:
                    eng.add_hook(clone_agent(proto, _net).apply)
                traj = eng.run_ode(cfg)
                return float(traj.final_concentrations().get(readout_id, 0.0))

            def frac_inhibition(level: float, baseline: float) -> float:
                return max(0.0, min(1.0, (baseline - level) / max(baseline, 1e-12)))

            disease_final = result.disease.final_concentrations().get(readout_id, 0.0)

            if goal.n_drugs >= 2 and len(ordered_cands) >= 2:
                mark(StepKind.DRUG_COMBINATION, "running")
                best: Optional[SynergyResult] = None
                best_pair: Tuple[str, str] = (ordered_cands[0], ordered_cands[1])
                mono: Dict[str, float] = {}
                pairs: List[Tuple[str, str]] = []
                for i, a in enumerate(ordered_cands[:4]):
                    for b in ordered_cands[i + 1 : 4]:
                        pairs.append((a, b))
                if not pairs:
                    pairs = [(ordered_cands[0], ordered_cands[1])]
                for a_name, b_name in pairs:
                    agent_a = make_agent(a_name, goal.dose)
                    agent_b = make_agent(b_name, goal.dose * 0.85)
                    ra = run_readout([agent_a])
                    rb = run_readout([agent_b])
                    rab = run_readout([agent_a, agent_b])
                    ea = frac_inhibition(ra, disease_final)
                    eb = frac_inhibition(rb, disease_final)
                    eab = frac_inhibition(rab, disease_final)
                    expected = bliss_independence(ea, eb)
                    bliss_score = eab - expected
                    syn = SynergyResult(
                        effect_a=ea,
                        effect_b=eb,
                        effect_ab=eab,
                        bliss_expected=expected,
                        bliss_score=bliss_score,
                        loewe_ci=None,
                        interpretation=interpret_synergy(bliss_score, None),
                        doses={"a": goal.dose, "b": goal.dose * 0.85},
                    )
                    mono[a_name] = ea
                    mono[b_name] = eb
                    if best is None or eab > best.effect_ab or (
                        abs(eab - best.effect_ab) < 1e-9 and bliss_score > best.bliss_score
                    ):
                        best = syn
                        best_pair = (a_name, b_name)
                assert best is not None
                result.synergy = best
                result.monotherapy_effects = mono
                result.best_agents = [
                    make_agent(best_pair[0], goal.dose),
                    make_agent(best_pair[1], goal.dose * 0.85),
                ]
                mark(
                    StepKind.DRUG_COMBINATION,
                    "done",
                    f"{best_pair[0]}+{best_pair[1]} effect_ab={best.effect_ab:.3f} "
                    f"bliss={best.bliss_score:.3f} ({best.interpretation})",
                    pair=list(best_pair),
                )
                if StepKind.DRUG_MONOTHERAPY in step_map:
                    mark(StepKind.DRUG_MONOTHERAPY, "skipped")
            else:
                mark(StepKind.DRUG_MONOTHERAPY, "running")
                best_name = ordered_cands[0]
                best_effect = -1.0
                for name in ordered_cands[:4]:
                    agent = make_agent(name, goal.dose)
                    final = run_readout([agent])
                    effect = frac_inhibition(final, disease_final)
                    result.monotherapy_effects[name] = effect
                    if effect > best_effect:
                        best_effect = effect
                        best_name = name
                result.best_agents = [make_agent(best_name, goal.dose)]
                mark(
                    StepKind.DRUG_MONOTHERAPY,
                    "done",
                    f"best={best_name} effect={best_effect:.3f}",
                )
                if StepKind.DRUG_COMBINATION in step_map:
                    mark(StepKind.DRUG_COMBINATION, "skipped")

            # Treated trajectory with best agents + tox monitor
            rx_net, rx_engine = open_disease_engine()
            agents = [clone_agent(proto, rx_net) for proto in result.best_agents]
            for agent in agents:
                rx_engine.add_hook(agent.apply)
            result.best_agents = agents

            panel = SafetyTargetPanel(
                [
                    SafetyTarget(
                        entity_id=readout_id,
                        pathway=SafetyPathway.CUSTOM,
                        threshold=goal.tox_threshold,
                        direction=ThresholdDirection.ABOVE,
                        name=goal.readout,
                    )
                ]
            )
            tox = ToxicologyMonitor(panel, sample_every=1, cooldown=2.0)
            rx_engine.add_hook(tox.observe)
            result.treated = rx_engine.run_ode(cfg)
            result.tox_events = [e.as_dict() for e in tox.events]
            result.tox_safe = len(result.tox_events) == 0
            mark(
                StepKind.TOXICOLOGY_AUDIT,
                "done",
                f"events={len(result.tox_events)} safe={result.tox_safe}",
            )

            result.hsi = homeostatic_shift_index(
                result.baseline, result.treated, rx_net, threshold=0.75
            )

            # Ensemble on disease network (serial for portability)
            try:
                ens_net, _ens_eng = open_disease_engine()
                runner = EnsembleRunner(ens_net, cfg, executor="serial")
                result.ensemble = runner.monte_carlo(
                    max(3, min(goal.ensemble_members, 8)),
                    seed=7,
                    initial_noise_sigma=0.08,
                    lognormal_param_sigma=0.12,
                    level=0.9,
                )
                mark(
                    StepKind.ENSEMBLE_SENSITIVITY,
                    "done",
                    f"success={result.ensemble.n_success}/{result.ensemble.n_members}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ensemble failed: %s", exc)
                mark(StepKind.ENSEMBLE_SENSITIVITY, "failed", str(exc))

            # Stats
            try:
                cmp = compare_trajectories(
                    result.baseline, result.treated, readout_id, burn_in=goal.t_sim * 0.5
                )
                result.stats = [cmp]
                mark(
                    StepKind.STATISTICAL_AUDIT,
                    "done",
                    f"p={cmp.test.p_value:.3g} d={cmp.test.effect.cohens_d:.3g} "
                    f"Δrel={cmp.relative_change:.3g}",
                )
            except Exception as exc:  # noqa: BLE001
                mark(StepKind.STATISTICAL_AUDIT, "failed", str(exc))

            # Literature
            score_map = {t.entity_id: t.score for t in result.target_scores}
            syn_pair = None
            if len(result.best_agents) >= 2:
                names = [
                    rx_net.registry.get(a.target_id).name for a in result.best_agents
                ]
                syn_pair = (names[0], names[1])
            result.literature = self.literature.align(
                rx_net, score_map, synergy_pair=syn_pair
            )
            mark(
                StepKind.LITERATURE_ALIGN,
                "done",
                result.literature.summary,
                las=result.literature.las,
            )

            # Objective evaluation
            treated_ss = result.treated.final_concentrations().get(readout_id, 0.0)
            reduced = treated_ss < disease_final * 0.85 if goal.halt_overactivation else True
            tox_ok = result.tox_safe if goal.require_tox_safe else True
            if not tox_ok and treated_ss <= goal.tox_threshold:
                tox_ok = True
                result.notes.append(
                    "Transient tox flags observed but final readout within threshold."
                )
            result.objective_met = bool(reduced and tox_ok)
            result.success = True
            result.notes.append(
                f"Disease {goal.readout}={disease_final:.3f} → treated={treated_ss:.3f} "
                f"(reduction={(disease_final - treated_ss) / max(disease_final, 1e-12):.1%})"
            )

            ctx = ReportContext(
                plan=experiment,
                result=result,
                network=rx_net,
            )
            result.report_markdown = self.reporter.generate(ctx)
            mark(
                StepKind.SYNTHESIZE_REPORT,
                "done",
                f"chars={len(result.report_markdown)}",
            )
            result.metadata = {
                "disease_readout": disease_final,
                "treated_readout": treated_ss,
                "readout_id": readout_id,
            }
        except Exception as exc:
            logger.exception("Planner execution failed: %s", exc)
            result.success = False
            result.notes.append(f"FAILED: {exc}")
            for st in experiment.steps:
                if st.status in {"pending", "running"}:
                    st.status = "skipped"
            # Still emit a minimal failure report
            try:
                result.report_markdown = self.reporter.generate(
                    ReportContext(plan=experiment, result=result)
                )
            except Exception:  # noqa: BLE001
                result.report_markdown = f"# Failed run\n\n{exc}\n"

        return result
