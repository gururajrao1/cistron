/**
 * Semantic-zoom pathway modules — map genes → coarse biological programs.
 * Used when the network is zoomed out (Google-Maps-style LOD).
 */

export type PathwayModuleId =
  | 'hypoxia'
  | 'glycolysis'
  | 'growth'
  | 'cell_cycle'
  | 'apoptosis'
  | 'inflammation'
  | 'other'

export type PathwayModuleDef = {
  id: PathwayModuleId
  label: string
  /** Short biologist-facing gloss. */
  gloss: string
  genes: readonly string[]
}

export const PATHWAY_MODULES: readonly PathwayModuleDef[] = [
  {
    id: 'hypoxia',
    label: 'Hypoxia / HIF',
    gloss: 'O₂ sensing & angiogenesis',
    genes: [
      'O2',
      'HIF1A',
      'ARNT',
      'EPAS1',
      'EGLN1',
      'PHD',
      'VHL',
      'VEGFA',
      'BNIP3',
      'ANGPT2',
      'EPO',
    ],
  },
  {
    id: 'glycolysis',
    label: 'Glycolysis',
    gloss: 'Sugar → lactate / Warburg',
    genes: [
      'GLUT1',
      'SLC2A1',
      'HK2',
      'PKM2',
      'LDHA',
      'PDK1',
      'PDH',
      'PFKFB3',
      'GAPDH',
    ],
  },
  {
    id: 'growth',
    label: 'Growth signaling',
    gloss: 'RTK → MAPK / PI3K–AKT',
    genes: [
      'EGF',
      'EGFR',
      'INS',
      'INSULIN',
      'IGF1',
      'FGF',
      'PDGF',
      'HGF',
      'WNT',
      'NOTCH',
      'KRAS',
      'HRAS',
      'NRAS',
      'BRAF',
      'RAF1',
      'ARAF',
      'RAF',
      'MAP2K1',
      'MAP2K2',
      'MEK',
      'MAPK1',
      'MAPK3',
      'ERK',
      'PIK3CA',
      'PI3K',
      'AKT1',
      'AKT2',
      'AKT',
      'MTOR',
      'PTEN',
      'RHEB',
      'SOS1',
      'GRB2',
      'SRC',
      'MYC',
      'VEGFR',
      'KDR',
    ],
  },
  {
    id: 'cell_cycle',
    label: 'Cell cycle',
    gloss: 'Proliferation checkpoint',
    genes: ['CCND1', 'CDKN1A', 'TP53', 'RB1', 'E2F1', 'CDK4', 'CDK6', 'CDKN2A'],
  },
  {
    id: 'apoptosis',
    label: 'Apoptosis',
    gloss: 'Death / survival balance',
    genes: ['BAX', 'BCL2', 'CASP3', 'CASP9', 'BID', 'BAK1', 'MCL1'],
  },
  {
    id: 'inflammation',
    label: 'Inflammation',
    gloss: 'Cytokine / NF-κB axis',
    genes: [
      'TNF',
      'TNFR',
      'IL6',
      'LPS',
      'NFKB1',
      'RELA',
      'STAT3',
      'STAT1',
      'JAK1',
      'JAK2',
      'FOS',
      'JUN',
      'ROS',
    ],
  },
] as const

const GENE_TO_MODULE: Record<string, PathwayModuleId> = (() => {
  const m: Record<string, PathwayModuleId> = {}
  for (const mod of PATHWAY_MODULES) {
    for (const g of mod.genes) m[g.toUpperCase()] = mod.id
  }
  return m
})()

export function moduleForGene(symbol: string): PathwayModuleId {
  return GENE_TO_MODULE[symbol.toUpperCase()] ?? 'other'
}

export function moduleDef(id: PathwayModuleId): PathwayModuleDef {
  if (id === 'other') {
    return {
      id: 'other',
      label: 'Other nodes',
      gloss: 'Unassigned network members',
      genes: [],
    }
  }
  return PATHWAY_MODULES.find((m) => m.id === id)!
}

export type ModuleAggregate = {
  id: PathwayModuleId
  label: string
  gloss: string
  members: string[]
  /** Mean live activity across members (0–1). */
  meanActivity: number
  /** Mean Δ vs baseline — positive = activated program. */
  meanDelta: number
  /** −1 … +1 health for glow (green activated / red suppressed). */
  health: number
}

/**
 * Aggregate live node values into pathway bubbles for zoomed-out LOD.
 */
export function buildModuleAggregates(
  nodeIds: string[],
  nodeValues: Record<string, number>,
  baselineValues: Record<string, number>,
): ModuleAggregate[] {
  const buckets = new Map<PathwayModuleId, string[]>()
  for (const id of nodeIds) {
    const mid = moduleForGene(id)
    const list = buckets.get(mid) ?? []
    list.push(id)
    buckets.set(mid, list)
  }

  const out: ModuleAggregate[] = []
  for (const [mid, members] of buckets) {
    if (!members.length) continue
    // Skip tiny "other" noise unless it's the only stuff on canvas.
    if (mid === 'other' && buckets.size > 1 && members.length < 2) continue

    let sumY = 0
    let sumD = 0
    for (const id of members) {
      const y = nodeValues[id] ?? nodeValues[id.toUpperCase()] ?? 0.35
      const b = baselineValues[id] ?? baselineValues[id.toUpperCase()] ?? y
      sumY += y
      sumD += y - b
    }
    const n = members.length
    const meanActivity = sumY / n
    const meanDelta = sumD / n
    const health = Math.max(-1, Math.min(1, meanDelta * 4 + (meanActivity - 0.4) * 1.5))
    const def = moduleDef(mid)
    out.push({
      id: mid,
      label: def.label,
      gloss: def.gloss,
      members,
      meanActivity,
      meanDelta,
      health,
    })
  }

  return out.sort((a, b) => b.members.length - a.members.length || a.label.localeCompare(b.label))
}

/** Mix health (−1…+1) into a semantic glow color (IPA-style). */
export function healthGlowColor(health: number): string {
  if (health >= 0.12) return '#22C55E' // predicted activation
  if (health <= -0.12) return '#EF4444' // predicted inhibition / stress
  return '#64748B'
}
