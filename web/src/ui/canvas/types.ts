/**
 * Visual canvas types — mirror of voidsignal/ui/visual_translator.py exports.
 */

export type NodeVisualState =
  | "overactive"
  | "homeostatic"
  | "inhibited"
  | "quiescent"
  | "mutated";

export type EdgeVisualState = "flowing" | "blocked" | "inhibitory";

export type NodeVisual = {
  node_id: string;
  label: string;
  state: NodeVisualState;
  activity: number;
  color: string;
  fill: string;
  radius_scale: number;
  mutated?: boolean;
  crosstalk_hub?: boolean;
  pathways?: string[];
  x?: number;
  y?: number;
  inspect: Record<string, number | string | boolean>;
};

export type EdgeVisual = {
  edge_id: string;
  source_id: string;
  target_id: string;
  state: EdgeVisualState;
  flux: number;
  thickness: number;
  pulse_speed: number;
  dash: string;
  color: string;
  kind: string;
  blocked: boolean;
  inspect: Record<string, number | string | boolean>;
};

export type VisualFrame = {
  t: number;
  frame_index: number;
  nodes: NodeVisual[];
  edges: EdgeVisual[];
};

export type VisualTimeline = {
  t_start: number;
  t_end: number;
  frames: VisualFrame[];
  legend: Record<string, { emoji: string; label: string; color: string; fill: string }>;
};

export type CellAgentVisual = {
  cell_id: string;
  kind: "tumor" | "ctl" | "macrophage" | "treg";
  x: number;
  y: number;
  state: NodeVisualState;
  color: string;
  inspect: Record<string, number | string>;
};

export type CytokineFieldFrame = {
  cytokine: string;
  t: number;
  grid_w: number;
  grid_h: number;
  values: number[][];
  color: string;
};

export type MicroenvironmentVisual = {
  t: number;
  cells: CellAgentVisual[];
  fields: CytokineFieldFrame[];
};

export type NodePerturbationMode = "none" | "knockout" | "drug";
