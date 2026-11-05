/** Shared API / domain types for the Cistron laboratory frontend. */

export interface PresetSummary {
  id: string
  name: string
  n_nodes: number
  n_edges: number
  description: string
  nodes: string[]
}

export interface PresetDetail {
  id: string
  name: string
  organism_id: number
  nodes: Record<
    string,
    {
      gene_symbol: string
      tau_min: number
      activity_weight: number
      initial_concentration?: number
      metadata?: Record<string, unknown>
    }
  >
  edges: Array<{
    source: string
    target: string
    sign: number
    is_stimulation: boolean
    is_inhibition: boolean
    mechanism: string
    sources?: string[]
    datasets?: string[]
    evidence_score?: number | null
  }>
  provenance: Record<string, unknown>
}

export interface ScrubberPayload {
  simulation_id: string
  time_steps: number[]
  /** Node concentration series (legacy key; same data as trajectories). */
  nodes: Record<string, number[]>
  /** Single-source-of-truth concentration series (preferred). */
  trajectories?: Record<string, number[]>
  edges: Record<string, number[]>
  /** Server HIF1A 2-compartment pools (cyto / nuc). */
  compartments?: {
    cyto?: number[]
    nuc?: number[]
    [key: string]: number[] | undefined
  }
  metadata: Record<string, unknown>
}

/** Prefer trajectories when present; fall back to nodes. */
export function payloadNodeSeries(
  payload: ScrubberPayload | null | undefined,
): Record<string, number[]> {
  if (!payload) return {}
  const traj = payload.trajectories
  if (traj && Object.keys(traj).length > 0) return traj
  return payload.nodes ?? {}
}

/** Sample server compartment pools at time t (minutes). */
export function sampleCompartmentsAt(
  payload: ScrubberPayload | null | undefined,
  t: number,
): { cytoplasm: number; nucleus: number; mitochondria: number } | null {
  const cyto = payload?.compartments?.cyto
  const nuc = payload?.compartments?.nuc
  const times = payload?.time_steps
  if (!cyto?.length || !nuc?.length || !times?.length) return null
  let i = 0
  if (t <= times[0]!) i = 0
  else if (t >= times[times.length - 1]!) i = times.length - 1
  else {
    while (i < times.length - 1 && times[i + 1]! < t) i += 1
    const t0 = times[i]!
    const t1 = times[i + 1]!
    const w = t1 <= t0 ? 0 : (t - t0) / (t1 - t0)
    const c0 = cyto[i] ?? 0
    const c1 = cyto[i + 1] ?? c0
    const n0 = nuc[i] ?? 0
    const n1 = nuc[i + 1] ?? n0
    return {
      cytoplasm: c0 + w * (c1 - c0),
      nucleus: n0 + w * (n1 - n0),
      mitochondria: 0,
    }
  }
  return {
    cytoplasm: cyto[i] ?? 0,
    nucleus: nuc[i] ?? 0,
    mitochondria: 0,
  }
}

export interface SimulateRequest {
  preset: string
  t_end?: number
  knockouts?: string[]
  clamps?: Record<string, number>
  drugs?: Array<{ target: string; c_drug: number; ki: number }>
  simulation_id?: string
  dense_output_points?: number
}

export interface SimulateResponse {
  payload: ScrubberPayload
  preset: string
  elapsed_ms: number
}

export interface NodeFeatureVector {
  y_init: number
  y_final: number
  delta_y: number
  capacity: number
  is_knocked_out: boolean
}

export interface PrioritizationResult {
  node_vectors: Record<string, NodeFeatureVector>
  attention_matrix: Record<string, number>
  master_regulators: Array<[string, number]>
  metadata?: Record<string, unknown>
}

export interface PrioritizeResponse {
  result: PrioritizationResult
  preset: string
  elapsed_ms: number
}

export interface CausalPathContext {
  nodes: string[]
  state_deltas: Record<string, number>
  cumulative_attention: number
  mechanisms: string[]
  path_distance?: number
  signs?: number[]
}

export interface CausalContextPayload {
  simulation_id: string
  extracted_paths: CausalPathContext[]
  top_master_regulator: string
  perturbed_nodes: string[]
  source_node?: string
  target_node?: string
}

export interface ReasonRequest {
  preset: string
  payload: ScrubberPayload
  source_node: string
  target_node: string
  k?: number
  include_prompt?: boolean
  include_brief?: boolean
  include_prioritization?: boolean
}

export interface ReasonResponse {
  context: CausalContextPayload
  brief?: string | null
  prompt?: string | null
  prioritization?: PrioritizationResult | null
  elapsed_ms: number
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  timestamp?: string
  database_handles?: Record<string, unknown>
}

export interface ConditionSuggestion {
  label: string
  query: string
}

export interface FeatureAttribution {
  feature_name: string
  value: number
  attribution: number
}

export interface NodeShapAttribution {
  node: string
  importance: number
  rank: number
  feature_attributions: FeatureAttribution[]
  delta_y: number
  capacity: number
  is_knocked_out: boolean
}

export interface EdgeFlowImpact {
  edge_key: string
  source: string
  target: string
  alpha: number
  impact_score: number
  mean_flux: number
}

export interface CounterfactualResult {
  hypothesis: string
  node: string
  intervention: string
  readout_node: string
  baseline_readout: number
  counterfactual_readout: number
  fold_change: number
  delta_absolute: number
  horizon_min: number
  narrative: string
}

export interface XAIAttributionResult {
  node_attributions: NodeShapAttribution[]
  edge_flow_impacts: EdgeFlowImpact[]
  counterfactuals: CounterfactualResult[]
  output_nodes: string[]
  output_delta_sum: number
  elapsed_ms: number
  metadata?: Record<string, unknown>
}

export interface ScientistReasoning {
  brief: string
  sentiment: 'up' | 'down' | 'mixed' | 'neutral' | string
  total_flux_delta: number
  top_node_deltas: Record<string, number>
  attention_reroutes: Record<string, number>
  perturbation_summary: string
  elapsed_ms: number
  metadata?: Record<string, unknown>
}

export interface PreviousStateSummary {
  node_finals: Record<string, number>
  attention_matrix: Record<string, number>
  edge_mean_flux: Record<string, number>
  knockouts: string[]
  clamps: Record<string, number>
  condition_query?: string | null
  scientist_brief?: string | null
}

export interface ModelContext {
  cell_line?: string
  tissue?: string
  passage?: string
  batch_note?: string
}

export interface SearchAndSimulateRequest {
  condition_query: string
  custom_knockouts?: string[]
  custom_clamps?: Record<string, number>
  drugs?: Array<{ target: string; c_drug?: number; concentration?: number; ki: number }>
  drug_perturbations?: Array<{
    target: string
    c_drug?: number
    concentration?: number
    ki: number
  }>
  previous_state_summary?: PreviousStateSummary | null
  t_end?: number
  dense_output_points?: number
  source_node?: string
  target_node?: string
  simulation_id?: string
  use_omnipath?: boolean
  selected_sources?: string[]
  context?: ModelContext
  include_synthetic_lethality?: boolean
  /** Preferred Dual Screen / SL permutation targets. */
  sl_candidate_nodes?: string[]
}

/** Browser-built Reactome + STRING topology for /simulate-dynamic-graph. */
export interface DynamicGraphSimulateRequest {
  query: string
  pathway_id?: string | null
  pathway_name?: string | null
  profile_id: string
  nodes: Array<{ id: string; symbol?: string; y0?: number }>
  edges: Array<{
    source: string
    target: string
    weight?: number
    type?: 'activation' | 'inhibition' | string
  }>
  custom_knockouts?: string[]
  custom_clamps?: Record<string, number>
  drugs?: Array<{ target: string; c_drug?: number; concentration?: number; ki: number }>
  previous_state_summary?: PreviousStateSummary | null
  t_end?: number
  dense_output_points?: number
  source_node?: string
  target_node?: string
  simulation_id?: string
  include_synthetic_lethality?: boolean
  sl_candidate_nodes?: string[]
}

export interface TopologicalAnalysis {
  bottlenecks: Array<{
    node: string
    betweenness: number
    hub_degree: number
    pagerank: number
    role: string
  }>
  feedback_loops: Array<{
    cycle: string[]
    type: string
    length: number
    sign_product: number
  }>
  synthetic_lethal_pairs: Array<{
    pair: string[]
    synergy_score: number
    dual_output_sum: number
    single_a_output: number
    single_b_output: number
    baseline_output: number
    explanation: string
  }>
  elapsed_ms: number
  metadata?: Record<string, unknown>
}

export interface SearchAndSimulateResponse {
  query: string
  profile_id: string
  resolved_graph: PresetDetail
  scrubber_payload: ScrubberPayload
  prioritization: PrioritizationResult
  causal_brief: ReasonResponse
  xai_attributions?: XAIAttributionResult | null
  scientist_reasoning?: ScientistReasoning | null
  state_summary?: PreviousStateSummary | null
  topological_analysis?: TopologicalAnalysis | null
  default_clamps: Record<string, number>
  source_node: string
  target_node: string
  resolve_ms: number
  elapsed_ms: number
  stages: string[]
  metadata: Record<string, unknown>
  /** Omics Fit Score (%) when response came from /omics/simulate. */
  alignment_score?: number | null
  /** Dynamic key e.g. cistron-hypoxia from sample/condition metadata. */
  omics_provenance?: string | null
}

/** Differential-omics feature (matches cistron.models.omics.OmicsFeature). */
export interface OmicsFeature {
  symbol: string
  uniprot_id?: string | null
  ensembl_id?: string | null
  log2_fc: number
  p_value?: number | null
  expression_level?: number | null
}

/** Uploaded / example omics profile. */
export interface OmicsProfile {
  profile_id: string
  sample_name: string
  condition: string
  /** Dynamic key e.g. cistron-hypoxia / cistron-alzheimers-cortex. */
  provenance?: string
  features: Record<string, OmicsFeature>
}

/** Lowercase kebab-case slug for provenance keys. */
export function slugifyOmicsLabel(raw: string): string {
  const s = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  return s || 'profile'
}

/** `cistron-{slugify(condition || sample_name)}` — prefers server-provided provenance. */
export function resolveOmicsProvenance(
  profile: Pick<OmicsProfile, 'condition' | 'sample_name' | 'provenance'>,
): string {
  if (profile.provenance && /^cistron-[a-z0-9-]+$/.test(profile.provenance)) {
    return profile.provenance
  }
  const label = (profile.condition || profile.sample_name || 'profile').trim()
  return `cistron-${slugifyOmicsLabel(label)}`
}

/** Ensure profile carries a dynamic provenance key before library / simulate use. */
export function withOmicsProvenance(profile: OmicsProfile): OmicsProfile {
  return { ...profile, provenance: resolveOmicsProvenance(profile) }
}

/** Optional knobs for POST /api/v1/omics/simulate. */
export interface OmicsSimulateParams {
  t_end?: number
  knockouts?: string[]
  /** Interactive node clamps / titrations y∈[0,1]; 0 = knockout. */
  perturbations?: Record<string, number>
  drugs?: Array<{ target: string; c_drug?: number; concentration?: number; ki: number }>
  dense_output_points?: number
  source_node?: string
  target_node?: string
  simulation_id?: string
  scaling_factor?: number
  baseline_y0?: number
  previous_state_summary?: PreviousStateSummary | null
  include_synthetic_lethality?: boolean
  sl_candidate_nodes?: string[]
  /** Active Studio graph id from last simulate metadata / resolved_graph.id */
  graph_id?: string
  nodes?: Array<{ id: string; symbol?: string; y0?: number }>
  edges?: Array<{ source: string; target: string; weight?: number; type?: string }>
}

/** Soft y₀ bounds used by the backend sigmoid mapper. */
export const OMICS_Y0_MIN = 0.01
export const OMICS_Y0_MAX = 0.99

/** Client-side mirror of OmicsProfile.map_to_initial_states sigmoid. */
export function mapLog2FcToY0(
  log2Fc: number,
  scalingFactor = 1.0,
): number {
  const y = 1 / (1 + Math.exp(-scalingFactor * log2Fc))
  return Math.max(OMICS_Y0_MIN, Math.min(OMICS_Y0_MAX, y))
}

/** Built-in hypoxia RNA-seq demo for instant Studio testing. */
export const EXAMPLE_HYPOXIA_RNASEQ_CSV = `Gene,Log2FC,padj,UniProt
HIF1A,2.40,0.0002,Q16665
EGLN1,-1.80,0.0011,Q9GZT9
VEGFA,1.95,0.0008,P15692
GLUT1,1.55,0.0042,P11166
MTOR,0.65,0.031,P42345
AKT1,0.40,0.082,P31749
O2,-3.20,0.0001,
`

/** Mild / control-like DE table for multi-profile switching demos. */
export const EXAMPLE_CONTROL_RNASEQ_CSV = `Gene,Log2FC,padj,UniProt
HIF1A,0.15,0.42,Q16665
EGLN1,0.05,0.61,Q9GZT9
VEGFA,-0.10,0.55,P15692
GLUT1,0.08,0.48,P11166
MTOR,-0.12,0.39,P42345
AKT1,0.02,0.71,P31749
O2,0.20,0.33,
`

export interface DiseaseImpact {
  overview?: string
  if_activity_up?: string
  if_activity_down?: string
  structure_or_interaction?: string
  mode?: string
}

export interface ProteinMeta {
  gene_symbol: string
  uniprot_id?: string | null
  full_name?: string | null
  localization?: string | null
  function?: string | null
  diseases?: string[]
  plain_english?: string
  why_it_matters?: string
  in_this_network?: string
  analogy?: string | null
  uniprot_url?: string | null
  alphafold_url?: string | null
  entrez_url?: string | null
  sources_used?: string[]
  narrative_mode?: string
  summary?: string | null
  type_of_gene?: string | null
  entrezgene?: string | null
  disease_impact?: DiseaseImpact | null
}

export interface LabControls {
  conditionQuery: string
  clampNode: string
  clampValue: number
  knockouts: string[]
  drugEnabled: boolean
  drugTarget: string
  cDrug: number
  ki: number
  sourceNode: string
  targetNode: string
  selectedSources: string[]
  modelContext?: ModelContext
}

export const DEFAULT_SELECTED_SOURCES = [
  'local',
  'uniprot',
] as const

export interface KnowledgeSource {
  id: string
  label: string
}

/** Full Explorer catalogue fallback when GET /sources is unreachable. */
export const ALL_KNOWLEDGE_SOURCES: KnowledgeSource[] = [
  { id: 'local', label: 'Local curated bank' },
  { id: 'omnipath', label: 'OmniPath' },
  { id: 'signor', label: 'SIGNOR' },
  { id: 'kegg', label: 'KEGG' },
  { id: 'reactome', label: 'Reactome' },
  { id: 'string', label: 'STRING' },
  { id: 'biogrid', label: 'BioGRID' },
  { id: 'uniprot', label: 'UniProt' },
]

export interface SourceSituation {
  id: string
  source: string
  label: string
  query: string
  pathway_id?: string
  description?: string
}

export const SUGGESTION_QUERIES = [
  'Hypoxia-induced angiogenesis',
  'Radiation DNA Damage p53 response',
  "Alzheimer's Amyloid Stress",
  'Glioblastoma EGFR resistance',
  'Glaucoma Oxidative Stress',
  'Triple-negative breast cancer EGFR survival',
] as const

export const FOCUS_SERIES: Record<string, string[]> = {
  hypoxia: ['O2', 'EGLN1', 'HIF1A', 'VEGFA', 'GLUT1'],
  alzheimers: ['APP', 'ROS', 'NFKB1', 'TNF', 'IL1B'],
  tnbc_egfr: ['EGF', 'EGFR', 'KRAS', 'MAPK1', 'MYC'],
  glioblastoma: ['EGF', 'EGFR', 'PIK3CA', 'AKT1', 'MYC', 'STAT3'],
  dna_damage: ['ATM', 'TP53', 'CDKN1A', 'BAX'],
  glaucoma_oxidative: ['ROS', 'NRF2', 'HMOX1', 'TNF'],
  inflammation: ['LPS', 'TLR4', 'NFKB1', 'TNF', 'IL6'],
  mapk: ['EGF', 'EGFR', 'KRAS', 'BRAF', 'MAP2K1', 'MAPK1'],
}
