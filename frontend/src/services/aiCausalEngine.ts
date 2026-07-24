/**
 * Client-side causal network analyzer for dual-knockout / synthetic-lethality
 * hypothesis generation (AI Scientist Hypothesis Cards).
 */

import type { PresetDetail, ScrubberPayload, TopologicalAnalysis } from '../api/types'

export type CausalEdgeInput = {
  source: string
  target: string
  sign?: number
  is_stimulation?: boolean
  is_inhibition?: boolean
  mechanism?: string
}

export type CausalGraphInput = {
  nodes: Record<string, unknown> | string[]
  edges: CausalEdgeInput[]
}

export type CausalHypothesis = {
  id: string
  /** e.g. "HIF1A + MTOR Synthetic Lethality" */
  title: string
  targets: [string, string]
  synergyScore: number | null
  /** Primary vs bypass / backup-loop collapse narrative */
  pathwayCollapse: string
  /** Expected downstream cellular phenotype */
  phenotypicImpact: string
  /** Recommended wet-lab validation */
  suggestedAssay: string
  /** Nodes reached by both targets (shared sinks) */
  convergenceNodes: string[]
  /** Parallel backup / exclusive downstream arms */
  bypassNodes: string[]
  /** Feedback cycles touching either target */
  feedbackLoops: string[][]
  /** Structured prompt for an LLM agent */
  llmPrompt: string
  source: 'dual_clamp' | 'synthetic_lethality' | 'screen'
}

export type CausalHypothesisBundle = {
  clamped: Array<{ symbol: string; value: number }>
  hypotheses: CausalHypothesis[]
  llmPrompt: string
  elapsedMs: number
}

function normSym(s: string): string {
  return String(s ?? '')
    .trim()
    .toUpperCase()
}

function nodeList(nodes: CausalGraphInput['nodes']): string[] {
  if (Array.isArray(nodes)) return nodes.map(normSym).filter(Boolean)
  return Object.keys(nodes ?? {}).map(normSym).filter(Boolean)
}

function buildAdj(edges: CausalEdgeInput[]): Map<string, Array<{ tgt: string; sign: number; mech: string }>> {
  const adj = new Map<string, Array<{ tgt: string; sign: number; mech: string }>>()
  for (const e of edges ?? []) {
    const s = normSym(e.source)
    const t = normSym(e.target)
    if (!s || !t || s === t) continue
    let sign = typeof e.sign === 'number' ? Math.sign(e.sign) || 1 : 1
    if (e.is_inhibition && !e.is_stimulation) sign = -1
    else if (e.is_stimulation && !e.is_inhibition) sign = 1
    const mech = e.mechanism || (sign < 0 ? 'inhibition' : 'activation')
    if (!adj.has(s)) adj.set(s, [])
    adj.get(s)!.push({ tgt: t, sign, mech })
  }
  return adj
}

/** BFS reachable set + shortest-path parent map (unweighted). */
function downstreamReach(
  adj: Map<string, Array<{ tgt: string; sign: number; mech: string }>>,
  root: string,
  maxDepth = 6,
): { reach: Set<string>; parent: Map<string, string>; depth: Map<string, number> } {
  const reach = new Set<string>()
  const parent = new Map<string, string>()
  const depth = new Map<string, number>([[root, 0]])
  const q: string[] = [root]
  while (q.length) {
    const u = q.shift()!
    const d = depth.get(u) ?? 0
    if (d >= maxDepth) continue
    for (const { tgt } of adj.get(u) ?? []) {
      if (reach.has(tgt) || tgt === root) continue
      reach.add(tgt)
      parent.set(tgt, u)
      depth.set(tgt, d + 1)
      q.push(tgt)
    }
  }
  return { reach, parent, depth }
}

function reconstructPath(parent: Map<string, string>, root: string, leaf: string): string[] {
  const path = [leaf]
  let cur = leaf
  const guard = new Set<string>()
  while (parent.has(cur) && !guard.has(cur)) {
    guard.add(cur)
    const p = parent.get(cur)!
    path.push(p)
    cur = p
    if (cur === root) break
  }
  if (path[path.length - 1] !== root) path.push(root)
  return path.reverse()
}

function terminalY(payload: ScrubberPayload | null | undefined, sym: string): number {
  if (!payload?.nodes) return 0
  const series = payload.nodes[sym] ?? payload.nodes[normSym(sym)]
  if (!series?.length) return 0
  return series[series.length - 1] ?? 0
}

function deltaMap(
  treated: ScrubberPayload | null | undefined,
  untreated: ScrubberPayload | null | undefined,
  exclude: Set<string>,
): Array<{ sym: string; dy: number; yT: number }> {
  if (!treated?.nodes) return []
  const keys = new Set([
    ...Object.keys(treated.nodes),
    ...Object.keys(untreated?.nodes ?? {}),
  ])
  const rows: Array<{ sym: string; dy: number; yT: number }> = []
  for (const raw of keys) {
    const sym = normSym(raw)
    if (exclude.has(sym)) continue
    const yT = terminalY(treated, raw)
    const yU = untreated ? terminalY(untreated, raw) : terminalY(treated, raw) // fallback: use t0
    const y0 = untreated
      ? yU
      : (treated.nodes[raw]?.[0] ?? treated.nodes[sym]?.[0] ?? 0)
    const dy = untreated ? yT - yU : yT - y0
    if (Math.abs(dy) < 0.015) continue
    rows.push({ sym, dy, yT })
  }
  return rows.sort((a, b) => a.dy - b.dy)
}

const PHENOTYPE_HINTS: Array<{ re: RegExp; label: string }> = [
  { re: /VEGF|ANGPT|KDR|FLT1|TEK/, label: 'angiogenic' },
  { re: /LDHA|GLUT|SLC2A|HK[12]|PKM|PFK/, label: 'glycolytic' },
  { re: /MYC|CCND|CDK|E2F|PCNA/, label: 'proliferative' },
  { re: /BAX|BAK|CASP|BCL2|BIM|PUMA/, label: 'apoptotic' },
  { re: /MTOR|RPS6|EIF4|S6K/, label: 'translational / mTOR' },
  { re: /HIF|EPAS|VHL/, label: 'hypoxia-response' },
  { re: /NFKB|RELA|TNF|IL6|CXCL/, label: 'inflammatory' },
]

function phenotypeFromNodes(syms: string[]): string {
  const hits = new Set<string>()
  for (const s of syms) {
    for (const h of PHENOTYPE_HINTS) {
      if (h.re.test(s)) hits.add(h.label)
    }
  }
  if (!hits.size) {
    return `Systemic attenuation of shared sinks (${syms.slice(0, 3).join(', ') || 'network outputs'}).`
  }
  const list = Array.from(hits)
  if (list.length === 1) {
    return `Predicted ${list[0]} pathway collapse downstream of the dual clamp.`
  }
  if (list.length === 2) {
    return `Complete ${list[0]} & ${list[1]} shutdown via convergent inhibition.`
  }
  return `Multi-axis phenotype: ${list.slice(0, 3).join(', ')} programs suppressed.`
}

function assayFromNodes(syms: string[], targets: [string, string]): string {
  const readout = syms.slice(0, 4)
  const qpcr = readout.length
    ? `qPCR / Western for ${readout.join('/')}`
    : `qPCR for ${targets[0]}/${targets[1]} pathway readouts`
  return `${qpcr}; Annexin V / Caspase-3/7 apoptosis assay; optional Seahorse glycolytic stress test.`
}

function formatPath(nodes: string[]): string {
  return nodes.join(' -> ')
}

function pairKey(a: string, b: string): string {
  return [normSym(a), normSym(b)].sort().join('+')
}

function analyzePair(args: {
  a: string
  b: string
  adj: Map<string, Array<{ tgt: string; sign: number; mech: string }>>
  feedbackLoops: string[][]
  simDeltas: Array<{ sym: string; dy: number; yT: number }>
  synergyScore: number | null
  explanation?: string
  source: CausalHypothesis['source']
}): CausalHypothesis {
  const { a, b, adj, feedbackLoops, simDeltas, synergyScore, explanation, source } = args
  const ra = downstreamReach(adj, a)
  const rb = downstreamReach(adj, b)

  const convergence: string[] = []
  for (const n of ra.reach) {
    if (rb.reach.has(n)) convergence.push(n)
  }
  // Prefer high-impact sim sinks among convergence
  const convRank = new Map(simDeltas.map((d, i) => [d.sym, i]))
  convergence.sort((x, y) => (convRank.get(x) ?? 999) - (convRank.get(y) ?? 999))

  const bypassA = [...ra.reach].filter((n) => !rb.reach.has(n))
  const bypassB = [...rb.reach].filter((n) => !ra.reach.has(n))
  const bypassNodes = [...bypassA.slice(0, 4), ...bypassB.slice(0, 4)]

  const loops = feedbackLoops.filter(
    (c) => c.some((n) => normSym(n) === a || normSym(n) === b) || c.some((n) => convergence.includes(normSym(n))),
  )

  const topConv = convergence.slice(0, 5)
  const topCollapse = simDeltas.filter((d) => d.dy < -0.02).slice(0, 6)

  // Example primary / bypass paths to a shared sink
  const sink = topConv[0] ?? topCollapse[0]?.sym ?? null
  let primaryPath = [a]
  let bypassPath = [b]
  if (sink) {
    if (ra.reach.has(sink)) primaryPath = reconstructPath(ra.parent, a, sink)
    if (rb.reach.has(sink)) bypassPath = reconstructPath(rb.parent, b, sink)
  }

  const pathwayCollapse = [
    explanation?.trim() || null,
    sink
      ? `Primary arm: ${formatPath(primaryPath)}. Bypass / parallel arm: ${formatPath(bypassPath)}.`
      : `${a} and ${b} lack a short shared sink within depth-6 reach — synergy may be indirect.`,
    topConv.length
      ? `Convergence nodes: ${topConv.join(', ')}.`
      : 'No strong topological convergence detected.',
    bypassNodes.length
      ? `Exclusive / backup branches: ${bypassNodes.slice(0, 6).join(', ')}.`
      : null,
    loops.length
      ? `Feedback loops engaged: ${loops
          .slice(0, 2)
          .map((c) => c.join(' -> '))
          .join('; ')}.`
      : null,
  ]
    .filter(Boolean)
    .join(' ')

  const impactSyms = [
    ...topConv,
    ...topCollapse.map((d) => d.sym),
  ]
  const phenotypicImpact = phenotypeFromNodes(impactSyms)
  const collapseDetail =
    topCollapse.length > 0
      ? ` Strongest Δy60: ${topCollapse
          .slice(0, 4)
          .map((d) => `${d.sym} (${d.dy >= 0 ? '+' : ''}${d.dy.toFixed(2)})`)
          .join(', ')}.`
      : ''
  const phenotypic = `${phenotypicImpact}${collapseDetail}`

  const suggestedAssay = assayFromNodes(topConv.length ? topConv : topCollapse.map((d) => d.sym), [a, b])

  const title =
    synergyScore != null && synergyScore > 0.05
      ? `${a} + ${b} Synthetic Lethality`
      : `${a} + ${b} Dual Knockout`

  const llmPrompt = buildPairLlmPrompt({
    a,
    b,
    title,
    pathwayCollapse,
    phenotypicImpact: phenotypic,
    suggestedAssay,
    convergence: topConv,
    bypassNodes,
    loops,
    synergyScore,
  })

  return {
    id: `${source}-${pairKey(a, b)}`,
    title,
    targets: [a, b],
    synergyScore,
    pathwayCollapse,
    phenotypicImpact: phenotypic,
    suggestedAssay,
    convergenceNodes: topConv,
    bypassNodes: bypassNodes.slice(0, 8),
    feedbackLoops: loops.slice(0, 3),
    llmPrompt,
    source,
  }
}

function buildPairLlmPrompt(p: {
  a: string
  b: string
  title: string
  pathwayCollapse: string
  phenotypicImpact: string
  suggestedAssay: string
  convergence: string[]
  bypassNodes: string[]
  loops: string[][]
  synergyScore: number | null
}): string {
  return [
    'You are a systems-biology AI Scientist. Summarize the molecular mechanism of action for this dual intervention.',
    '',
    `Hypothesis: ${p.title}`,
    `Clamped targets: ${p.a}=0 (KO), ${p.b}=0 (KO)`,
    p.synergyScore != null ? `Synergy score: ${p.synergyScore.toFixed(3)}` : 'Synergy score: n/a (live dual clamp)',
    '',
    'Causal graph findings:',
    `- Convergence / shared sinks: ${p.convergence.join(', ') || 'none'}`,
    `- Parallel backup / exclusive branches: ${p.bypassNodes.join(', ') || 'none'}`,
    `- Feedback loops: ${
      p.loops.length ? p.loops.map((c) => c.join(' -> ')).join(' ; ') : 'none detected'
    }`,
    '',
    `Pathway collapse draft: ${p.pathwayCollapse}`,
    `Phenotypic impact draft: ${p.phenotypicImpact}`,
    `Suggested assay draft: ${p.suggestedAssay}`,
    '',
    'Write 3 short paragraphs:',
    '1) Primary vs bypass inhibition mechanism',
    '2) Why the combination is (or is not) synthetically lethal',
    '3) One decisive validation experiment',
  ].join('\n')
}

/**
 * Identify clamped nodes, trace shared / exclusive downstream pathways,
 * and emit Hypothesis Cards + a structured LLM prompt.
 */
export function generateCausalHypothesis(
  nodes: CausalGraphInput['nodes'] | PresetDetail['nodes'],
  edges: CausalEdgeInput[] | PresetDetail['edges'],
  activePerturbations: Record<string, number>,
  simulationResults?: {
    treated?: ScrubberPayload | null
    untreated?: ScrubberPayload | null
    topologicalAnalysis?: TopologicalAnalysis | null
  } | ScrubberPayload | null,
): CausalHypothesisBundle {
  const t0 = performance.now()
  const adj = buildAdj((edges ?? []) as CausalEdgeInput[])
  const allNodes = nodeList(nodes as CausalGraphInput['nodes'])

  const clamped = Object.entries(activePerturbations ?? {})
    .map(([symbol, value]) => ({ symbol: normSym(symbol), value: Number(value) }))
    .filter((c) => c.symbol && Number.isFinite(c.value))
    .sort((a, b) => a.symbol.localeCompare(b.symbol))

  const kos = clamped.filter((c) => c.value <= 1e-6).map((c) => c.symbol)
  // Prefer hard KOs; fall back to any clamps when titrating
  const focus = kos.length >= 2 ? kos : clamped.map((c) => c.symbol)

  const simBag =
    simulationResults &&
    typeof simulationResults === 'object' &&
    ('treated' in simulationResults ||
      'untreated' in simulationResults ||
      'topologicalAnalysis' in simulationResults)
      ? (simulationResults as {
          treated?: ScrubberPayload | null
          untreated?: ScrubberPayload | null
          topologicalAnalysis?: TopologicalAnalysis | null
        })
      : simulationResults &&
          typeof simulationResults === 'object' &&
          'nodes' in simulationResults &&
          'time_steps' in simulationResults
        ? {
            treated: simulationResults as ScrubberPayload,
            untreated: null as ScrubberPayload | null,
            topologicalAnalysis: null as TopologicalAnalysis | null,
          }
        : {
            treated: null as ScrubberPayload | null,
            untreated: null as ScrubberPayload | null,
            topologicalAnalysis: null as TopologicalAnalysis | null,
          }

  const topo = simBag.topologicalAnalysis ?? null
  const feedbackLoops = (topo?.feedback_loops ?? []).map((f) =>
    (f.cycle ?? []).map(normSym).filter(Boolean),
  )
  const exclude = new Set(focus)
  const simDeltas = deltaMap(simBag.treated ?? null, simBag.untreated ?? null, exclude)

  const hypotheses: CausalHypothesis[] = []
  const seen = new Set<string>()

  // 1) Synthetic lethality pairs from Dual Screen
  for (const pair of topo?.synthetic_lethal_pairs ?? []) {
    const [rawA, rawB] = Array.isArray(pair.pair) ? pair.pair : []
    const a = normSym(rawA)
    const b = normSym(rawB)
    if (!a || !b) continue
    const key = pairKey(a, b)
    if (seen.has(key)) continue
    seen.add(key)
    hypotheses.push(
      analyzePair({
        a,
        b,
        adj,
        feedbackLoops,
        simDeltas,
        synergyScore: Number(pair.synergy_score ?? 0),
        explanation: pair.explanation || undefined,
        source: 'synthetic_lethality',
      }),
    )
  }

  // 2) Live dual (or multi) clamps on the canvas — generate cards for top pairs
  if (focus.length >= 2) {
    const pairs: Array<[string, string]> = []
    for (let i = 0; i < focus.length; i++) {
      for (let j = i + 1; j < focus.length; j++) {
        pairs.push([focus[i]!, focus[j]!])
      }
    }
    // Cap combinatorial explosion
    for (const [a, b] of pairs.slice(0, 6)) {
      const key = pairKey(a, b)
      if (seen.has(key)) {
        // Promote existing SL card to also reflect live dual clamp
        const existing = hypotheses.find((h) => h.id.endsWith(key) || pairKey(h.targets[0], h.targets[1]) === key)
        if (existing && existing.source === 'synthetic_lethality') {
          existing.source = 'screen'
        }
        continue
      }
      seen.add(key)
      // Skip pairs with no graph footprint
      if (!allNodes.includes(a) && !adj.has(a)) continue
      if (!allNodes.includes(b) && !adj.has(b)) continue
      hypotheses.push(
        analyzePair({
          a,
          b,
          adj,
          feedbackLoops,
          simDeltas,
          synergyScore: null,
          source: 'dual_clamp',
        }),
      )
    }
  }

  // Rank: synergy first, then stronger simulated collapse
  hypotheses.sort((x, y) => {
    const sx = x.synergyScore ?? -1
    const sy = y.synergyScore ?? -1
    if (sy !== sx) return sy - sx
    return y.convergenceNodes.length - x.convergenceNodes.length
  })

  const top = hypotheses.slice(0, 5)
  const llmPrompt =
    top.length === 0
      ? [
          'You are a systems-biology AI Scientist.',
          `Active clamps: ${
            clamped.length
              ? clamped.map((c) => `${c.symbol}=${c.value}`).join(', ')
              : 'none'
          }`,
          'No dual-target hypothesis yet. Wait for two simultaneous clamps or a Synthetic Lethality / Dual Screen run.',
        ].join('\n')
      : [
          'You are a systems-biology AI Scientist reviewing combinatorial interventions.',
          `Active clamps: ${clamped.map((c) => `${c.symbol}=${c.value}`).join(', ') || 'none'}`,
          '',
          ...top.map(
            (h, i) =>
              `### Card ${i + 1}: ${h.title}\n${h.llmPrompt}`,
          ),
          '',
          'Return a concise ranked summary of the strongest synthetic-lethality rationale.',
        ].join('\n')

  return {
    clamped,
    hypotheses: top,
    llmPrompt,
    elapsedMs: performance.now() - t0,
  }
}

/** Convenience: build from Lab-shaped PresetDetail + perturbations + runs. */
export function generateHypothesesFromLab(input: {
  graph: PresetDetail | null
  perturbations: Record<string, number>
  treated?: ScrubberPayload | null
  untreated?: ScrubberPayload | null
  topologicalAnalysis?: TopologicalAnalysis | null
}): CausalHypothesisBundle {
  if (!input.graph) {
    return {
      clamped: Object.entries(input.perturbations ?? {}).map(([symbol, value]) => ({
        symbol: normSym(symbol),
        value: Number(value),
      })),
      hypotheses: [],
      llmPrompt: 'No causal graph loaded.',
      elapsedMs: 0,
    }
  }
  return generateCausalHypothesis(
    input.graph.nodes,
    input.graph.edges,
    input.perturbations,
    {
      treated: input.treated ?? null,
      untreated: input.untreated ?? null,
      topologicalAnalysis: input.topologicalAnalysis ?? null,
    },
  )
}
