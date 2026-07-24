/**
 * Client-side pairwise combinatorial / synthetic-lethality screen.
 *
 * Synergy (Bliss Independence excess):
 *   S = (E_A + E_B) − E_AB
 * where E = 1 − viability_treated / viability_baseline
 *
 * Loewe-style excess also reported as S_loewe when single-agent effects are large.
 */

import {
  simulateCompartmentOde,
  specsFromGraph,
  type CompartmentTrajectory,
} from './compartmentOde'
import type { PresetDetail } from '../api/types'

export type ComboScreenParams = {
  /** Max genes to include in N×N screen (pairs = N(N−1)/2). */
  maxCandidates?: number
  /** Viability readouts (default: top effectors). */
  readoutNodes?: string[]
  /** Dual-KO viability fraction below this → synthetic lethal flag. */
  lethalThreshold?: number
  /** Bliss synergy above this → synergistic. */
  synergyThreshold?: number
  tEnd?: number
  dt?: number
  oxygen?: number
}

export type ComboPairResult = {
  a: string
  b: string
  viabilityBaseline: number
  viabilityA: number
  viabilityB: number
  viabilityAB: number
  effectA: number
  effectB: number
  effectAB: number
  /** Bliss excess S = E_A + E_B − E_AB (positive → synergy / SL) */
  blissSynergy: number
  loeweExcess: number
  syntheticLethal: boolean
  synergistic: boolean
}

export type DualKnockoutScreenResult = {
  candidates: string[]
  readouts: string[]
  pairs: ComboPairResult[]
  /** Dense matrix keyed `${a}|${b}` with bliss synergy (symmetric). */
  matrix: Record<string, number>
  lethalPairs: ComboPairResult[]
  elapsedMs: number
}

function terminalEffective(traj: CompartmentTrajectory, sym: string): number {
  const series = traj.effective[sym.toUpperCase()]
  if (!series?.length) return 0
  return series[series.length - 1] ?? 0
}

function viability(
  traj: CompartmentTrajectory,
  readouts: string[],
): number {
  if (!readouts.length) {
    const all = Object.values(traj.effective)
    if (!all.length) return 0
    return all.reduce((s, arr) => s + (arr[arr.length - 1] ?? 0), 0) / all.length
  }
  let s = 0
  let n = 0
  for (const r of readouts) {
    const v = terminalEffective(traj, r)
    if (Number.isFinite(v)) {
      s += v
      n++
    }
  }
  return n ? s / n : 0
}

function effect(vTreat: number, vBase: number): number {
  if (vBase < 1e-9) return 0
  return Math.max(0, Math.min(1.5, 1 - vTreat / vBase))
}

function pickCandidates(
  graph: PresetDetail,
  maxN: number,
  preferred?: string[],
): string[] {
  const degree = new Map<string, number>()
  for (const e of graph.edges ?? []) {
    const s = e.source.toUpperCase()
    const t = e.target.toUpperCase()
    degree.set(s, (degree.get(s) ?? 0) + 1)
    degree.set(t, (degree.get(t) ?? 0) + 1)
  }
  const skip = new Set(['O2', 'ROS', 'LPS', 'ATP', 'GTP', 'GLUCOSE'])
  const preferredUp = (preferred ?? []).map((p) => p.toUpperCase()).filter(Boolean)
  const ranked = Object.keys(graph.nodes)
    .map((k) => (graph.nodes[k]?.gene_symbol || k).toUpperCase())
    .filter((s) => !skip.has(s))
    .sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0))

  const out: string[] = []
  for (const p of preferredUp) {
    if (ranked.includes(p) && !out.includes(p)) out.push(p)
  }
  for (const s of ranked) {
    if (out.length >= maxN) break
    if (!out.includes(s)) out.push(s)
  }
  return out.slice(0, maxN)
}

function defaultReadouts(graph: PrefetDetailLike, candidates: string[]): string[] {
  const prefer = ['VEGFA', 'GLUT1', 'SLC2A1', 'MYC', 'LDHA', 'CCND1', 'BAX', 'HIF1A']
  const have = new Set(
    Object.keys(graph.nodes).map((k) => (graph.nodes[k]?.gene_symbol || k).toUpperCase()),
  )
  const hits = prefer.filter((p) => have.has(p))
  if (hits.length) return hits.slice(0, 4)
  return candidates.slice(0, 3)
}

type PrefetDetailLike = {
  nodes: PresetDetail['nodes']
  edges: PresetDetail['edges']
}

function simWithKos(
  graph: PresetDetail,
  kos: string[],
  params: { tEnd: number; dt: number; oxygen: number },
): CompartmentTrajectory {
  const { nodes, edges } = specsFromGraph(graph, {
    perturbations: Object.fromEntries(kos.map((k) => [k, 0])),
    maxNodes: 36,
  })
  // Force KO flags even if not in perturbations map keys matching
  for (const n of nodes) {
    if (kos.includes(n.symbol)) {
      n.knockout = true
      n.clamp = 0
    }
  }
  return simulateCompartmentOde(nodes, edges, {
    tEnd: params.tEnd,
    dt: params.dt,
    oxygen: params.oxygen,
  })
}

/**
 * Run all pairwise knockouts among top candidates against baseline y₆₀ viability.
 */
export function runDualKnockoutScreen(
  networkNodes: PresetDetail | null,
  ODEParams?: ComboScreenParams & { preferredCandidates?: string[] },
): DualKnockoutScreenResult {
  const t0 = performance.now()
  if (!networkNodes || !Object.keys(networkNodes.nodes ?? {}).length) {
    return {
      candidates: [],
      readouts: [],
      pairs: [],
      matrix: {},
      lethalPairs: [],
      elapsedMs: 0,
    }
  }

  const maxCandidates = ODEParams?.maxCandidates ?? 8
  const lethalThreshold = ODEParams?.lethalThreshold ?? 0.35
  const synergyThreshold = ODEParams?.synergyThreshold ?? 0.08
  const tEnd = ODEParams?.tEnd ?? 40
  const dt = ODEParams?.dt ?? 1
  const oxygen = ODEParams?.oxygen ?? 0.3

  const candidates = pickCandidates(
    networkNodes,
    maxCandidates,
    ODEParams?.preferredCandidates,
  )
  const readouts =
    ODEParams?.readoutNodes?.map((r) => r.toUpperCase()) ??
    defaultReadouts(networkNodes, candidates)

  const baseTraj = simWithKos(networkNodes, [], { tEnd, dt, oxygen })
  const vBase = viability(baseTraj, readouts)

  const singleCache = new Map<string, number>()
  const getSingle = (sym: string): number => {
    if (singleCache.has(sym)) return singleCache.get(sym)!
    const traj = simWithKos(networkNodes, [sym], { tEnd, dt, oxygen })
    const v = viability(traj, readouts)
    singleCache.set(sym, v)
    return v
  }

  const pairs: ComboPairResult[] = []
  const matrix: Record<string, number> = {}

  for (let i = 0; i < candidates.length; i++) {
    for (let j = i + 1; j < candidates.length; j++) {
      const a = candidates[i]!
      const b = candidates[j]!
      const vA = getSingle(a)
      const vB = getSingle(b)
      const trajAB = simWithKos(networkNodes, [a, b], { tEnd, dt, oxygen })
      const vAB = viability(trajAB, readouts)

      const effectA = effect(vA, vBase)
      const effectB = effect(vB, vBase)
      const effectAB = effect(vAB, vBase)
      const blissSynergy = effectA + effectB - effectAB

      // Loewe excess proxy: dual effect beyond max single
      const loeweExcess = effectAB - Math.max(effectA, effectB)

      const syntheticLethal =
        vBase > 1e-6 && vAB / vBase < lethalThreshold && blissSynergy > synergyThreshold * 0.5
      const synergistic = blissSynergy >= synergyThreshold

      const row: ComboPairResult = {
        a,
        b,
        viabilityBaseline: vBase,
        viabilityA: vA,
        viabilityB: vB,
        viabilityAB: vAB,
        effectA,
        effectB,
        effectAB,
        blissSynergy,
        loeweExcess,
        syntheticLethal,
        synergistic,
      }
      pairs.push(row)
      matrix[`${a}|${b}`] = blissSynergy
      matrix[`${b}|${a}`] = blissSynergy
      matrix[`${a}|${a}`] = effectA
      matrix[`${b}|${b}`] = effectB
    }
  }

  pairs.sort((x, y) => y.blissSynergy - x.blissSynergy)
  const lethalPairs = pairs.filter((p) => p.syntheticLethal)

  return {
    candidates,
    readouts,
    pairs,
    matrix,
    lethalPairs,
    elapsedMs: performance.now() - t0,
  }
}
