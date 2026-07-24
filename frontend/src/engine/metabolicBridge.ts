/**
 * Metabolomics / flux-balance bridge.
 *
 * Couples enzymatic signaling nodes (GLUT1, LDHA, PKM2, …) to metabolite
 * outputs via Michaelis–Menten stoichiometric conversion:
 *
 *   Flux_M = k_cat · y_enzyme(t) · (S / (K_m + S))
 */

import type { ScrubberPayload } from '../api/types'

export type MetaboliteId =
  | 'Glucose'
  | 'G6P'
  | 'Pyruvate'
  | 'Lactate'
  | 'ATP'
  | 'ADP'
  | 'NAD'
  | 'NADH'
  | 'NAD_NADH_ratio'
  | string

export type MetabolicReaction = {
  id: string
  enzyme: string
  substrate: MetaboliteId
  product: MetaboliteId
  /** Catalytic rate scale (conc / min at y=1, saturating S) */
  kCat: number
  /** Michaelis constant (same units as metabolite pool) */
  km: number
  /** Stoichiometric coefficient for product formation */
  stoich?: number
  /** Optional second product (e.g. NADH) */
  coproduct?: { id: MetaboliteId; stoich: number }
  /** Optional cofactor consumption */
  cosubstrate?: { id: MetaboliteId; stoich: number }
}

export type MetabolitePool = Record<MetaboliteId, number>

export type MetabolicFluxPoint = {
  t: number
  fluxes: Record<string, number>
  pools: MetabolitePool
  /** Convenient derived readouts */
  nadRatio: number
  lactateExport: number
  atpYield: number
}

export type MetabolicBridgeResult = {
  time: number[]
  series: MetabolicFluxPoint[]
  enzymesUsed: string[]
  reactions: MetabolicReaction[]
  elapsedMs: number
}

/** Default glycolytic / hypoxia-relevant reaction set. */
export const DEFAULT_METABOLIC_NETWORK: MetabolicReaction[] = [
  {
    id: 'GLUT1_uptake',
    enzyme: 'GLUT1',
    substrate: 'Glucose',
    product: 'G6P',
    kCat: 0.45,
    km: 0.35,
    stoich: 1,
  },
  {
    id: 'SLC2A1_uptake',
    enzyme: 'SLC2A1',
    substrate: 'Glucose',
    product: 'G6P',
    kCat: 0.4,
    km: 0.35,
    stoich: 1,
  },
  {
    id: 'PKM2_pyruvate',
    enzyme: 'PKM2',
    substrate: 'G6P',
    product: 'Pyruvate',
    kCat: 0.55,
    km: 0.25,
    stoich: 1,
    coproduct: { id: 'ATP', stoich: 1 },
    cosubstrate: { id: 'ADP', stoich: 1 },
  },
  {
    id: 'PKM_pyruvate',
    enzyme: 'PKM',
    substrate: 'G6P',
    product: 'Pyruvate',
    kCat: 0.5,
    km: 0.25,
    stoich: 1,
    coproduct: { id: 'ATP', stoich: 1 },
    cosubstrate: { id: 'ADP', stoich: 1 },
  },
  {
    id: 'LDHA_lactate',
    enzyme: 'LDHA',
    substrate: 'Pyruvate',
    product: 'Lactate',
    kCat: 0.7,
    km: 0.2,
    stoich: 1,
    cosubstrate: { id: 'NADH', stoich: 1 },
    coproduct: { id: 'NAD', stoich: 1 },
  },
  {
    id: 'HK2_g6p',
    enzyme: 'HK2',
    substrate: 'Glucose',
    product: 'G6P',
    kCat: 0.35,
    km: 0.3,
    stoich: 1,
    cosubstrate: { id: 'ATP', stoich: 1 },
    coproduct: { id: 'ADP', stoich: 1 },
  },
]

export const DEFAULT_POOLS: MetabolitePool = {
  Glucose: 1.0,
  G6P: 0.25,
  Pyruvate: 0.2,
  Lactate: 0.15,
  ATP: 0.7,
  ADP: 0.3,
  NAD: 0.55,
  NADH: 0.25,
  NAD_NADH_ratio: 2.2,
}

function clamp(v: number, lo = 0, hi = 5): number {
  return Math.max(lo, Math.min(hi, v))
}

/** Michaelis–Menten instantaneous flux. */
export function michaelisMentenFlux(
  yEnzyme: number,
  substrate: number,
  kCat: number,
  km: number,
): number {
  const y = Math.max(0, Math.min(1, yEnzyme))
  const s = Math.max(0, substrate)
  return kCat * y * (s / (km + s + 1e-12))
}

function terminalOrLerp(
  series: number[] | undefined,
  timeSteps: number[],
  t: number,
): number {
  if (!series?.length) return 0
  if (timeSteps.length === 0) return series[series.length - 1] ?? 0
  // Nearest keyframe
  let best = 0
  let bestD = Infinity
  for (let i = 0; i < timeSteps.length; i++) {
    const d = Math.abs((timeSteps[i] ?? 0) - t)
    if (d < bestD) {
      bestD = d
      best = i
    }
  }
  const i1 = Math.min(best, series.length - 1)
  return series[i1] ?? 0
}

function enzymeY(
  payload: ScrubberPayload,
  enzyme: string,
  t: number,
  aliases: Record<string, string[]> = {
    GLUT1: ['GLUT1', 'SLC2A1'],
    SLC2A1: ['SLC2A1', 'GLUT1'],
    PKM2: ['PKM2', 'PKM'],
    PKM: ['PKM', 'PKM2'],
  },
): number {
  const names = aliases[enzyme.toUpperCase()] ?? [enzyme.toUpperCase()]
  for (const n of names) {
    const series = payload.nodes[n] ?? payload.nodes[enzyme]
    if (series?.length) return terminalOrLerp(series, payload.time_steps, t)
  }
  return 0
}

/**
 * Integrate metabolite pools forward in time driven by scrubber enzyme trajectories.
 */
export function simulateMetabolicBridge(
  payload: ScrubberPayload | null | undefined,
  opts?: {
    reactions?: MetabolicReaction[]
    pools0?: MetabolitePool
    dt?: number
  },
): MetabolicBridgeResult {
  const t0 = performance.now()
  const reactions = opts?.reactions ?? DEFAULT_METABOLIC_NETWORK
  const dt = opts?.dt ?? 1
  const times =
    payload?.time_steps?.length && payload.time_steps.length > 1
      ? payload.time_steps
      : Array.from({ length: 61 }, (_, i) => i)

  let pools: MetabolitePool = { ...DEFAULT_POOLS, ...opts?.pools0 }
  const series: MetabolicFluxPoint[] = []
  const enzymesUsed = Array.from(new Set(reactions.map((r) => r.enzyme.toUpperCase())))

  // Skip reactions whose enzyme never appears (keeps flux sparse & honest)
  const activeRx = payload
    ? reactions.filter((r) => enzymeY(payload, r.enzyme, times[0] ?? 0) > 1e-6 ||
        Object.keys(payload.nodes).some(
          (k) =>
            k.toUpperCase() === r.enzyme.toUpperCase() ||
            (r.enzyme === 'GLUT1' && k.toUpperCase() === 'SLC2A1'),
        ))
    : reactions

  for (let i = 0; i < times.length; i++) {
    const t = times[i]!
    const fluxes: Record<string, number> = {}
    const next = { ...pools }

    for (const rx of activeRx) {
      const y = payload ? enzymeY(payload, rx.enzyme, t) : 0.35
      const s = next[rx.substrate] ?? 0
      let flux = michaelisMentenFlux(y, s, rx.kCat, rx.km)

      // Cofactor limitation
      if (rx.cosubstrate) {
        const cos = next[rx.cosubstrate.id] ?? 0
        flux *= cos / (0.15 + cos)
      }

      fluxes[rx.id] = flux
      const stoich = rx.stoich ?? 1
      next[rx.substrate] = clamp((next[rx.substrate] ?? 0) - flux * dt * 0.35)
      next[rx.product] = clamp((next[rx.product] ?? 0) + flux * dt * stoich)

      if (rx.coproduct) {
        next[rx.coproduct.id] = clamp(
          (next[rx.coproduct.id] ?? 0) + flux * dt * rx.coproduct.stoich,
        )
      }
      if (rx.cosubstrate) {
        next[rx.cosubstrate.id] = clamp(
          (next[rx.cosubstrate.id] ?? 0) - flux * dt * rx.cosubstrate.stoich,
        )
      }
    }

    // External glucose feed (tumor microenvironment)
    next.Glucose = clamp((next.Glucose ?? 0) + 0.04 * dt)
    // Slow lactate clearance
    next.Lactate = clamp((next.Lactate ?? 0) * (1 - 0.01 * dt))

    const nad = next.NAD ?? 0.01
    const nadh = next.NADH ?? 0.01
    next.NAD_NADH_ratio = nad / (nadh + 1e-9)

    pools = next
    series.push({
      t,
      fluxes: { ...fluxes },
      pools: { ...pools },
      nadRatio: pools.NAD_NADH_ratio ?? nad / (nadh + 1e-9),
      lactateExport: pools.Lactate ?? 0,
      atpYield: pools.ATP ?? 0,
    })
  }

  return {
    time: times,
    series,
    enzymesUsed,
    reactions: activeRx,
    elapsedMs: performance.now() - t0,
  }
}

/** Sample pools / fluxes at scrubber time t. */
export function metabolicAtTime(
  result: MetabolicBridgeResult,
  t: number,
): MetabolicFluxPoint | null {
  if (!result.series.length) return null
  let best = result.series[0]!
  let bestD = Infinity
  for (const p of result.series) {
    const d = Math.abs(p.t - t)
    if (d < bestD) {
      bestD = d
      best = p
    }
  }
  return best
}
