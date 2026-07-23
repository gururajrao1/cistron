"""
Plain-language metric translation & progressive disclosure (UX layer).

Sits *above* raw simulation numerics: every helper returns human-readable
labels / badges / tooltips while leaving original floats untouched for
MassActionRHS, optimizers, and statistical engines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import math
import re


class BadgeTone(str, Enum):
    HEALTHY = "healthy"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    CRITICAL = "critical"
    STRONG = "strong"
    WEAK = "weak"
    INFO = "info"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MetricDefinition:
    """Canonical glossary entry for one scientific abbreviation."""

    key: str
    short_label: str
    """UI-facing plain name, e.g. 'Cellular Health / Sickness Score'."""
    technical_name: str
    """Full technical expansion, e.g. 'Homeostatic Shift Index'."""
    tooltip: str
    """Hover / glossary definition (1–2 sentences)."""
    unit: str = ""
    lower_is_better: bool = True
    aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslatedMetric:
    """
    Human context for a single numeric (or string) observation.

    ``raw_value`` is always the unmodified input so solvers stay authoritative.
    """

    key: str
    raw_value: Any
    short_label: str
    technical_name: str
    tooltip: str
    badge_label: str
    badge_tone: BadgeTone
    badge_emoji: str
    plain_phrase: str
    unit: str = ""
    display_value: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "raw_value": self.raw_value,
            "short_label": self.short_label,
            "technical_name": self.technical_name,
            "tooltip": self.tooltip,
            "badge_label": self.badge_label,
            "badge_tone": self.badge_tone.value,
            "badge_emoji": self.badge_emoji,
            "plain_phrase": self.plain_phrase,
            "unit": self.unit,
            "display_value": self.display_value,
        }

    def markdown_inline(self) -> str:
        """Compact badge + value for Markdown briefs (raw number preserved)."""
        return (
            f"{self.badge_emoji} **{self.short_label}** "
            f"({self.key}={self.display_value}) — *{self.badge_label}*"
        )


# ---------------------------------------------------------------------------
# Glossary catalog
# ---------------------------------------------------------------------------

METRIC_CATALOG: Dict[str, MetricDefinition] = {
    "HSI": MetricDefinition(
        key="HSI",
        short_label="Cellular Health / Sickness Score",
        technical_name="Homeostatic Shift Index",
        tooltip=(
            "How far the cell's signaling steady-state has drifted from a healthy "
            "baseline. Near 0 means homeostasis; higher values mean progressive dysregulation."
        ),
        unit="",
        lower_is_better=True,
        aliases=("hsi", "homeostatic_shift", "homeostatic_shift_index"),
    ),
    "LAS": MetricDefinition(
        key="LAS",
        short_label="Literature Confidence Score",
        technical_name="Literature Alignment Score",
        tooltip=(
            "How well the agent's chosen targets and outcomes agree with published "
            "pathway / pharmacology literature. Higher means stronger scientific alignment."
        ),
        unit="",
        lower_is_better=False,
        aliases=("las", "literature_alignment", "literature_alignment_score"),
    ),
    "DG": MetricDefinition(
        key="DG",
        short_label="3D Binding Fit Strength",
        technical_name="Binding Free Energy (ΔG)",
        tooltip=(
            "Estimated Gibbs free energy of ligand–protein binding from the docking "
            "scorer. More negative values mean a tighter lock-and-key fit."
        ),
        unit="kcal/mol",
        lower_is_better=True,
        aliases=("dg", "delta_g", "deltag", "ΔG", "dG", "DELTA_G"),
    ),
    "KI": MetricDefinition(
        key="KI",
        short_label="Drug Concentration Threshold",
        technical_name="Inhibition Constant (Kᵢ)",
        tooltip=(
            "Equilibrium concentration at which the drug occupies half of its target "
            "sites. Lower Kᵢ means a more potent inhibitor."
        ),
        unit="M",
        lower_is_better=True,
        aliases=("ki", "k_i", "Ki", "K_i", "kd", "KD", "k_d"),
    ),
    "PSI": MetricDefinition(
        key="PSI",
        short_label="Gene Splicing Ratio",
        technical_name="Percent Spliced In",
        tooltip=(
            "Fraction of transcripts that include a given exon or isoform. "
            "PSI near 1 means the isoform dominates; near 0 means it is mostly skipped."
        ),
        unit="",
        lower_is_better=False,
        aliases=("psi", "percent_spliced_in", "splicing_ratio"),
    ),
    "PDS": MetricDefinition(
        key="PDS",
        short_label="Pathway Disruption Index",
        technical_name="Pathway Dysregulation Score",
        tooltip=(
            "Composite measure of how disrupted a functional pathway subgraph is "
            "relative to a healthy reference. Higher means more pathway damage."
        ),
        unit="",
        lower_is_better=True,
        aliases=("pds", "pathway_dysregulation", "pathway_dysregulation_score"),
    ),
    "ERK": MetricDefinition(
        key="ERK",
        short_label="Growth Signal Readout",
        technical_name="Extracellular signal-Regulated Kinase activity",
        tooltip=(
            "Downstream MAPK effector concentration / activity used as the primary "
            "oncogenic readout in MAPK-centric simulations."
        ),
        unit="a.u.",
        lower_is_better=True,
        aliases=("erk", "mapk1", "mapk3"),
    ),
    "EPSILON": MetricDefinition(
        key="EPSILON",
        short_label="T-cell Exhaustion Level",
        technical_name="Immune Exhaustion Coefficient (ε)",
        tooltip=(
            "How worn-out cytotoxic T cells are under checkpoint pressure "
            "(PD-1/CTLA-4/LAG-3). 0 = fully competent; 1 = fully exhausted."
        ),
        unit="",
        lower_is_better=True,
        aliases=("epsilon", "epsilon_exhaustion", "exhaustion", "ε", "eps_exhaustion"),
    ),
    "IC50": MetricDefinition(
        key="IC50",
        short_label="Peptide–MHC Binding Strength",
        technical_name="Half-maximal Inhibitory Concentration (IC50)",
        tooltip=(
            "Estimated peptide concentration needed for half-maximal MHC binding. "
            "Lower IC50 (nM) means a stronger neoantigen presentation candidate."
        ),
        unit="nM",
        lower_is_better=True,
        aliases=("ic50", "ic_50"),
    ),
    "TOX": MetricDefinition(
        key="TOX",
        short_label="Safety / Toxicity Load",
        technical_name="Toxicology Composite Index",
        tooltip=(
            "Aggregate on-target / off-pathway toxicity pressure from the live "
            "toxicology monitor. Higher means greater safety concern."
        ),
        unit="",
        lower_is_better=True,
        aliases=("tox", "toxicity", "toxicity_index"),
    ),
}

_ALIAS_INDEX: Dict[str, str] = {}
for _def in METRIC_CATALOG.values():
    _ALIAS_INDEX[_def.key.upper()] = _def.key
    for _a in _def.aliases:
        _ALIAS_INDEX[_a.upper()] = _def.key
    _ALIAS_INDEX[_def.short_label.upper()] = _def.key
    _ALIAS_INDEX[_def.technical_name.upper()] = _def.key


def normalize_metric_key(metric_name: str) -> str:
    """Map free-text / alias → canonical catalog key (e.g. 'ΔG' → 'DG')."""
    raw = (metric_name or "").strip()
    if not raw:
        return ""
    # Unicode delta variants
    cleaned = raw.replace("Δ", "D").replace("δ", "d").replace("ᵢ", "i").replace("ε", "EPSILON")
    cleaned = cleaned.replace(" ", "_")
    # Common symbol forms
    if cleaned.upper() in {"DG", "DELTA_G", "DELTA-G", "D_G"}:
        return "DG"
    if cleaned.upper() in {"KI", "K_I", "K-I"}:
        return "KI"
    key = _ALIAS_INDEX.get(cleaned.upper())
    if key:
        return key
    # Strip punctuation
    alnum = re.sub(r"[^A-Za-z0-9_]", "", cleaned).upper()
    return _ALIAS_INDEX.get(alnum, alnum)


def get_human_context(metric_name: str) -> MetricDefinition:
    """
    Return the glossary definition for ``metric_name``.

    Unknown metrics receive a graceful fallback definition (never raises).
    """
    key = normalize_metric_key(metric_name)
    if key in METRIC_CATALOG:
        return METRIC_CATALOG[key]
    return MetricDefinition(
        key=key or "UNKNOWN",
        short_label=metric_name or "Unknown metric",
        technical_name=metric_name or "Unknown metric",
        tooltip="No glossary entry yet — raw simulation value is shown unchanged.",
        unit="",
        lower_is_better=True,
        aliases=(),
    )


def _fmt_number(value: Any, *, sci_below: float = 1e-3) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(v):
        return str(v)
    if v == 0.0:
        return "0"
    if abs(v) < sci_below or abs(v) >= 1e4:
        return f"{v:.3e}"
    if abs(v) >= 100:
        return f"{v:.1f}"
    if abs(v) >= 10:
        return f"{v:.2f}"
    return f"{v:.3f}"


def _badge(
    tone: BadgeTone, label: str
) -> Tuple[str, BadgeTone, str]:
    emoji = {
        BadgeTone.HEALTHY: "🟢",
        BadgeTone.MODERATE: "🟡",
        BadgeTone.ELEVATED: "🟠",
        BadgeTone.CRITICAL: "🔴",
        BadgeTone.STRONG: "🟢",
        BadgeTone.WEAK: "🟡",
        BadgeTone.INFO: "🔵",
        BadgeTone.UNKNOWN: "⚪",
    }[tone]
    return label, tone, emoji


def classify_hsi(value: float) -> Tuple[str, BadgeTone, str, str]:
    """Return (badge_label, tone, emoji, plain_phrase) for HSI."""
    v = float(value)
    if v <= 0.25:
        label, tone, emoji = _badge(BadgeTone.HEALTHY, "Healthy")
        phrase = "cells look close to a healthy baseline"
    elif v <= 0.50:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Moderate Risk")
        phrase = "cells show moderate signaling sickness"
    elif v <= 1.00:
        label, tone, emoji = _badge(BadgeTone.CRITICAL, "Severe Dysregulation")
        phrase = "cells are severely dysregulated"
    else:
        label, tone, emoji = _badge(BadgeTone.CRITICAL, "Collapse-Level Dysregulation")
        phrase = "signaling has drifted into collapse territory"
    return label, tone, emoji, phrase


def classify_las(value: float) -> Tuple[str, BadgeTone, str, str]:
    v = float(value)
    if v >= 0.70:
        label, tone, emoji = _badge(BadgeTone.STRONG, "High scientific alignment")
        phrase = "findings strongly match published literature"
    elif v >= 0.40:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Medium scientific alignment")
        phrase = "findings partially align with literature"
    else:
        label, tone, emoji = _badge(BadgeTone.WEAK, "Low scientific alignment")
        phrase = "literature support is still limited"
    return label, tone, emoji, phrase


def classify_pds(value: float) -> Tuple[str, BadgeTone, str, str]:
    # Same ladder spirit as HSI for pathway disruption
    return classify_hsi(value)


def classify_dg(value: float) -> Tuple[str, BadgeTone, str, str]:
    v = float(value)
    if v <= -8.0:
        label, tone, emoji = _badge(BadgeTone.STRONG, "Strong Lock-and-Key Affinity")
        phrase = "the drug locks tightly into the 3D pocket"
    elif v <= -4.0:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Moderate Binding Fit")
        phrase = "the drug shows a workable pocket fit"
    elif v < 0.0:
        label, tone, emoji = _badge(BadgeTone.WEAK, "Weak Binding Fit")
        phrase = "binding is weak / transient"
    else:
        label, tone, emoji = _badge(BadgeTone.CRITICAL, "Unfavorable Binding")
        phrase = "binding is energetically unfavorable"
    return label, tone, emoji, phrase


def classify_ki(value: float) -> Tuple[str, BadgeTone, str, str]:
    v = float(value)
    if v <= 1e-9:
        label, tone, emoji = _badge(BadgeTone.STRONG, "Nanomolar-or-better potency")
        phrase = "only a tiny drug concentration is needed to inhibit the target"
    elif v <= 1e-6:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Micromolar potency")
        phrase = "drug potency is in a typical micromolar range"
    elif v <= 1e-3:
        label, tone, emoji = _badge(BadgeTone.WEAK, "Millimolar / weak potency")
        phrase = "a relatively high concentration is needed for inhibition"
    else:
        label, tone, emoji = _badge(BadgeTone.CRITICAL, "Negligible potency")
        phrase = "inhibition would require impractically high drug levels"
    return label, tone, emoji, phrase


def classify_psi(value: float) -> Tuple[str, BadgeTone, str, str]:
    v = max(0.0, min(1.0, float(value)))
    if v >= 0.7:
        label, tone, emoji = _badge(BadgeTone.INFO, "Isoform dominant")
        phrase = "this splice isoform dominates the transcript pool"
    elif v >= 0.3:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Mixed splicing")
        phrase = "both isoforms are meaningfully present"
    else:
        label, tone, emoji = _badge(BadgeTone.INFO, "Isoform mostly skipped")
        phrase = "this isoform is largely skipped"
    return label, tone, emoji, phrase


def classify_epsilon(value: float) -> Tuple[str, BadgeTone, str, str]:
    v = max(0.0, min(1.0, float(value)))
    if v <= 0.25:
        label, tone, emoji = _badge(BadgeTone.HEALTHY, "T cells competent")
        phrase = "cytotoxic T cells remain largely competent"
    elif v <= 0.55:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Partial T-cell exhaustion")
        phrase = "T cells are partially exhausted under checkpoint pressure"
    else:
        label, tone, emoji = _badge(BadgeTone.CRITICAL, "Severe T-cell exhaustion")
        phrase = "T cells are heavily exhausted"
    return label, tone, emoji, phrase


def classify_ic50(value: float) -> Tuple[str, BadgeTone, str, str]:
    v = float(value)
    if v <= 50.0:
        label, tone, emoji = _badge(BadgeTone.STRONG, "Strong MHC binder")
        phrase = "peptide is a strong MHC-binding neoantigen candidate"
    elif v <= 500.0:
        label, tone, emoji = _badge(BadgeTone.MODERATE, "Weak MHC binder")
        phrase = "peptide is a weak but usable MHC binder"
    else:
        label, tone, emoji = _badge(BadgeTone.WEAK, "Poor MHC binder")
        phrase = "peptide is unlikely to present well on MHC"
    return label, tone, emoji, phrase


_CLASSIFIERS = {
    "HSI": classify_hsi,
    "LAS": classify_las,
    "PDS": classify_pds,
    "DG": classify_dg,
    "KI": classify_ki,
    "PSI": classify_psi,
    "EPSILON": classify_epsilon,
    "IC50": classify_ic50,
}


def translate_metric(metric_name: str, value: Any) -> TranslatedMetric:
    """
    Translate one metric observation into badges + plain language.

    Never mutates ``value``; it is stored as ``raw_value``.
    """
    definition = get_human_context(metric_name)
    key = definition.key
    display = _fmt_number(value)
    if key == "KI" and isinstance(value, (int, float)) and math.isfinite(float(value)):
        display = f"{float(value):.3e}"
    if key == "DG" and isinstance(value, (int, float)) and math.isfinite(float(value)):
        display = f"{float(value):.2f}"

    classifier = _CLASSIFIERS.get(key)
    if classifier is not None:
        try:
            badge_label, tone, emoji, phrase = classifier(float(value))
        except (TypeError, ValueError):
            badge_label, tone, emoji = _badge(BadgeTone.UNKNOWN, "Unclassified")
            phrase = "value could not be classified"
    else:
        badge_label, tone, emoji = _badge(BadgeTone.INFO, "Recorded")
        phrase = f"{definition.short_label} = {display}"

    return TranslatedMetric(
        key=key,
        raw_value=value,
        short_label=definition.short_label,
        technical_name=definition.technical_name,
        tooltip=definition.tooltip,
        badge_label=badge_label,
        badge_tone=tone,
        badge_emoji=emoji,
        plain_phrase=phrase,
        unit=definition.unit,
        display_value=display,
    )


def translate_metrics(metrics: Mapping[str, Any]) -> Dict[str, TranslatedMetric]:
    """Batch-translate a mapping of metric_name → raw value."""
    return {normalize_metric_key(k) or k: translate_metric(k, v) for k, v in metrics.items()}


# ---------------------------------------------------------------------------
# Executive summary / progressive disclosure
# ---------------------------------------------------------------------------


@dataclass
class ExecutiveSummary:
    """Top-level one-sentence takeaway + supporting badge strip."""

    sentence: str
    badges: List[TranslatedMetric] = field(default_factory=list)
    details: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sentence": self.sentence,
            "badges": [b.as_dict() for b in self.badges],
            "details": list(self.details),
        }

    def markdown(self) -> str:
        lines = [
            "## Executive Summary",
            "",
            f"> {self.sentence}",
            "",
        ]
        if self.badges:
            lines.append("### Status at a glance")
            lines.append("")
            for b in self.badges:
                lines.append(f"- {b.markdown_inline()}")
            lines.append("")
        if self.details:
            lines.append("### Plain-language notes")
            lines.append("")
            for d in self.details:
                lines.append(f"- {d}")
            lines.append("")
        return "\n".join(lines)


def build_executive_summary(
    *,
    hsi: Optional[float] = None,
    hsi_pre: Optional[float] = None,
    las: Optional[float] = None,
    pds: Optional[float] = None,
    readout: str = "ERK",
    readout_pre: Optional[float] = None,
    readout_post: Optional[float] = None,
    delta_g: Optional[float] = None,
    ki: Optional[float] = None,
    epsilon: Optional[float] = None,
    objective_met: Optional[bool] = None,
    patient_id: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> ExecutiveSummary:
    """
    Compose a progressive-disclosure executive takeaway from common engine outputs.

    All numeric inputs remain available unchanged via ``TranslatedMetric.raw_value``.
    """
    badges: List[TranslatedMetric] = []
    details: List[str] = []
    parts: List[str] = []

    who = f"Patient `{patient_id}`" if patient_id else "Patient"

    if hsi is not None:
        th = translate_metric("HSI", hsi)
        badges.append(th)
        pct = max(0.0, min(100.0, float(hsi) * 100.0))
        if hsi_pre is not None and float(hsi_pre) > 1e-9:
            drop = (float(hsi_pre) - float(hsi)) / float(hsi_pre) * 100.0
            parts.append(
                f"{who} shows {pct:.0f}% cellular dysregulation"
            )
            if drop > 0:
                parts.append(f"therapy improved the sickness score by {drop:.1f}%")
            details.append(th.plain_phrase)
        else:
            parts.append(f"{who} shows {pct:.0f}% cellular dysregulation ({th.badge_label})")
            details.append(th.plain_phrase)

    if readout_pre is not None and readout_post is not None and float(readout_pre) > 1e-9:
        change = (float(readout_pre) - float(readout_post)) / float(readout_pre) * 100.0
        direction = "reduced" if change > 0 else "increased"
        parts.append(
            f"{readout} disease activity was {direction} by {abs(change):.1f}%"
        )

    if las is not None:
        tl = translate_metric("LAS", las)
        badges.append(tl)
        details.append(tl.plain_phrase)

    if pds is not None:
        tp = translate_metric("PDS", pds)
        badges.append(tp)
        details.append(tp.plain_phrase)

    if delta_g is not None:
        tg = translate_metric("DG", delta_g)
        badges.append(tg)
        details.append(tg.plain_phrase)

    if ki is not None:
        tk = translate_metric("KI", ki)
        badges.append(tk)
        details.append(tk.plain_phrase)

    if epsilon is not None:
        te = translate_metric("EPSILON", epsilon)
        badges.append(te)
        details.append(te.plain_phrase)

    if extra:
        for k, v in extra.items():
            if normalize_metric_key(k) in METRIC_CATALOG:
                badges.append(translate_metric(k, v))

    if objective_met is True:
        parts.append("the stated treatment objective was met")
    elif objective_met is False:
        parts.append("the stated treatment objective was not yet met")

    if not parts:
        sentence = (
            "Simulation complete — open the telemetry panel below for raw biophysical detail."
        )
    else:
        # Capitalize first clause; join with '; '
        body = "; ".join(parts)
        sentence = body[0].upper() + body[1:] + "."

    return ExecutiveSummary(sentence=sentence, badges=badges, details=details)


TELEMETRY_OPEN = "<!-- CISTRON_TELEMETRY_START -->"
TELEMETRY_CLOSE = "<!-- CISTRON_TELEMETRY_END -->"


def wrap_raw_telemetry(raw_markdown: str, *, title: str = "Show Raw Biophysical Telemetry") -> str:
    """
    Wrap dense numeric Markdown inside a collapsible HTML ``<details>`` block.

    Compatible with GitHub / Streamlit / most Markdown renderers.
    """
    body = raw_markdown.strip()
    return "\n".join(
        [
            "<details>",
            f"<summary>▼ {title}</summary>",
            "",
            TELEMETRY_OPEN,
            "",
            body,
            "",
            TELEMETRY_CLOSE,
            "",
            "</details>",
            "",
        ]
    )


def compose_progressive_brief(
    *,
    executive: ExecutiveSummary,
    body_markdown: str,
    glossary_keys: Optional[Sequence[str]] = None,
) -> str:
    """
    Lead with executive summary, then collapsible raw body, then glossary.
    """
    keys = list(glossary_keys) if glossary_keys is not None else [
        b.key for b in executive.badges
    ]
    # Always include core glossary
    for k in ("HSI", "LAS", "PDS", "DG", "KI", "PSI"):
        if k not in keys:
            keys.append(k)

    sections = [
        executive.markdown().rstrip(),
        "",
        "---",
        "",
        wrap_raw_telemetry(body_markdown).rstrip(),
        "",
        "## Glossary",
        "",
    ]
    seen = set()
    for k in keys:
        nk = normalize_metric_key(k)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        d = get_human_context(nk)
        sections.append(f"- **{d.short_label}** (`{d.key}` / {d.technical_name}): {d.tooltip}")
    sections.append("")
    return "\n".join(sections)


def annotate_abbreviations(text: str) -> str:
    """
    Append parenthetical plain labels the first time common abbreviations appear.

    Example: ``HSI=0.35`` → ``HSI (Cellular Health / Sickness Score)=0.35`` once.
    Does not alter numeric literals.
    """
    seen: set[str] = set()

    def _repl(match: re.Match[str]) -> str:
        token = match.group(0)
        key = normalize_metric_key(token)
        if key not in METRIC_CATALOG or key in seen:
            return token
        seen.add(key)
        label = METRIC_CATALOG[key].short_label
        return f"{token} ({label})"

    # Match standalone abbreviations / ΔG / K_i forms
    pattern = re.compile(
        r"\b(?:HSI|LAS|PDS|PSI|IC50|ERK)\b|\bK[_]?i\b|\bK[_]?I\b|ΔG|\bdelta[_ ]?G\b",
        re.IGNORECASE,
    )
    return pattern.sub(_repl, text)


class MetricTranslator:
    """Facade used by reporters, Streamlit, and API serializers."""

    def context(self, metric_name: str) -> MetricDefinition:
        return get_human_context(metric_name)

    def translate(self, metric_name: str, value: Any) -> TranslatedMetric:
        return translate_metric(metric_name, value)

    def translate_many(self, metrics: Mapping[str, Any]) -> Dict[str, TranslatedMetric]:
        return translate_metrics(metrics)

    def executive_summary(self, **kwargs: Any) -> ExecutiveSummary:
        return build_executive_summary(**kwargs)

    def progressive_brief(
        self,
        body_markdown: str,
        **summary_kwargs: Any,
    ) -> str:
        executive = build_executive_summary(**summary_kwargs)
        return compose_progressive_brief(executive=executive, body_markdown=body_markdown)

    def catalog(self) -> Dict[str, Dict[str, Any]]:
        return {
            k: {
                "key": d.key,
                "short_label": d.short_label,
                "technical_name": d.technical_name,
                "tooltip": d.tooltip,
                "unit": d.unit,
                "lower_is_better": d.lower_is_better,
                "aliases": list(d.aliases),
            }
            for k, d in METRIC_CATALOG.items()
        }


DEFAULT_TRANSLATOR = MetricTranslator()
