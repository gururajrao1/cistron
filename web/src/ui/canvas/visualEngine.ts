/**
 * Client-side visual translator — builds animated frames from trajectory series.
 * Mirrors cistron/ui/visual_translator.py for offline mock / browser use.
 */

import type { PatientNetwork, TrajectorySeries } from "../api/types";
import type {
  EdgeVisual,
  MicroenvironmentVisual,
  NodePerturbationMode,
  NodeVisual,
  NodeVisualState,
  VisualFrame,
  VisualTimeline,
} from "./types";

export const VISUAL_LEGEND = {
  overactive: { emoji: "🔴", label: "Overactive / Oncogenic Drive", color: "#FB7185", fill: "rgba(251,113,133,0.55)" },
  homeostatic: { emoji: "🟢", label: "Homeostatic / Normal Signal", color: "#A3E635", fill: "rgba(163,230,53,0.45)" },
  inhibited: { emoji: "🔵", label: "Inhibited / Suppressed", color: "#38BDF8", fill: "rgba(56,189,248,0.45)" },
  quiescent: { emoji: "⚪", label: "Quiescent / Low Activity", color: "#64748B", fill: "rgba(100,116,139,0.35)" },
  mutated: { emoji: "🟣", label: "Mutated Node", color: "#C084FC", fill: "rgba(192,132,252,0.25)" },
  flowing: { emoji: "⚡", label: "Active Signal Pulse", color: "#00E5FF", fill: "#00E5FF" },
  blocked: { emoji: "⛔", label: "Blocked / Severed Edge", color: "#64748B", fill: "#64748B" },
} as const;

function normSeries(y: number[]): number[] {
  if (!y.length) return [];
  const lo = Math.min(...y);
  const hi = Math.max(...y);
  if (hi - lo < 1e-12) return y.map(() => 0.5);
  return y.map((v) => (v - lo) / (hi - lo));
}

function classify(activity: number, inhibited: boolean): NodeVisualState {
  if (inhibited) return activity < 0.35 ? "inhibited" : "quiescent";
  if (activity >= 0.72) return "overactive";
  if (activity <= 0.15) return "quiescent";
  return "homeostatic";
}

function thickness(flux: number): number {
  const t = Math.abs(flux) / (1 + Math.abs(flux));
  return 1.2 + 5.8 * t;
}

function pulseSpeed(flux: number, blocked: boolean): number {
  if (blocked || Math.abs(flux) < 1e-9) return 0;
  return Math.max(0.15, Math.min(4, 0.4 + 2.2 * (Math.abs(flux) / (1 + Math.abs(flux)))));
}

export function buildVisualTimeline(
  network: PatientNetwork,
  series: TrajectorySeries[],
  perturbations: Record<string, NodePerturbationMode> = {},
  maxFrames = 80,
): VisualTimeline {
  const byId = Object.fromEntries(series.map((s) => [s.id, s]));
  const tAxis = series[0]?.t ?? [0];
  const norms: Record<string, number[]> = {};
  for (const n of network.nodes) {
    const s = byId[n.id] ?? byId[n.label];
    norms[n.id] = s ? normSeries(s.y) : network.nodes.map(() => 0.4);
  }

  const stride = Math.max(1, Math.ceil(tAxis.length / maxFrames));
  const frames: VisualFrame[] = [];
  let fi = 0;
  for (let i = 0; i < tAxis.length; i += stride) {
    const t = tAxis[i]!;
    const nodes: NodeVisual[] = network.nodes.map((n) => {
      const mode = perturbations[n.id] ?? perturbations[n.label] ?? "none";
      const inhibited = mode === "knockout" || mode === "drug";
      const act = mode === "knockout" ? 0.02 : norms[n.id]?.[Math.min(i, (norms[n.id]?.length ?? 1) - 1)] ?? 0.4;
      const state = classify(act, inhibited);
      const legend = VISUAL_LEGEND[state];
      const rawY = byId[n.id]?.y[i] ?? byId[n.label]?.y[i] ?? act;
      return {
        node_id: n.id,
        label: n.label,
        state,
        activity: act,
        color: legend.color,
        fill: legend.fill,
        radius_scale: 0.7 + 0.8 * act,
        mutated: !!n.mutated,
        crosstalk_hub: !!n.crosstalk_hub,
        pathways: n.pathways,
        x: n.x,
        y: n.y,
        inspect: {
          concentration: rawY,
          activity_norm: act,
          centrality: n.centrality,
          attribution: n.attribution,
          perturbation: mode,
          state,
          crosstalk_hub: !!n.crosstalk_hub,
          pathways: (n.pathways ?? []).join(","),
        },
      };
    });

    const nodeAct = Object.fromEntries(nodes.map((n) => [n.node_id, n.activity]));
    const edges: EdgeVisual[] = network.edges.map((e) => {
      const srcMode = perturbations[e.source] ?? "none";
      const blocked = srcMode === "knockout" || srcMode === "drug";
      const srcAct = nodeAct[e.source] ?? 0.3;
      const flux = blocked ? 0 : e.weight * (0.4 + srcAct) * (e.kind === "inhibition" ? 0.5 : 1.2);
      if (blocked) {
        return {
          edge_id: e.id,
          source_id: e.source,
          target_id: e.target,
          state: "blocked" as const,
          flux: 0,
          thickness: 1.5,
          pulse_speed: 0,
          dash: "6,5",
          color: VISUAL_LEGEND.blocked.color,
          kind: e.kind,
          blocked: true,
          inspect: { weight: e.weight, flux: 0, blocked: true, kind: e.kind },
        };
      }
      const inhibitory = e.kind === "inhibition";
      return {
        edge_id: e.id,
        source_id: e.source,
        target_id: e.target,
        state: inhibitory ? ("inhibitory" as const) : ("flowing" as const),
        flux,
        thickness: thickness(flux),
        pulse_speed: pulseSpeed(flux, false),
        dash: inhibitory ? "5,4" : e.kind === "phosphorylation" ? "2,3" : "none",
        color: inhibitory ? "#FB7185" : e.kind === "phosphorylation" ? "#00E5FF" : "#2DD4BF",
        kind: e.kind,
        blocked: false,
        inspect: { weight: e.weight, flux, blocked: false, kind: e.kind },
      };
    });

    frames.push({ t, frame_index: fi, nodes, edges });
    fi += 1;
  }

  return {
    t_start: tAxis[0] ?? 0,
    t_end: tAxis[tAxis.length - 1] ?? 0,
    frames,
    legend: { ...VISUAL_LEGEND },
  };
}

export function buildTmeVisual(t: number, grid = 12): MicroenvironmentVisual {
  const tumor = [
    [0.35, 0.4],
    [0.55, 0.45],
    [0.45, 0.6],
  ] as const;
  const ctl = [
    [0.15, 0.2],
    [0.8, 0.3],
    [0.7, 0.75],
  ] as const;
  const macro = [
    [0.25, 0.7],
    [0.6, 0.2],
  ] as const;

  const field = (cx: number, cy: number, amp: number) => {
    const sigma = 0.22;
    const values: number[][] = [];
    for (let gy = 0; gy < grid; gy++) {
      const row: number[] = [];
      for (let gx = 0; gx < grid; gx++) {
        const x = (gx + 0.5) / grid;
        const y = (gy + 0.5) / grid;
        const d2 = (x - cx) ** 2 + (y - cy) ** 2;
        row.push(amp * Math.exp(-d2 / (2 * sigma * sigma)));
      }
      values.push(row);
    }
    return values;
  };

  const amp = 0.55 + 0.35 * Math.sin(t / 8) ** 2;
  return {
    t,
    cells: [
      ...tumor.map(([x, y], i) => ({
        cell_id: `tumor_${i}`,
        kind: "tumor" as const,
        x,
        y,
        state: "overactive" as const,
        color: VISUAL_LEGEND.overactive.color,
        inspect: { population: "tumor", x, y },
      })),
      ...ctl.map(([x, y], i) => ({
        cell_id: `ctl_${i}`,
        kind: "ctl" as const,
        x,
        y,
        state: "homeostatic" as const,
        color: "#00E5FF",
        inspect: { population: "ctl", x, y },
      })),
      ...macro.map(([x, y], i) => ({
        cell_id: `macro_${i}`,
        kind: "macrophage" as const,
        x,
        y,
        state: "homeostatic" as const,
        color: "#FBBF24",
        inspect: { population: "macrophage", x, y },
      })),
    ],
    fields: [
      { cytokine: "TGFb", t, grid_w: grid, grid_h: grid, values: field(0.45, 0.5, amp), color: "#FB923C" },
      { cytokine: "IL6", t, grid_w: grid, grid_h: grid, values: field(0.3, 0.65, amp * 0.85), color: "#A78BFA" },
    ],
  };
}

export function frameAtTime(timeline: VisualTimeline, t: number): VisualFrame {
  if (!timeline.frames.length) {
    return { t: 0, frame_index: 0, nodes: [], edges: [] };
  }
  let best = timeline.frames[0]!;
  let bestD = Math.abs(best.t - t);
  for (const fr of timeline.frames) {
    const d = Math.abs(fr.t - t);
    if (d < bestD) {
      best = fr;
      bestD = d;
    }
  }
  return best;
}
