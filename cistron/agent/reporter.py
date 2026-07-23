"""
Automated scientific report & hypothesis generator for CISTRON Phase 10.

Produces structured Markdown research briefs from planner execution artefacts,
wrapped with plain-language executive summaries (Phase 15 UX translator).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json

from cistron.ui.translator import (
    MetricTranslator,
    build_executive_summary,
    compose_progressive_brief,
)


@dataclass
class ReportContext:
    """Bundle passed from :class:`BiologicalAgentPlanner` into the reporter."""

    plan: Any
    result: Any
    network: Any = None
    title: str = "CISTRON Autonomous Research Brief"
    author: str = "BiologicalAgentPlanner"
    metadata: Dict[str, Any] = field(default_factory=dict)
    progressive_disclosure: bool = True
    """When True, lead with executive summary and collapse raw telemetry."""


class ScientificReportGenerator:
    """
    Render a complete Markdown research brief:

    Executive Summary → (collapsible) Abstract & Hypothesis → Experimental Design →
    Results & Statistics → Target Rationale → Literature Alignment → Conclusions.
    """

    def __init__(self, translator: Optional[MetricTranslator] = None) -> None:
        self.translator = translator or MetricTranslator()

    def generate(self, ctx: ReportContext) -> str:
        plan = ctx.plan
        result = ctx.result
        goal = plan.goal
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        body_sections: List[str] = [
            f"# {ctx.title}",
            "",
            f"**Generated:** {now}  ",
            f"**Agent:** {ctx.author}  ",
            f"**Patient / case id:** `{goal.patient_id}`  ",
            f"**Objective met:** {'YES' if result.objective_met else 'NO'}  ",
            "",
            "---",
            "",
            self._abstract(plan, result),
            "",
            self._hypothesis(plan),
            "",
            self._experimental_design(plan, result),
            "",
            self._results(result, goal),
            "",
            self._statistics(result),
            "",
            self._target_rationale(result),
            "",
            self._literature(result),
            "",
            self._conclusions(plan, result),
            "",
            self._appendix(plan, result),
        ]
        body = "\n".join(body_sections)

        if not ctx.progressive_disclosure:
            return body

        meta = result.metadata or {}
        hsi = float(result.hsi.hsi) if result.hsi is not None else None
        hsi_pre = None
        if isinstance(meta.get("pre_hsi"), (int, float)):
            hsi_pre = float(meta["pre_hsi"])
        elif isinstance(ctx.metadata.get("pre_hsi"), (int, float)):
            hsi_pre = float(ctx.metadata["pre_hsi"])
        las = float(result.literature.las) if result.literature is not None else None
        executive = build_executive_summary(
            hsi=hsi,
            hsi_pre=hsi_pre,
            las=las,
            readout=str(goal.readout),
            readout_pre=meta.get("disease_readout"),
            readout_post=meta.get("treated_readout"),
            objective_met=bool(result.objective_met),
            patient_id=str(goal.patient_id),
        )
        header = [
            f"# {ctx.title}",
            "",
            f"**Generated:** {now}  ",
            f"**Agent:** {ctx.author}  ",
            f"**Patient / case id:** `{goal.patient_id}`  ",
            "",
        ]
        return "\n".join(header) + "\n" + compose_progressive_brief(
            executive=executive,
            body_markdown=body,
        )

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def _abstract(self, plan: Any, result: Any) -> str:
        goal = plan.goal
        lit = result.literature
        las = f"{lit.las:.3f}" if lit is not None else "n/a"
        agents = ", ".join(
            f"{a.name} (C0={a.plateau_concentration or a.pk.dose:g})"
            for a in result.best_agents
        ) or "none selected"
        hsi = f"{result.hsi.hsi:.3f}" if result.hsi is not None else "n/a"
        from cistron.ui.translator import translate_metric

        hsi_human = ""
        if result.hsi is not None:
            hsi_human = f" ({translate_metric('HSI', result.hsi.hsi).badge_label})"
        las_human = ""
        if lit is not None:
            las_human = f" ({translate_metric('LAS', lit.las).badge_label})"
        return "\n".join(
            [
                "## Abstract",
                "",
                f"We tasked an autonomous CISTRON agent with the objective: "
                f"*\"{goal.text}\"*. "
                f"Working in a `{goal.disease}` phenotype with oncogene background "
                f"**{'+'.join(goal.oncogenes)}**, the planner selected **{agents}** "
                f"to modulate readout **{goal.readout}**. "
                f"Cellular Health / Sickness Score reached **HSI={hsi}**{hsi_human}, "
                f"Literature Confidence Score **LAS={las}**{las_human}, and the stated "
                f"safety / efficacy objective was "
                f"**{'satisfied' if result.objective_met else 'not satisfied'}**.",
            ]
        )

    def _hypothesis(self, plan: Any) -> str:
        return "\n".join(
            [
                "## Hypothesis",
                "",
                plan.hypothesis,
                "",
                f"*Parse confidence:* {plan.parse.confidence:.2f}  ",
                f"*Matched rules:* {', '.join(plan.parse.matched_rules) or 'none'}",
            ]
        )

    def _experimental_design(self, plan: Any, result: Any) -> str:
        goal = plan.goal
        lines = [
            "## Experimental Design",
            "",
            "| Parameter | Value |",
            "|-----------|-------|",
            f"| Readout | `{goal.readout}` |",
            f"| Disease preset | `{goal.disease}` |",
            f"| Oncogenes | {', '.join(goal.oncogenes)} |",
            f"| Drug count | {goal.n_drugs} |",
            f"| Candidates | {', '.join(goal.drug_candidates)} |",
            f"| Dose C₀ | {goal.dose:g} |",
            f"| Wash-in / washout | t∈[{goal.t_start:g}, {goal.t_end:g}] |",
            f"| Horizon / dt | {goal.t_sim:g} / {goal.dt:g} |",
            f"| Toxicity threshold | {goal.tox_threshold:g} |",
            f"| Ensemble members | {goal.ensemble_members} |",
            "",
            "### Workflow steps",
            "",
        ]
        for i, step in enumerate(plan.steps, start=1):
            lines.append(
                f"{i}. **{step.kind.value}** — {step.description} "
                f"[{step.status}] {step.result_summary}"
            )
        if result.best_agents:
            lines.extend(["", "### Selected dosing regimen", ""])
            for a in result.best_agents:
                lines.append(
                    f"- `{a.name}` → target `{a.target_id[:12]}…` "
                    f"mechanism={a.mechanism.value}, "
                    f"C0={a.plateau_concentration or a.pk.dose:g}, "
                    f"window=[{a.t_start:g}, {a.t_end}]"
                )
        lines.extend(
            [
                "",
                "Spatial routing uses the default DualEngine / MassActionRHS "
                "compartment boundary conditions inherited from the Phase 1–3 stack; "
                "no additional spatial overrides were injected by the agent.",
            ]
        )
        return "\n".join(lines)

    def _results(self, result: Any, goal: Any) -> str:
        lines = ["## Results", ""]
        meta = result.metadata or {}
        if "disease_readout" in meta:
            lines.append(
                f"- Disease steady-state **{goal.readout}** = "
                f"**{meta['disease_readout']:.4f}**"
            )
        if "treated_readout" in meta:
            lines.append(
                f"- Treated steady-state **{goal.readout}** = "
                f"**{meta['treated_readout']:.4f}**"
            )
        if result.hsi is not None:
            from cistron.ui.translator import translate_metric

            th = translate_metric("HSI", result.hsi.hsi)
            lines.append(
                f"- {th.markdown_inline()} "
                f"(collapse_flag={result.hsi.collapse_flag})"
            )
            if result.hsi.node_shifts:
                lines.append("- Top node shifts:")
                for s in result.hsi.node_shifts[:5]:
                    lines.append(
                        f"  - {s.name}: Δrel={s.relative_delta:.3f}, "
                        f"contrib={s.contribution:.3f}"
                    )
        if result.synergy is not None:
            syn = result.synergy
            lines.extend(
                [
                    "",
                    "### Combination pharmacology",
                    "",
                    f"- Effect A / B / AB = {syn.effect_a:.3f} / {syn.effect_b:.3f} / "
                    f"{syn.effect_ab:.3f}",
                    f"- Bliss expected = {syn.bliss_expected:.3f}, "
                    f"Bliss excess = {syn.bliss_score:.3f}",
                    f"- Loewe CI = {syn.loewe_ci if syn.loewe_ci is not None else 'n/a'}",
                    f"- Interpretation: **{syn.interpretation}**",
                ]
            )
        if result.monotherapy_effects:
            lines.extend(["", "### Monotherapy effects", ""])
            for name, eff in sorted(
                result.monotherapy_effects.items(), key=lambda kv: kv[1], reverse=True
            ):
                lines.append(f"- {name}: fractional inhibition ≈ {eff:.3f}")
        lines.extend(
            [
                "",
                "### Toxicology",
                "",
                f"- Events flagged: **{len(result.tox_events)}**",
                f"- Tox-safe verdict: **{result.tox_safe}**",
            ]
        )
        for ev in result.tox_events[:5]:
            lines.append(
                f"  - t={ev.get('time')}: {ev.get('name')} "
                f"conc={ev.get('concentration')} > {ev.get('threshold')}"
            )
        if result.ensemble is not None:
            ens = result.ensemble
            lines.extend(
                [
                    "",
                    "### Ensemble uncertainty",
                    "",
                    f"- Members succeeded: {ens.n_success}/{ens.n_members}",
                ]
            )
        for note in result.notes:
            lines.append(f"- Note: {note}")
        return "\n".join(lines)

    def _statistics(self, result: Any) -> str:
        lines = [
            "## Statistical Auditing",
            "",
            "| Entity | p-value | Cohen's d | Δrel | Significant |",
            "|--------|---------|-----------|------|-------------|",
        ]
        if not result.stats:
            lines.append("| — | — | — | — | — |")
            lines.append("")
            lines.append("_No trajectory comparisons recorded._")
            return "\n".join(lines)
        for s in result.stats:
            lines.append(
                f"| `{s.entity_id[:8]}…` | {s.test.p_value:.3g} | "
                f"{s.test.effect.cohens_d:.3g} | {s.relative_change:.3g} | "
                f"{s.test.significant} |"
            )
        lines.append("")
        lines.append(
            "Tests use Welch's *t* on post burn-in samples "
            "(`compare_trajectories`, Phase 6 statistics engine)."
        )
        return "\n".join(lines)

    def _target_rationale(self, result: Any) -> str:
        lines = ["## Target Rationale (GAT + AIScientistReasoner)", ""]
        if result.target_scores:
            lines.extend(
                [
                    "| Rank | Symbol | Score |",
                    "|------|--------|-------|",
                ]
            )
            for i, t in enumerate(result.target_scores[:8], start=1):
                lines.append(f"| {i} | {t.name} | {t.score:.4f} |")
            lines.append("")
        if result.ai_recommendations:
            lines.append("### Edge-occlusion / feature attributions")
            lines.append("")
            for rec in result.ai_recommendations:
                lines.append(f"**{rec.get('name', rec.get('entity_id'))}** — score {rec.get('score')}")
                lines.append("")
                summary = rec.get("summary")
                if summary:
                    lines.append(summary)
                    lines.append("")
                feats = rec.get("feature_attributions") or []
                if feats:
                    lines.append("Feature importance:")
                    for f in feats[:5]:
                        lines.append(
                            f"- {f.get('feature_name')}: "
                            f"value={f.get('value')}, attr={f.get('attribution')}"
                        )
                    lines.append("")
                edges = rec.get("edge_attributions") or []
                if edges:
                    lines.append("Critical edges:")
                    for e in edges[:5]:
                        lines.append(
                            f"- {e.get('source_name')}→{e.get('target_name')}: "
                            f"Δ={e.get('attribution')}"
                        )
                    lines.append("")
        else:
            lines.append("_No AIScientistReasoner recommendations available._")
        return "\n".join(lines)

    def _literature(self, result: Any) -> str:
        lit = result.literature
        lines = ["## Literature Alignment", ""]
        if lit is None:
            lines.append("_Literature reasoner did not run._")
            return "\n".join(lines)
        lines.append(lit.summary)
        lines.append("")
        from cistron.ui.translator import translate_metric

        tl = translate_metric("LAS", lit.las)
        lines.append(f"- {tl.markdown_inline()}")
        lines.append(f"- Pathway coverage = {lit.pathway_coverage:.3f}")
        if lit.synergy_alignment is not None:
            lines.append(f"- Synergy literature alignment = {lit.synergy_alignment:.3f}")
        lines.append(f"- Evidence hits = {lit.n_evidence_hits} / corpus {lit.corpus_size}")
        lines.append("")
        lines.append("| Symbol | LASᵢ | Pathway | Drug-target | PPI |")
        lines.append("|--------|------|---------|-------------|-----|")
        for t in lit.target_alignments[:8]:
            lines.append(
                f"| {t.symbol} | {t.las_component:.3f} | "
                f"{'Y' if t.pathway_hit else 'n'} | "
                f"{'Y' if t.drug_target_hit else 'n'} | "
                f"{'Y' if t.ppi_hit else 'n'} |"
            )
        # Top evidence quotes
        quotes: List[str] = []
        for t in lit.target_alignments[:3]:
            for ev in t.matched_evidence[:2]:
                quotes.append(f"- ({ev.source}) {ev.claim}")
        if quotes:
            lines.extend(["", "### Supporting evidence", ""] + quotes)
        return "\n".join(lines)

    def _conclusions(self, plan: Any, result: Any) -> str:
        goal = plan.goal
        verdict = (
            "The autonomous campaign **met** the stated efficacy and safety constraints."
            if result.objective_met
            else "The autonomous campaign **did not fully meet** the stated objective; "
            "see tox flags / residual readout above."
        )
        next_steps = [
            "Validate top combination in an expanded dose-response grid.",
            "Re-run Morris / Sobol sensitivity on selected kinetic parameters.",
            "Cross-check LAS hits against live UniProt / STRING when network access is available.",
        ]
        lines = [
            "## Conclusions",
            "",
            verdict,
            "",
            "### Recommended next experiments",
            "",
        ]
        for i, s in enumerate(next_steps, start=1):
            lines.append(f"{i}. {s}")
        lines.extend(
            [
                "",
                f"Primary readout of interest remains **{goal.readout}** under "
                f"**{'+'.join(goal.oncogenes)}** pressure.",
            ]
        )
        return "\n".join(lines)

    def _appendix(self, plan: Any, result: Any) -> str:
        payload = {}
        try:
            payload = result.as_dict()
        except Exception:  # noqa: BLE001
            payload = {"error": "as_dict failed"}
        # Keep appendix compact
        compact = {
            "success": payload.get("success"),
            "objective_met": payload.get("objective_met"),
            "best_agents": payload.get("best_agents"),
            "hsi": (payload.get("hsi") or {}).get("hsi") if payload.get("hsi") else None,
            "las": (payload.get("literature") or {}).get("las") if payload.get("literature") else None,
            "tox_safe": payload.get("tox_safe"),
        }
        return "\n".join(
            [
                "## Appendix — machine-readable summary",
                "",
                "```json",
                json.dumps(compact, indent=2, default=str),
                "```",
            ]
        )
