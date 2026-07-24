/**
 * Multi-compartment Hill-cube ODE engine.
 *
 * Splits each node activity into subcellular pools:
 *   y_i = { cytoplasm, nucleus, mitochondria }
 *
 * Continuity (example, nuclear pool):
 *   dy_nuc/dt = (1/τ)·(W(y) − y_nuc) + k_import·y_cyto − k_export·y_nuc
 *
 * Effective activity for graph wiring uses a weighted blend of compartments
 * (default: cytoplasm + nucleus for TFs, mitochondria for metabolic nodes).
 */

export type CompartmentId = 'cytoplasm' | 'nucleus' | 'mitochondria'

export type CompartmentState = {
  cytoplasm: number
  nucleus: number
  mitochondria: number
}

export type TranslocationRates = {
  /** cytoplasm → nucleus */
  kImportNuc: number
  /** nucleus → cytoplasm */
  kExportNuc: number
  /** cytoplasm → mitochondria */
  kImportMito: number
  /** mitochondria → cytoplasm */
  kExportMito: number
}

export type CompartmentNodeSpec = {
  symbol: string
  tauMin: number
  activityWeight: number
  y0?: Partial<CompartmentState>
  /** Soft clamp on effective y (all pools scaled) */
  clamp?: number | null
  knockout?: boolean
  translocation?: Partial<TranslocationRates>
  /**
   * How effective y is read for upstream Hill inputs.
   * Defaults by gene family (nuclear TFs → nucleus-weighted).
   */
  readout?: Partial<Record<CompartmentId, number>>
}

export type CompartmentEdgeSpec = {
  source: string
  target: string
  sign: number
  mechanism?: string
}

export type CompartmentOdeConfig = {
  hillN?: number
  ec50?: number
  tStart?: number
  tEnd?: number
  dt?: number
  /** Environmental oxygen (0–1). Low O2 → HIF1A nuclear import surge. */
  oxygen?: number
  /** Optional drug inhibiting cytoplasmic activity of a target */
  drug?: { target: string; occupancy: number } | null
}

export type CompartmentTrajectory = {
  time: number[]
  /** symbol → compartment series */
  nodes: Record<string, { cytoplasm: number[]; nucleus: number[]; mitochondria: number[] }>
  /** Effective blended activity series (graph-compatible scrubber) */
  effective: Record<string, number[]>
  metadata: {
    oxygen: number
    elapsedMs: number
    nSteps: number
  }
}

const DEFAULT_RATES: TranslocationRates = {
  kImportNuc: 0.05,
  kExportNuc: 0.08,
  kImportMito: 0.02,
  kExportMito: 0.04,
}

const NUCLEAR_TFS = new Set([
  'HIF1A',
  'EPAS1',
  'ARNT',
  'MYC',
  'TP53',
  'NFKB1',
  'RELA',
  'FOS',
  'JUN',
  'STAT3',
  'STAT1',
  'FOXO1',
  'CREB1',
  'SP1',
])

const MITO_NODES = new Set([
  'BAX',
  'BAK1',
  'CYCS',
  'VDAC1',
  'PPARGC1A',
  'SOD2',
  'MT-CO1',
  'ATP5F1A',
])

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

export function hillActivation(x: number, n = 3, ec50 = 0.5): number {
  const xn = Math.pow(Math.max(0, x), n)
  const kn = Math.pow(ec50, n)
  return xn / (xn + kn + 1e-12)
}

export function hillInhibition(x: number, n = 3, ec50 = 0.5): number {
  return 1 - hillActivation(x, n, ec50)
}

function combineOrAnd(acts: number[], inhs: number[]): number {
  const act =
    acts.length === 0
      ? 1
      : 1 - acts.reduce((acc, a) => acc * (1 - a), 1)
  const inh = inhs.length === 0 ? 1 : inhs.reduce((acc, h) => acc * (1 - h), 1)
  return clamp01(act * inh)
}

export function defaultReadoutWeights(symbol: string): Record<CompartmentId, number> {
  const s = symbol.toUpperCase()
  if (NUCLEAR_TFS.has(s)) return { cytoplasm: 0.25, nucleus: 0.7, mitochondria: 0.05 }
  if (MITO_NODES.has(s)) return { cytoplasm: 0.25, nucleus: 0.05, mitochondria: 0.7 }
  return { cytoplasm: 0.7, nucleus: 0.2, mitochondria: 0.1 }
}

export function effectiveActivity(
  y: CompartmentState,
  weights: Record<CompartmentId, number>,
): number {
  const wSum = weights.cytoplasm + weights.nucleus + weights.mitochondria || 1
  return clamp01(
    (weights.cytoplasm * y.cytoplasm +
      weights.nucleus * y.nucleus +
      weights.mitochondria * y.mitochondria) /
      wSum,
  )
}

/** HIF1A-like: hypoxia drives rapid cyto→nuc import and slows export. */
export function resolveTranslocation(
  symbol: string,
  base: Partial<TranslocationRates> | undefined,
  oxygen: number,
): TranslocationRates {
  const r: TranslocationRates = { ...DEFAULT_RATES, ...base }
  const s = symbol.toUpperCase()
  const hypoxia = clamp01(1 - oxygen)

  if (s === 'HIF1A' || s === 'EPAS1') {
    // Stabilization + nuclear translocation under low O2
    r.kImportNuc = 0.04 + 0.55 * hypoxia
    r.kExportNuc = 0.12 * (0.15 + 0.85 * oxygen)
  } else if (NUCLEAR_TFS.has(s)) {
    r.kImportNuc = 0.06 + 0.1 * hypoxia
  }

  if (MITO_NODES.has(s)) {
    r.kImportMito = 0.05 + 0.15 * hypoxia
  }

  return r
}

function emptyState(partial?: Partial<CompartmentState>): CompartmentState {
  return {
    cytoplasm: clamp01(partial?.cytoplasm ?? 0.15),
    nucleus: clamp01(partial?.nucleus ?? 0.05),
    mitochondria: clamp01(partial?.mitochondria ?? 0.05),
  }
}

type InternalNode = {
  symbol: string
  tau: number
  w: number
  clamp: number | null
  knockout: boolean
  rates: TranslocationRates
  readout: Record<CompartmentId, number>
  incoming: Array<{ src: number; sign: number }>
}

/**
 * Integrate compartmental Hill-cube ODEs with explicit RK4.
 * State vector layout per node: [cyto, nuc, mito].
 */
export function simulateCompartmentOde(
  nodeSpecs: CompartmentNodeSpec[],
  edges: CompartmentEdgeSpec[],
  config: CompartmentOdeConfig = {},
): CompartmentTrajectory {
  const t0 = performance.now()
  const hillN = config.hillN ?? 3
  const ec50 = config.ec50 ?? 0.5
  const tStart = config.tStart ?? 0
  const tEnd = config.tEnd ?? 60
  const dt = config.dt ?? 0.25
  const oxygen = clamp01(config.oxygen ?? 0.35)
  const drug = config.drug ?? null

  const symbols = nodeSpecs.map((n) => n.symbol.toUpperCase())
  const index = new Map(symbols.map((s, i) => [s, i]))

  const nodes: InternalNode[] = nodeSpecs.map((spec) => {
    const symbol = spec.symbol.toUpperCase()
    return {
      symbol,
      tau: Math.max(1e-3, spec.tauMin || 5),
      w: spec.knockout ? 0 : Math.max(0, Math.min(1, spec.activityWeight ?? 1)),
      clamp: spec.clamp ?? null,
      knockout: Boolean(spec.knockout),
      rates: resolveTranslocation(symbol, spec.translocation, oxygen),
      readout: { ...defaultReadoutWeights(symbol), ...spec.readout },
      incoming: [],
    }
  })

  for (const e of edges) {
    const si = index.get(e.source.toUpperCase())
    const ti = index.get(e.target.toUpperCase())
    if (si == null || ti == null) continue
    nodes[ti]!.incoming.push({ src: si, sign: Math.sign(e.sign) || 1 })
  }

  const nNodes = nodes.length
  const dim = nNodes * 3
  let y = new Float64Array(dim)

  for (let i = 0; i < nNodes; i++) {
    const spec = nodeSpecs[i]!
    const s0 = emptyState(spec.y0)
    if (nodes[i]!.knockout) {
      s0.cytoplasm = s0.nucleus = s0.mitochondria = 0
    }
    if (nodes[i]!.clamp != null) {
      const c = clamp01(nodes[i]!.clamp!)
      s0.cytoplasm = s0.nucleus = s0.mitochondria = c
    }
    y[i * 3] = s0.cytoplasm
    y[i * 3 + 1] = s0.nucleus
    y[i * 3 + 2] = s0.mitochondria
  }

  const time: number[] = []
  const series: Record<
    string,
    { cytoplasm: number[]; nucleus: number[]; mitochondria: number[] }
  > = {}
  const effective: Record<string, number[]> = {}
  for (const n of nodes) {
    series[n.symbol] = { cytoplasm: [], nucleus: [], mitochondria: [] }
    effective[n.symbol] = []
  }

  const effAt = (state: Float64Array, i: number): number => {
    const cy = state[i * 3]!
    const nu = state[i * 3 + 1]!
    const mi = state[i * 3 + 2]!
    return effectiveActivity(
      { cytoplasm: cy, nucleus: nu, mitochondria: mi },
      nodes[i]!.readout,
    )
  }

  const fInputs = (state: Float64Array, i: number): number => {
    const acts: number[] = []
    const inhs: number[] = []
    for (const edge of nodes[i]!.incoming) {
      let srcY = effAt(state, edge.src)
      const srcSym = nodes[edge.src]!.symbol
      if (drug && drug.target.toUpperCase() === srcSym) {
        srcY *= 1 - clamp01(drug.occupancy)
      }
      if (edge.sign >= 0) acts.push(hillActivation(srcY, hillN, ec50))
      else inhs.push(hillActivation(srcY, hillN, ec50))
    }
    // Basal drive for source-like nodes with no inputs
    if (!nodes[i]!.incoming.length) {
      if (nodes[i]!.symbol === 'O2') return oxygen
      return 0.35
    }
    return combineOrAnd(acts, inhs)
  }

  const rhs = (state: Float64Array): Float64Array => {
    const dy = new Float64Array(dim)
    for (let i = 0; i < nNodes; i++) {
      const node = nodes[i]!
      const cy = state[i * 3]!
      const nu = state[i * 3 + 1]!
      const mi = state[i * 3 + 2]!

      if (node.clamp != null || node.knockout) {
        dy[i * 3] = dy[i * 3 + 1] = dy[i * 3 + 2] = 0
        continue
      }

      const w = node.w
      const fIn = fInputs(state, i)
      // Production target primarily lands in cytoplasm; TFs also seed nucleus
      const targetCyto = w * fIn
      const targetNuc = NUCLEAR_TFS.has(node.symbol) ? w * fIn * 0.35 : w * fIn * 0.05
      const targetMito = MITO_NODES.has(node.symbol) ? w * fIn * 0.4 : w * fIn * 0.05

      const { kImportNuc, kExportNuc, kImportMito, kExportMito } = node.rates
      const invTau = 1 / node.tau

      // cyto: Hill relaxation + net export to nuc/mito
      dy[i * 3] =
        invTau * (targetCyto - cy) -
        kImportNuc * cy +
        kExportNuc * nu -
        kImportMito * cy +
        kExportMito * mi

      // nucleus: Hill seed + import − export  (task equation)
      dy[i * 3 + 1] =
        invTau * (targetNuc - nu) + kImportNuc * cy - kExportNuc * nu

      // mitochondria
      dy[i * 3 + 2] =
        invTau * (targetMito - mi) + kImportMito * cy - kExportMito * mi
    }
    return dy
  }

  const clipState = (state: Float64Array) => {
    for (let i = 0; i < nNodes; i++) {
      if (nodes[i]!.knockout) {
        state[i * 3] = state[i * 3 + 1] = state[i * 3 + 2] = 0
        continue
      }
      if (nodes[i]!.clamp != null) {
        const c = clamp01(nodes[i]!.clamp!)
        state[i * 3] = state[i * 3 + 1] = state[i * 3 + 2] = c
        continue
      }
      state[i * 3] = clamp01(state[i * 3]!)
      state[i * 3 + 1] = clamp01(state[i * 3 + 1]!)
      state[i * 3 + 2] = clamp01(state[i * 3 + 2]!)
    }
  }

  const record = (t: number, state: Float64Array) => {
    time.push(t)
    for (let i = 0; i < nNodes; i++) {
      const sym = nodes[i]!.symbol
      series[sym]!.cytoplasm.push(state[i * 3]!)
      series[sym]!.nucleus.push(state[i * 3 + 1]!)
      series[sym]!.mitochondria.push(state[i * 3 + 2]!)
      effective[sym]!.push(effAt(state, i))
    }
  }

  clipState(y)
  record(tStart, y)

  const nSteps = Math.max(1, Math.round((tEnd - tStart) / dt))
  let t = tStart
  for (let step = 0; step < nSteps; step++) {
    const k1 = rhs(y)
    const y2 = new Float64Array(dim)
    for (let i = 0; i < dim; i++) y2[i] = y[i]! + 0.5 * dt * k1[i]!
    clipState(y2)
    const k2 = rhs(y2)
    const y3 = new Float64Array(dim)
    for (let i = 0; i < dim; i++) y3[i] = y[i]! + 0.5 * dt * k2[i]!
    clipState(y3)
    const k3 = rhs(y3)
    const y4 = new Float64Array(dim)
    for (let i = 0; i < dim; i++) y4[i] = y[i]! + dt * k3[i]!
    clipState(y4)
    const k4 = rhs(y4)

    for (let i = 0; i < dim; i++) {
      y[i] = y[i]! + (dt / 6) * (k1[i]! + 2 * k2[i]! + 2 * k3[i]! + k4[i]!)
    }
    clipState(y)
    t = tStart + (step + 1) * dt
    // Subsample recording ~ every 1 min equivalent for scrubber alignment
    if ((step + 1) % Math.max(1, Math.round(1 / dt)) === 0 || step === nSteps - 1) {
      record(Math.min(t, tEnd), y)
    }
  }

  return {
    time,
    nodes: series,
    effective,
    metadata: {
      oxygen,
      elapsedMs: performance.now() - t0,
      nSteps,
    },
  }
}

/** Build node specs from a PresetDetail-like graph + interactive clamps. */
export function specsFromGraph(
  graph: {
    nodes: Record<
      string,
      {
        gene_symbol?: string
        tau_min?: number
        activity_weight?: number
        initial_concentration?: number
      }
    >
    edges: Array<{ source: string; target: string; sign: number; mechanism?: string }>
  },
  opts?: {
    perturbations?: Record<string, number>
    maxNodes?: number
  },
): { nodes: CompartmentNodeSpec[]; edges: CompartmentEdgeSpec[] } {
  const maxNodes = opts?.maxNodes ?? 36
  const pert = opts?.perturbations ?? {}
  const keys = Object.keys(graph.nodes).slice(0, maxNodes)
  const keySet = new Set(keys.map((k) => k.toUpperCase()))

  const nodes: CompartmentNodeSpec[] = keys.map((k) => {
    const n = graph.nodes[k]!
    const symbol = (n.gene_symbol || k).toUpperCase()
    const p = pert[symbol] ?? pert[k]
    const y0 = clamp01(n.initial_concentration ?? 0.2)
    return {
      symbol,
      tauMin: n.tau_min ?? 5,
      activityWeight: n.activity_weight ?? 1,
      y0: { cytoplasm: y0, nucleus: y0 * 0.3, mitochondria: y0 * 0.2 },
      knockout: p != null && p <= 1e-6,
      clamp: p != null && p > 1e-6 ? p : null,
    }
  })

  const edges: CompartmentEdgeSpec[] = (graph.edges ?? [])
    .filter(
      (e) => keySet.has(e.source.toUpperCase()) && keySet.has(e.target.toUpperCase()),
    )
    .map((e) => ({
      source: e.source.toUpperCase(),
      target: e.target.toUpperCase(),
      sign: e.sign,
      mechanism: e.mechanism,
    }))

  return { nodes, edges }
}

/** Snapshot compartment state at nearest time index. */
export function compartmentAtTime(
  traj: CompartmentTrajectory,
  symbol: string,
  t: number,
): CompartmentState | null {
  const series = traj.nodes[symbol.toUpperCase()]
  if (!series?.cytoplasm.length) return null
  const times = traj.time
  let idx = 0
  let best = Infinity
  for (let i = 0; i < times.length; i++) {
    const d = Math.abs(times[i]! - t)
    if (d < best) {
      best = d
      idx = i
    }
  }
  return {
    cytoplasm: series.cytoplasm[idx] ?? 0,
    nucleus: series.nucleus[idx] ?? 0,
    mitochondria: series.mitochondria[idx] ?? 0,
  }
}
