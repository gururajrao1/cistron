/**
 * Live Reactome + STRING-DB pathway / interactome resolution for dynamic scenarios.
 *
 * Browser calls go through the Vite proxies (`/reactome`, `/string-db`) to avoid CORS.
 */

export type ReactomePathwayHit = {
  pathwayId: string
  name: string
  species: string
  summation?: string
  isDisease?: boolean
  /** How this pathway relates to the typed query */
  matchKind?: 'name' | 'alias' | 'text' | 'weak'
  /** Short human reason, e.g. "Mentions Creutzfeldt-Jakob / prion disease" */
  matchHint?: string
  /** Higher = better name/text relevance to the query */
  relevance?: number
}

export type CytoscapeNode = {
  id: string
  symbol: string
  y0: number
}

export type CytoscapeEdge = {
  source: string
  target: string
  weight: number
  type: 'activation' | 'inhibition'
}

export type DynamicInteractome = {
  query: string
  pathwayId: string
  pathwayName: string
  /** e.g. cistron-alzheimer-disease */
  provenance: string
  geneSymbols: string[]
  nodes: CytoscapeNode[]
  edges: CytoscapeEdge[]
}

const MAX_GENES = 36
const MAX_EDGES = 80
const MIN_STRING_SCORE = 0.4

function isLocalViteDev(): boolean {
  return typeof window !== 'undefined' && /:(5173|4173)$/.test(window.location.host)
}

function reactomeBase(): string {
  // Local Vite uses vite.config.ts proxy; production uses FastAPI /proxy/reactome.
  if (isLocalViteDev()) return '/reactome/ContentService'
  return '/proxy/reactome/ContentService'
}

function stringBase(): string {
  if (isLocalViteDev()) return '/string-db/api'
  return '/proxy/string-db/api'
}

/** Lowercase kebab slug for provenance keys — keep short for UI badges. */
export function slugifyDiseaseName(raw: string, maxLen = 40): string {
  let s = raw
    .trim()
    .toLowerCase()
    .replace(/['']/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  if (!s) return 'disease'
  if (s.length > maxLen) {
    s = s.slice(0, maxLen).replace(/-+$/g, '')
    // Prefer cutting on a hyphen boundary
    const cut = s.lastIndexOf('-')
    if (cut >= 16) s = s.slice(0, cut)
  }
  return s || 'disease'
}

export function diseaseProvenance(label: string): string {
  return `cistron-${slugifyDiseaseName(label)}`
}

type ReactomeSearchEntry = {
  stId?: string
  id?: string
  name?: string
  species?: string | string[]
  summation?: string
  type?: string
  exactType?: string
  isDisease?: boolean
  disease?: boolean
}

type ReactomeSearchResponse = {
  results?: Array<{ entries?: ReactomeSearchEntry[]; typeName?: string }>
}

function stripHtml(raw: string): string {
  return raw
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Common disease shorthand → Reactome-friendlier search terms. */
const QUERY_EXPANDERS: Record<string, string[]> = {
  prion: ['prion', 'Creutzfeldt-Jakob', 'PRNP', 'prion disease'],
  cjd: ['Creutzfeldt-Jakob', 'prion', 'PRNP'],
  alzheimer: ['Alzheimer', 'Alzheimer disease', 'APP'],
  alzheimers: ['Alzheimer', 'Alzheimer disease'],
  parkinson: ['Parkinson', 'Parkinson disease', 'SNCA'],
  parkinsons: ['Parkinson', 'Parkinson disease'],
  glioblastoma: ['Glioblastoma', 'EGFR'],
  diabetes: ['Type II diabetes', 'diabetes mellitus'],
  'colorectal cancer': [
    'colorectal',
    'colorectal carcinoma',
    'CRCS1',
    'MLH1',
    'APC truncation',
  ],
  colorectal: ['colorectal', 'colorectal carcinoma', 'CRCS1', 'MLH1'],
  'breast cancer': ['Breast cancer', 'BRCA1'],
}

/** Words too common to count as a strong name match alone. */
const GENERIC_TOKENS = new Set([
  'cancer',
  'cancers',
  'disease',
  'diseases',
  'signaling',
  'signalling',
  'pathway',
  'pathways',
  'defective',
  'mutants',
  'mutant',
  'associated',
  'with',
  'in',
  'of',
  'by',
  'and',
  'the',
  'for',
])

function expandSearchTerms(query: string): string[] {
  const q = query.trim()
  const key = q.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  const extras = QUERY_EXPANDERS[key] ?? QUERY_EXPANDERS[key.replace(/s$/, '')] ?? []
  const terms = [q, ...extras]
  // Prefer the distinctive first token alone (e.g. "colorectal" from "Colorectal Cancer").
  const parts = key.split(/\s+/).filter(Boolean)
  for (const p of parts) {
    if (!GENERIC_TOKENS.has(p) && p.length >= 4) terms.push(p)
  }
  if (!/\bdisease\b/i.test(q) && q.split(/\s+/).length <= 2) {
    terms.push(`${q} disease`)
  }
  return Array.from(new Set(terms.map((t) => t.trim()).filter((t) => t.length >= 2)))
}

function tokenize(q: string): string[] {
  return q
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length >= 2 && !['the', 'and', 'of', 'in', 'by', 'for'].includes(t))
}

function scorePathwayHit(query: string, name: string, summation: string): {
  relevance: number
  matchKind: ReactomePathwayHit['matchKind']
  matchHint: string
} {
  const q = query.trim().toLowerCase()
  const tokens = tokenize(query)
  const specific = tokens.filter((t) => !GENERIC_TOKENS.has(t))
  const nameL = name.toLowerCase()
  const sumL = summation.toLowerCase()

  // Explicit negative: Reactome says this disease is NOT annotated here.
  const negative =
    tokens.some((t) => {
      const re = new RegExp(
        `${t}[^.]{0,40}(have not been annotated|not been annotated|not annotated)`,
        'i',
      )
      return re.test(summation) || new RegExp(`not annotated[^.]{0,40}${t}`, 'i').test(summation)
    }) || /prion diseases have not been annotated/i.test(summation)

  if (negative) {
    return {
      relevance: -100,
      matchKind: 'weak',
      matchHint: 'Reactome notes this disease is not annotated in this pathway',
    }
  }

  if (nameL === q || nameL === `${q} disease` || nameL === `${q}s`) {
    return { relevance: 100, matchKind: 'name', matchHint: 'Exact pathway name match' }
  }

  // Prefer pathways that carry the distinctive disease token (colorectal, alzheimer…),
  // not just a generic word like "cancer".
  if (specific.length && specific.every((t) => nameL.includes(t))) {
    return {
      relevance: 92,
      matchKind: 'name',
      matchHint: `Name matches disease term “${specific.join(' ')}”`,
    }
  }
  if (specific.some((t) => nameL.includes(t))) {
    const hit = specific.find((t) => nameL.includes(t))!
    return {
      relevance: 88,
      matchKind: 'name',
      matchHint: `Name mentions “${hit}” (disease-specific)`,
    }
  }
  if (specific.some((t) => sumL.includes(t))) {
    const hit = specific.find((t) => sumL.includes(t))!
    const idx = sumL.indexOf(hit)
    const start = Math.max(0, idx - 36)
    const end = Math.min(summation.length, idx + hit.length + 72)
    let snippet = stripHtml(summation.slice(start, end))
    if (start > 0) snippet = `…${snippet}`
    if (end < summation.length) snippet = `${snippet}…`
    return {
      relevance: 75,
      matchKind: 'text',
      matchHint: `Mentions “${hit}”: ${snippet}`,
    }
  }

  if (tokens.length && tokens.every((t) => nameL.includes(t))) {
    return {
      relevance: 60,
      matchKind: 'name',
      matchHint: 'Pathway name contains your search terms',
    }
  }

  // Generic-only name hits (e.g. only "cancer") are weak.
  const genericHit = tokens.find((t) => GENERIC_TOKENS.has(t) && nameL.includes(t))
  if (genericHit && !specific.some((t) => nameL.includes(t) || sumL.includes(t))) {
    return {
      relevance: 25,
      matchKind: 'weak',
      matchHint: `Only generic word “${genericHit}” in the name — not disease-specific`,
    }
  }

  if (tokens.some((t) => nameL.includes(t))) {
    return {
      relevance: 45,
      matchKind: 'name',
      matchHint: `Name mentions “${tokens.find((t) => nameL.includes(t))}”`,
    }
  }

  // Pull a snippet around the first query token in summation.
  let snippet = ''
  for (const t of tokens) {
    const idx = sumL.indexOf(t)
    if (idx < 0) continue
    const start = Math.max(0, idx - 40)
    const end = Math.min(summation.length, idx + t.length + 80)
    snippet = stripHtml(summation.slice(start, end))
    if (start > 0) snippet = `…${snippet}`
    if (end < summation.length) snippet = `${snippet}…`
    break
  }

  if (snippet) {
    const hitCount = tokens.filter((t) => sumL.includes(t)).length
    return {
      relevance: 35 + hitCount * 5,
      matchKind: 'text',
      matchHint: `Text match: ${snippet}`,
    }
  }

  return {
    relevance: 5,
    matchKind: 'weak',
    matchHint: 'Weak / indirect Reactome hit',
  }
}

async function fetchReactomePathwayEntries(
  query: string,
  signal?: AbortSignal,
): Promise<ReactomeSearchEntry[]> {
  const url =
    `${reactomeBase()}/search/query?query=${encodeURIComponent(query)}` +
    `&species=${encodeURIComponent('Homo sapiens')}&types=Pathway&cluster=true`
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!res.ok) {
    if (res.status === 404) return []
    throw new Error(`Reactome search failed (${res.status})`)
  }
  const body = (await res.json()) as ReactomeSearchResponse
  const entries: ReactomeSearchEntry[] = []
  for (const group of body.results ?? []) {
    for (const entry of group.entries ?? []) entries.push(entry)
  }
  return entries
}

/**
 * Query Reactome ContentService for human pathways matching a disease / condition.
 * Expands short aliases (e.g. "prion" → Creutzfeldt-Jakob) and ranks by name/text relevance.
 */
export async function searchDiseasePathways(
  query: string,
  opts?: { limit?: number; signal?: AbortSignal },
): Promise<ReactomePathwayHit[]> {
  const q = query.trim()
  if (q.length < 2) return []

  const terms = expandSearchTerms(q).slice(0, 4)
  const entryBags = await Promise.all(
    terms.map((term) => fetchReactomePathwayEntries(term, opts?.signal)),
  )

  const limit = opts?.limit ?? 10
  const byId = new Map<string, ReactomePathwayHit>()

  for (let ti = 0; ti < terms.length; ti++) {
    const term = terms[ti]!
    for (const entry of entryBags[ti] ?? []) {
      const pathwayId = String(entry.stId || entry.id || '').trim()
      if (!pathwayId.startsWith('R-HSA-')) continue
      const speciesRaw = entry.species
      const species = Array.isArray(speciesRaw)
        ? String(speciesRaw[0] ?? 'Homo sapiens')
        : String(speciesRaw || 'Homo sapiens')
      if (!/homo sapiens/i.test(species)) continue

      const name = stripHtml(String(entry.name || pathwayId))
      const summation = entry.summation ? stripHtml(String(entry.summation)) : ''
      const scored = scorePathwayHit(q, name, summation)
      // Alias searches (Creutzfeldt-Jakob for "prion") get a small boost when text matches.
      const aliasBoost = ti > 0 && scored.matchKind !== 'weak' ? 6 : 0
      const relevance = scored.relevance + aliasBoost

      const prev = byId.get(pathwayId)
      if (prev && (prev.relevance ?? 0) >= relevance) continue

      byId.set(pathwayId, {
        pathwayId,
        name,
        species,
        summation: summation || undefined,
        isDisease: Boolean(entry.isDisease ?? entry.disease),
        matchKind: ti > 0 && scored.matchKind === 'text' ? 'alias' : scored.matchKind,
        matchHint:
          ti > 0 && scored.matchKind !== 'name'
            ? `${scored.matchHint} (via “${term}”)`
            : scored.matchHint,
        relevance,
      })
    }
  }

  return Array.from(byId.values())
    .filter((h) => (h.relevance ?? 0) > -50) // drop explicit "not annotated" junk
    .sort((a, b) => (b.relevance ?? 0) - (a.relevance ?? 0) || a.name.localeCompare(b.name))
    .slice(0, limit)
}

type ReactomeParticipant = {
  displayName?: string
  schemaClass?: string
  refEntities?: Array<{
    schemaClass?: string
    displayName?: string
    identifier?: string
  }>
}

function geneFromUniProtDisplay(display: string): string | null {
  // "UniProt:P07384 CAPN1" → CAPN1
  const m = display.match(/UniProt:[^\s]+\s+([A-Z0-9][A-Z0-9\-.]{0,14})/i)
  if (m) return m[1]!.toUpperCase()
  const tok = display.trim().split(/\s+/)[0]?.split('[')[0]
  if (tok && /^[A-Z][A-Z0-9\-.]{1,14}$/i.test(tok) && !/^CHEBI/i.test(tok)) {
    return tok.toUpperCase()
  }
  return null
}

/**
 * Pathway participants → human gene symbols.
 * Prefers `participatingMolecules` (per product spec); falls back to `participants`.
 */
export async function fetchPathwayGeneSymbols(
  pathwayId: string,
  opts?: { signal?: AbortSignal },
): Promise<string[]> {
  const id = encodeURIComponent(pathwayId.trim())
  const bases = [
    `${reactomeBase()}/data/pathway/${id}/participatingMolecules`,
    `${reactomeBase()}/data/participants/${id}`,
  ]

  let payload: unknown = null
  let lastStatus = 0
  for (const url of bases) {
    const res = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: opts?.signal,
    })
    lastStatus = res.status
    if (res.ok) {
      payload = await res.json()
      break
    }
  }
  if (payload == null) {
    throw new Error(`Reactome participants failed for ${pathwayId} (${lastStatus})`)
  }

  const genes: string[] = []
  const seen = new Set<string>()
  const push = (g: string | null) => {
    if (!g || seen.has(g) || g.length > 16) return
    // Skip tiny metabolites / ions mis-parsed as genes
    if (['CA2', 'CA2+', 'H2O', 'ATP', 'GTP', 'NAD', 'NADH'].includes(g)) return
    // Cytoscape-safe id: letters, digits, underscore, hyphen only
    if (!/^[A-Z][A-Z0-9_-]{0,14}$/.test(g)) return
    seen.add(g)
    genes.push(g)
  }

  const items = Array.isArray(payload) ? payload : []
  for (const item of items as ReactomeParticipant[]) {
    const refs = item.refEntities ?? []
    if (refs.length) {
      for (const ref of refs) {
        if ((ref.schemaClass || '').includes('GeneProduct') || (ref.schemaClass || '').includes('Protein')) {
          push(geneFromUniProtDisplay(String(ref.displayName || '')))
        }
      }
    } else if (item.displayName) {
      push(geneFromUniProtDisplay(String(item.displayName)))
    }
  }
  return genes
}

function parseTsv(text: string): Record<string, string>[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length < 2) return []
  const headers = lines[0]!.split('\t')
  const rows: Record<string, string>[] = []
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i]!.split('\t')
    const row: Record<string, string> = {}
    headers.forEach((h, j) => {
      row[h] = cols[j] ?? ''
    })
    rows.push(row)
  }
  return rows
}

/**
 * STRING-DB network for a gene set → Cistron Cytoscape topology.
 */
export async function fetchInteractionNetwork(
  geneSymbols: string[],
  opts?: { signal?: AbortSignal },
): Promise<{ nodes: CytoscapeNode[]; edges: CytoscapeEdge[] }> {
  const genes = Array.from(
    new Set(
      geneSymbols
        .map((g) => g.trim().toUpperCase())
        .filter((g) => /^[A-Z][A-Z0-9\-.]{0,14}$/.test(g)),
    ),
  ).slice(0, MAX_GENES)

  if (genes.length < 2) {
    return {
      nodes: genes.map((g) => ({ id: g, symbol: g, y0: 0.5 })),
      edges: [],
    }
  }

  const identifiers = genes.join('%0d')
  const url =
    `${stringBase()}/tsv/network?identifiers=${identifiers}&species=9606` +
    `&required_score=400&caller_identity=cistron`

  const res = await fetch(url, { signal: opts?.signal })
  if (!res.ok) {
    throw new Error(`STRING network failed (${res.status})`)
  }
  const text = await res.text()
  const rows = parseTsv(text)

  const edgeMap = new Map<string, CytoscapeEdge>()
  const nodeSet = new Set<string>()

  for (const row of rows) {
    const a = String(row.preferredName_A || row.preferredName_a || '').trim().toUpperCase()
    const b = String(row.preferredName_B || row.preferredName_b || '').trim().toUpperCase()
    if (!a || !b || a === b) continue
    let score = Number(row.score ?? row.combined_score ?? 0)
    if (!Number.isFinite(score)) continue
    // STRING TSV scores are typically 0–1000
    if (score > 1) score = score / 1000
    if (score < MIN_STRING_SCORE) continue

    nodeSet.add(a)
    nodeSet.add(b)
    const key = a < b ? `${a}|${b}` : `${b}|${a}`
    const prev = edgeMap.get(key)
    if (prev && prev.weight >= score) continue
    // Undirected PPI → directed activation for Hill-cube (unsigned evidence).
    edgeMap.set(key, {
      source: a,
      target: b,
      weight: score,
      type: 'activation',
    })
  }

  // Prefer STRING-covered nodes; fill remaining Reactome genes as isolates.
  for (const g of genes) nodeSet.add(g)

  let edges = Array.from(edgeMap.values()).sort((x, y) => y.weight - x.weight)
  if (edges.length > MAX_EDGES) edges = edges.slice(0, MAX_EDGES)

  // Keep highest-degree nodes if still too large.
  const degree = new Map<string, number>()
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }
  let keep = Array.from(nodeSet)
  if (keep.length > MAX_GENES) {
    keep = keep
      .sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0))
      .slice(0, MAX_GENES)
  }
  const keepSet = new Set(keep)
  edges = edges.filter((e) => keepSet.has(e.source) && keepSet.has(e.target))

  const nodes: CytoscapeNode[] = keep.map((g) => ({
    id: g,
    symbol: g,
    y0: 0.5,
  }))

  return { nodes, edges }
}

/**
 * Full pipeline: Reactome pathway → genes → STRING edges → interactome payload.
 */
export async function buildDynamicInteractome(
  pathway: ReactomePathwayHit,
  opts?: { query?: string; signal?: AbortSignal },
): Promise<DynamicInteractome> {
  const geneSymbols = await fetchPathwayGeneSymbols(pathway.pathwayId, {
    signal: opts?.signal,
  })
  if (!geneSymbols.length) {
    throw new Error(`No gene symbols found for pathway ${pathway.pathwayId}`)
  }

  const { nodes, edges } = await fetchInteractionNetwork(geneSymbols, {
    signal: opts?.signal,
  })
  if (nodes.length < 2) {
    throw new Error(`Interactome too small for ${pathway.name}`)
  }

  const label = opts?.query?.trim() || pathway.name
  // Prefer the user's short disease query for provenance — never the full Reactome title.
  const provenanceSeed =
    (opts?.query?.trim() && opts.query.trim().length <= 80
      ? opts.query.trim()
      : null) ||
    pathway.name.split(/[:–—|]/)[0]!.trim().slice(0, 60) ||
    pathway.pathwayId
  return {
    query: label,
    pathwayId: pathway.pathwayId,
    pathwayName: pathway.name,
    provenance: diseaseProvenance(provenanceSeed),
    geneSymbols,
    nodes,
    edges,
  }
}

/**
 * Search Reactome for the top pathway matching a free-text disease query, then build interactome.
 */
export async function resolveDiseaseInteractome(
  query: string,
  opts?: { signal?: AbortSignal },
): Promise<DynamicInteractome> {
  const hits = await searchDiseasePathways(query, { limit: 5, signal: opts?.signal })
  if (!hits.length) {
    throw new Error(`No Reactome pathway found for “${query}”`)
  }
  // Prefer disease-flagged + highest-relevance pathway when resolving free text.
  const best =
    [...hits].sort((a, b) => (b.relevance ?? 0) - (a.relevance ?? 0))[0] ??
    hits.find((h) => h.isDisease) ??
    hits[0]!
  return buildDynamicInteractome(best, { query, signal: opts?.signal })
}
