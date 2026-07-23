/**
 * Plain-language metric glossary — keep in sync with voidsignal/ui/translator.py
 */

export type BadgeTone =
  | "healthy"
  | "moderate"
  | "elevated"
  | "critical"
  | "strong"
  | "weak"
  | "info"
  | "unknown";

export type MetricDefinition = {
  key: string;
  shortLabel: string;
  technicalName: string;
  tooltip: string;
  unit: string;
  lowerIsBetter: boolean;
  aliases: string[];
};

export type TranslatedMetric = {
  key: string;
  rawValue: number | string;
  shortLabel: string;
  technicalName: string;
  tooltip: string;
  badgeLabel: string;
  badgeTone: BadgeTone;
  badgeEmoji: string;
  plainPhrase: string;
  unit: string;
  displayValue: string;
};

export const METRIC_CATALOG: Record<string, MetricDefinition> = {
  HSI: {
    key: "HSI",
    shortLabel: "Cellular Health / Sickness Score",
    technicalName: "Homeostatic Shift Index",
    tooltip:
      "How far the cell's signaling steady-state has drifted from a healthy baseline. Near 0 means homeostasis; higher values mean progressive dysregulation.",
    unit: "",
    lowerIsBetter: true,
    aliases: ["hsi", "homeostatic_shift"],
  },
  LAS: {
    key: "LAS",
    shortLabel: "Literature Confidence Score",
    technicalName: "Literature Alignment Score",
    tooltip:
      "How well the agent's chosen targets and outcomes agree with published pathway / pharmacology literature.",
    unit: "",
    lowerIsBetter: false,
    aliases: ["las", "literature_alignment"],
  },
  DG: {
    key: "DG",
    shortLabel: "3D Binding Fit Strength",
    technicalName: "Binding Free Energy (ΔG)",
    tooltip:
      "Estimated Gibbs free energy of ligand–protein binding. More negative values mean a tighter lock-and-key fit.",
    unit: "kcal/mol",
    lowerIsBetter: true,
    aliases: ["dg", "delta_g", "ΔG", "dG"],
  },
  KI: {
    key: "KI",
    shortLabel: "Drug Concentration Threshold",
    technicalName: "Inhibition Constant (Ki)",
    tooltip:
      "Equilibrium concentration at which the drug occupies half of its target sites. Lower Ki means a more potent inhibitor.",
    unit: "M",
    lowerIsBetter: true,
    aliases: ["ki", "k_i", "Ki"],
  },
  PSI: {
    key: "PSI",
    shortLabel: "Gene Splicing Ratio",
    technicalName: "Percent Spliced In",
    tooltip: "Fraction of transcripts that include a given exon or isoform.",
    unit: "",
    lowerIsBetter: false,
    aliases: ["psi", "percent_spliced_in"],
  },
  PDS: {
    key: "PDS",
    shortLabel: "Pathway Disruption Index",
    technicalName: "Pathway Dysregulation Score",
    tooltip: "Composite measure of pathway subgraph disruption vs a healthy reference.",
    unit: "",
    lowerIsBetter: true,
    aliases: ["pds", "pathway_dysregulation"],
  },
  EPSILON: {
    key: "EPSILON",
    shortLabel: "T-cell Exhaustion Level",
    technicalName: "Immune Exhaustion Coefficient (ε)",
    tooltip: "How worn-out cytotoxic T cells are under checkpoint pressure. 0 = competent; 1 = exhausted.",
    unit: "",
    lowerIsBetter: true,
    aliases: ["epsilon", "exhaustion"],
  },
  ERK: {
    key: "ERK",
    shortLabel: "Growth Signal Readout",
    technicalName: "Extracellular signal-Regulated Kinase activity",
    tooltip: "Downstream MAPK effector used as the primary oncogenic readout.",
    unit: "a.u.",
    lowerIsBetter: true,
    aliases: ["erk", "mapk1"],
  },
};

const ALIAS: Record<string, string> = {};
for (const def of Object.values(METRIC_CATALOG)) {
  ALIAS[def.key.toUpperCase()] = def.key;
  for (const a of def.aliases) ALIAS[a.toUpperCase()] = def.key;
}

export function normalizeMetricKey(name: string): string {
  const raw = (name || "").trim().replace("Δ", "D").replace("δ", "d");
  if (!raw) return "";
  if (/^delta[_\s-]?g$/i.test(raw) || raw.toUpperCase() === "DG") return "DG";
  if (/^k[_-]?i$/i.test(raw)) return "KI";
  return ALIAS[raw.toUpperCase()] ?? raw.toUpperCase();
}

export function getHumanContext(metricName: string): MetricDefinition {
  const key = normalizeMetricKey(metricName);
  return (
    METRIC_CATALOG[key] ?? {
      key: key || "UNKNOWN",
      shortLabel: metricName || "Unknown metric",
      technicalName: metricName || "Unknown metric",
      tooltip: "No glossary entry yet — raw simulation value is shown unchanged.",
      unit: "",
      lowerIsBetter: true,
      aliases: [],
    }
  );
}

function fmt(value: number | string, key: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  if (key === "KI") return value.toExponential(3);
  if (key === "DG") return value.toFixed(2);
  if (Math.abs(value) < 1e-3 || Math.abs(value) >= 1e4) return value.toExponential(3);
  return value.toFixed(3);
}

function badge(
  tone: BadgeTone,
  label: string,
): { badgeLabel: string; badgeTone: BadgeTone; badgeEmoji: string } {
  const emoji: Record<BadgeTone, string> = {
    healthy: "🟢",
    moderate: "🟡",
    elevated: "🟠",
    critical: "🔴",
    strong: "🟢",
    weak: "🟡",
    info: "🔵",
    unknown: "⚪",
  };
  return { badgeLabel: label, badgeTone: tone, badgeEmoji: emoji[tone] };
}

function classify(key: string, value: number): {
  badgeLabel: string;
  badgeTone: BadgeTone;
  badgeEmoji: string;
  plainPhrase: string;
} {
  if (key === "HSI" || key === "PDS") {
    if (value <= 0.25) return { ...badge("healthy", "Healthy"), plainPhrase: "cells look close to a healthy baseline" };
    if (value <= 0.5)
      return { ...badge("moderate", "Moderate Risk"), plainPhrase: "cells show moderate signaling sickness" };
    return {
      ...badge("critical", "Severe Dysregulation"),
      plainPhrase: "cells are severely dysregulated",
    };
  }
  if (key === "LAS") {
    if (value >= 0.7)
      return { ...badge("strong", "High scientific alignment"), plainPhrase: "findings strongly match published literature" };
    if (value >= 0.4)
      return { ...badge("moderate", "Medium scientific alignment"), plainPhrase: "findings partially align with literature" };
    return { ...badge("weak", "Low scientific alignment"), plainPhrase: "literature support is still limited" };
  }
  if (key === "DG") {
    if (value <= -8)
      return { ...badge("strong", "Strong Lock-and-Key Affinity"), plainPhrase: "the drug locks tightly into the 3D pocket" };
    if (value <= -4)
      return { ...badge("moderate", "Moderate Binding Fit"), plainPhrase: "the drug shows a workable pocket fit" };
    if (value < 0) return { ...badge("weak", "Weak Binding Fit"), plainPhrase: "binding is weak / transient" };
    return { ...badge("critical", "Unfavorable Binding"), plainPhrase: "binding is energetically unfavorable" };
  }
  if (key === "KI") {
    if (value <= 1e-9)
      return { ...badge("strong", "Nanomolar-or-better potency"), plainPhrase: "only a tiny drug concentration is needed" };
    if (value <= 1e-6)
      return { ...badge("moderate", "Micromolar potency"), plainPhrase: "drug potency is in a typical micromolar range" };
    return { ...badge("weak", "Weak potency"), plainPhrase: "a relatively high concentration is needed" };
  }
  if (key === "PSI") {
    if (value >= 0.7) return { ...badge("info", "Isoform dominant"), plainPhrase: "this splice isoform dominates" };
    if (value >= 0.3) return { ...badge("moderate", "Mixed splicing"), plainPhrase: "both isoforms are present" };
    return { ...badge("info", "Isoform mostly skipped"), plainPhrase: "this isoform is largely skipped" };
  }
  if (key === "EPSILON") {
    if (value <= 0.25) return { ...badge("healthy", "T cells competent"), plainPhrase: "T cells remain largely competent" };
    if (value <= 0.55)
      return { ...badge("moderate", "Partial T-cell exhaustion"), plainPhrase: "T cells are partially exhausted" };
    return { ...badge("critical", "Severe T-cell exhaustion"), plainPhrase: "T cells are heavily exhausted" };
  }
  return { ...badge("info", "Recorded"), plainPhrase: `${key} = ${fmt(value, key)}` };
}

export function translateMetric(metricName: string, value: number | string): TranslatedMetric {
  const def = getHumanContext(metricName);
  const key = def.key;
  const num = typeof value === "number" ? value : Number(value);
  const classified =
    Number.isFinite(num) ? classify(key, num) : { ...badge("unknown", "Unclassified"), plainPhrase: "value could not be classified" };
  return {
    key,
    rawValue: value,
    shortLabel: def.shortLabel,
    technicalName: def.technicalName,
    tooltip: def.tooltip,
    badgeLabel: classified.badgeLabel,
    badgeTone: classified.badgeTone,
    badgeEmoji: classified.badgeEmoji,
    plainPhrase: classified.plainPhrase,
    unit: def.unit,
    displayValue: fmt(value, key),
  };
}

export function buildExecutiveSentence(metrics: {
  hsi?: number;
  las?: number;
  pds?: number;
  readout?: string;
  readoutValue?: number;
}): string {
  const parts: string[] = [];
  if (metrics.hsi != null) {
    const pct = Math.max(0, Math.min(100, metrics.hsi * 100));
    const t = translateMetric("HSI", metrics.hsi);
    parts.push(`Patient shows ${pct.toFixed(0)}% cellular dysregulation (${t.badgeLabel})`);
  }
  if (metrics.readout && metrics.readoutValue != null) {
    parts.push(`${metrics.readout} activity is currently ${metrics.readoutValue.toFixed(2)}`);
  }
  if (metrics.las != null) {
    parts.push(translateMetric("LAS", metrics.las).plainPhrase);
  }
  if (!parts.length) {
    return "Simulation ready — expand telemetry panels for raw biophysical detail.";
  }
  const body = parts.join("; ");
  return body.charAt(0).toUpperCase() + body.slice(1) + ".";
}

export const toneColor: Record<BadgeTone, string> = {
  healthy: "#A3E635",
  moderate: "#FBBF24",
  elevated: "#FB923C",
  critical: "#FB7185",
  strong: "#A3E635",
  weak: "#FBBF24",
  info: "#00E5FF",
  unknown: "#94A3B8",
};
