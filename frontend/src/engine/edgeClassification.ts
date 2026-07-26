/**
 * Client-side edge-kind classification for the STRING-DB-style topology canvas.
 *
 * The API only returns a signed `sign` plus a coarse `mechanism`
 * ("enzymatic" | "transcriptional") — there is no fine-grained
 * activation/inhibition/phosphorylation distinction on the wire. This derives
 * a display-only kind from data that is actually present, reusing the same
 * kinase gene-symbol set the canvas already uses for layout.
 */

export type EdgeKind = 'activation' | 'inhibition' | 'phosphorylation'

export type ClassifiableEdge = {
  source: string
  sign?: number
  is_inhibition?: boolean
  mechanism?: string
}

export function classifyEdgeKind(
  edge: ClassifiableEdge,
  kinaseSymbols: ReadonlySet<string>,
): EdgeKind {
  const sign = typeof edge.sign === 'number' ? edge.sign : edge.is_inhibition ? -1 : 1
  if (sign < 0) return 'inhibition'

  const mechanism = (edge.mechanism ?? '').toLowerCase()
  const isKinaseSource =
    kinaseSymbols.has(edge.source) || kinaseSymbols.has(edge.source.toUpperCase())
  if (mechanism === 'enzymatic' && isKinaseSource) return 'phosphorylation'

  return 'activation'
}
