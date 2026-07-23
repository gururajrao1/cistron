/**
 * Shared API contracts for CISTRON Research Studio ↔ Python backend
 */

export type SystemHealth = {
  status: "online" | "degraded" | "offline";
  odeSolver: string;
  workers: number;
  version: string;
  uptimeSec: number;
};

export type PatientBadge = {
  patientId: string;
  vcfName: string;
  variants: Array<{ gene: string; hgvs: string; delta: number }>;
  pathwayId: string;
};

export type MetricSnapshot = {
  hsi: number;
  pds: number;
  las: number;
  toxicity: number;
  readout: string;
  readoutValue: number;
};

export type DoseParams = {
  agentId: string;
  target: string;
  enabled: boolean;
  c0: number;
  tStart: number;
  tEnd: number;
  ki?: number;
};

export type SimulationRequest = {
  patientId: string;
  pathwayId: string;
  doses: DoseParams[];
  tHorizon: number;
  dt: number;
  readout: string;
};

export type TrajectorySeries = {
  id: string;
  name: string;
  color?: string;
  t: number[];
  y: number[];
};

/** UniProt/Reactome-style protein/gene card from `.to_encyclopedia_card()`. */
export type EncyclopediaDomain = {
  name: string;
  start?: number | null;
  end?: number | null;
  domain_type: string;
  active: boolean;
};

export type EncyclopediaPtm = {
  name: string;
  residue?: string | null;
  modification: string;
  stoichiometry: number;
  occupancy: number;
  active: boolean;
};

export type EncyclopediaDrug = {
  name: string;
  mechanism: string;
  ic50_nM?: number | null;
  ki_M?: number | null;
  approval_status: string;
};

export type EncyclopediaCard = {
  card_type: "protein" | "gene";
  title: string;
  subtitle: string;
  identity: {
    gene_symbol?: string | null;
    full_name?: string | null;
    uniprot_id?: string | null;
    kegg_id?: string | null;
    aliases?: string[];
    species?: string;
    chromosomal_locus?: string | null;
  };
  biology: {
    is_enzyme?: boolean;
    cellular_localization?: string | null;
    domains?: EncyclopediaDomain[];
    ptm_sites?: EncyclopediaPtm[];
    molecular_weight_kda?: number | null;
    sequence_length?: number | null;
    pathway_membership?: string[];
    transcription_rate?: number;
    promoter_strength?: number;
  };
  structure?: {
    pdb_id?: string | null;
    alphafold_plddt_score?: number | null;
    active_site_center?: number[] | null;
    active_site_size?: number[] | null;
    disruption_delta?: number;
  };
  clinical?: {
    diseases?: string[];
    somatic_mutations?: string[];
    clinical_significance?: string | null;
    oncogene?: boolean;
    tumor_suppressor?: boolean;
  };
  drugs?: EncyclopediaDrug[];
  kinetics?: Record<string, number | null | undefined>;
  state?: {
    concentration?: number;
    boolean_state?: string;
    entity_id?: string;
  };
  entity_id?: string;
};

export type CausalChainStep = {
  source_name: string;
  target_name: string;
  interaction: string;
  evidence: string;
  attribution?: number | null;
};

export type CausalExplanation = {
  node_id: string;
  node_name: string;
  kind: "activation" | "inactivation" | "delta";
  percent_change: number;
  control_final: number;
  perturbed_final: number;
  narrative: string;
  chain: CausalChainStep[];
  mutations: string[];
  drugs: string[];
  pathways: string[];
  confidence: number;
};

export type CausalNarrativePayload = {
  control_label: string;
  perturbed_label: string;
  overview_narrative: string;
  cascade: string[];
  activated: CausalExplanation[];
  inactivated: CausalExplanation[];
  stable: string[];
};

export type CrosstalkHub = {
  entity_id: string;
  name: string;
  gene_symbol: string;
  pathways: string[];
  degree: number;
  switch_kind?: string;
};

export type SimulationRun = {
  runId: string;
  status: "queued" | "running" | "complete" | "error";
  request: SimulationRequest;
  series: TrajectorySeries[];
  washout?: { tStart: number; tEnd: number };
  metrics: MetricSnapshot;
  causal?: CausalNarrativePayload;
  error?: string;
};

export type NetworkNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  centrality: number;
  attribution: number;
  mutated?: boolean;
  /** Shared multi-pathway hub (EGFR, RAS, …). */
  crosstalk_hub?: boolean;
  pathways?: string[];
  encyclopedia?: EncyclopediaCard;
};

export type NetworkEdge = {
  id: string;
  source: string;
  target: string;
  kind: "activation" | "inhibition" | "phosphorylation";
  weight: number;
};

export type PatientNetwork = {
  patientId: string;
  pathwayId: string;
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  crosstalk_hubs?: CrosstalkHub[];
  pathway_mode?: "single" | "crosstalk";
};

export type AgentLogLevel = "info" | "hypothesis" | "experiment" | "result" | "warn";

export type AgentLogEvent = {
  id: string;
  t: number;
  level: AgentLogLevel;
  message: string;
};

export type AgentPlanRequest = {
  patientId: string;
  goal: string;
  readout: string;
  maxDrugs: number;
};

export type AgentPlanResult = {
  planId: string;
  status: "idle" | "running" | "complete" | "error";
  logs: AgentLogEvent[];
  las: number;
  briefMarkdown: string;
  selectedDoses: DoseParams[];
  metrics?: MetricSnapshot;
};

export type DockingAtom = {
  serial: number;
  name: string;
  element: string;
  x: number;
  y: number;
  z: number;
  role: "receptor" | "ligand";
};

export type DockingBond = {
  a: number;
  b: number;
  role: "receptor" | "ligand" | "hbond";
};

export type DockingPose = {
  ligandId: string;
  receptorId: string;
  deltaG: number;
  ki: number;
  contacts: number;
  hbonds: number;
  /** Optional 3D scene payload for Three.js viewer. */
  atoms?: DockingAtom[];
  bonds?: DockingBond[];
};
