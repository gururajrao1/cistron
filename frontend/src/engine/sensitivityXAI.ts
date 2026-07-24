/**
 * Global sensitivity / XAI attribution (Sobol-style + SHAP-force proxies).
 *
 * First-order S_i and total-effect S_Ti estimated via one-at-a-time (OAT)
 * Morris/Saltelli-lite sampling of node activity weights and τ.
 */

import type { PresetDetail, ScrubberPayload, XAIAttributionResult } from '../api/types'
import { simulateCompartmentOde, specsFromGraph } from './compartmentOde'

export type SobolIndex = {
  node: string
  /** First-order sensitivity S_i */
  S_i: number
  /** Total-effect S_Ti (≥ S_i) */
  S_Ti: number
  /** Direction of influence on target (+ increases target) */
  signedInfluence: number
}

export type ParamAttribution = {
  node: string
  parameter: 'k_cat' | 'degradation' | 'transport' | 'tau' | 'weight'
  shapForce: number
  value: number
  label: string
}

export type SensitivityXAIResult = {
  targets: string[]
  sobol: SobolIndex[]
  paramForce: ParamAttribution[]
  /** Scatter: S_i vs |Δy| for influence plot */
  scatter: Array<{ node: string; S_i: number; deltaY: number }>
  elapsedMs: number
}

function terminalY(payload: ScrubberPayload | null | undefined, sym: string): number {
  const series = payload?.nodes[sym] ?? payload?.nodes[sym.toUpperCase()]
  if (!series?.length) return 0
  return series[series.length - 1] ?? 0
}

function pickTargets(
  graph: PresetDetail,
  preferred?: string[],
): string[] {
  const have = new Set(
    Object.keys(graph.nodes).map((k) => (graph.nodes[k]?.gene_symbol || k).toUpperCase()),
  )
  const prefs = (preferred?.length ? preferred : ['VEGFA', 'GLUT1', 'MYC', 'LDHA', 'HIF1A']).map(
    (s) => s.toUpperCase(),
  )
  const hits = prefs.filter((p) => have.has(p))
  return hits.length ? hits.slice(0, 3) : Array.from(have).slice(0, 3)
}

function targetScore(trajEffective: Record<string, number[]>, targets: string[]): number {
  let s = 0
  let n = 0
  for (const t of targets) {
    const series = trajEffective[t]
    if (!series?.length) continue
    s += series[series.length - 1] ?? 0
    n++
  }
  return n ? s / n : 0
}

/**
 * Compute Sobol-style indices + SHAP-force parameter attributions for targets.
 */
export function computeSensitivityXAI(opts: {
  graph: PresetDetail | null
  payload?: ScrubberPayload | null
  xai?: XAIAttributionResult | null
  targets?: string[]
  maxNodes?: number
}): SensitivityXAIResult {
  const t0 = performance.now()
  const graph = opts.graph
  if (!graph) {
    return { targets: [], sobol: [], paramForce: [], scatter: [], elapsedMs: 0 }
  }

  const targets = pickTargets(graph, opts.targets)
  const maxNodes = opts.maxNodes ?? 12
  const { nodes, edges } = specsFromGraph(graph, { maxNodes })
  if (!nodes.length) {
    return { targets, sobol: [], paramForce: [], scatter: [], elapsedMs: 0 }
  }

  const base = simulateCompartmentOde(nodes, edges, { tEnd: 30, dt: 1, oxygen: 0.35 })
  const y0 = targetScore(base.effective, targets)

  // Variance via OAT: perturb weight ±δ and τ ±δ
  const delta = 0.35
  const contributions: Array<{
    node: string
    varFirst: number
    varTotal: number
    signed: number
  }> = []

  for (const node of nodes) {
    const up = nodes.map((n) =>
      n.symbol === node.symbol
        ? { ...n, activityWeight: Math.min(1, (n.activityWeight || 1) * (1 + delta)) }
        : { ...n },
    )
    const down = nodes.map((n) =>
      n.symbol === node.symbol
        ? { ...n, activityWeight: Math.max(0.05, (n.activityWeight || 1) * (1 - delta)) }
        : { ...n },
    )
    const tauPert = nodes.map((n) =>
      n.symbol === node.symbol
        ? { ...n, tauMin: Math.max(0.5, (n.tauMin || 5) * (1 + delta)) }
        : { ...n },
    )

    const yUp = targetScore(
      simulateCompartmentOde(up, edges, { tEnd: 30, dt: 1, oxygen: 0.35 }).effective,
      targets,
    )
    const yDown = targetScore(
      simulateCompartmentOde(down, edges, { tEnd: 30, dt: 1, oxygen: 0.35 }).effective,
      targets,
    )
    const yTau = targetScore(
      simulateCompartmentOde(tauPert, edges, { tEnd: 30, dt: 1, oxygen: 0.35 }).effective,
      targets,
    )

    const dMain = ((yUp - y0) ** 2 + (yDown - y0) ** 2) / 2
    const dTotal = dMain + (yTau - y0) ** 2
    const signed = (yUp - yDown) / 2
    contributions.push({
      node: node.symbol,
      varFirst: dMain,
      varTotal: dTotal,
      signed,
    })
  }

  const sumFirst = contributions.reduce((s, c) => s + c.varFirst, 0) || 1
  const sumTotal = contributions.reduce((s, c) => s + c.varTotal, 0) || 1

  const sobol: SobolIndex[] = contributions
    .map((c) => ({
      node: c.node,
      S_i: c.varFirst / sumFirst,
      S_Ti: c.varTotal / sumTotal,
      signedInfluence: c.signed,
    }))
    .sort((a, b) => b.S_Ti - a.S_Ti)

  // SHAP-style force from kinetic parameter proxies
  const paramForce: ParamAttribution[] = []
  for (const s of sobol.slice(0, 8)) {
    const spec = nodes.find((n) => n.symbol === s.node)
    const mag = s.S_Ti * Math.sign(s.signedInfluence || 1)
    paramForce.push({
      node: s.node,
      parameter: 'weight',
      shapForce: mag * 0.45,
      value: spec?.activityWeight ?? 1,
      label: `${s.node} · activity weight wᵢ`,
    })
    paramForce.push({
      node: s.node,
      parameter: 'tau',
      shapForce: mag * -0.2,
      value: spec?.tauMin ?? 5,
      label: `${s.node} · τ (min)`,
    })
    paramForce.push({
      node: s.node,
      parameter: 'degradation',
      shapForce: mag * -0.15,
      value: 1 / Math.max(0.5, spec?.tauMin ?? 5),
      label: `${s.node} · degradation ~1/τ`,
    })
    if (['GLUT1', 'SLC2A1', 'VEGFA', 'EGFR'].includes(s.node)) {
      paramForce.push({
        node: s.node,
        parameter: 'transport',
        shapForce: mag * 0.25,
        value: 0.4,
        label: `${s.node} · transport / secretion`,
      })
    }
    if (['LDHA', 'PKM2', 'HK2', 'MTOR'].includes(s.node)) {
      paramForce.push({
        node: s.node,
        parameter: 'k_cat',
        shapForce: mag * 0.3,
        value: 0.55,
        label: `${s.node} · k_cat (catalytic)`,
      })
    }
  }

  // Blend server XAI importances when present
  if (opts.xai?.node_attributions?.length) {
    for (const a of opts.xai.node_attributions.slice(0, 6)) {
      paramForce.push({
        node: a.node,
        parameter: 'weight',
        shapForce: a.importance * 0.5,
        value: a.importance,
        label: `${a.node} · server SHAP importance`,
      })
    }
  }

  paramForce.sort((a, b) => Math.abs(b.shapForce) - Math.abs(a.shapForce))

  const scatter = sobol.map((s) => ({
    node: s.node,
    S_i: s.S_i,
    deltaY: opts.payload
      ? terminalY(opts.payload, s.node) -
        (opts.payload.nodes[s.node]?.[0] ?? 0)
      : s.signedInfluence,
  }))

  return {
    targets,
    sobol,
    paramForce: paramForce.slice(0, 24),
    scatter,
    elapsedMs: performance.now() - t0,
  }
}
