/**
 * MaxQuant / FragPipe LC-MS/MS intensity table parser.
 *
 * Stoichiometric phospho-site occupancy:
 *   occupancy = Phospho_Intensity / (Phospho_Intensity + Unmodified_Intensity)
 *   y₀,i = Base_Expression * occupancy
 */

import {
  type PtmIngestResult,
  type PtmSite,
  parsePtmToken,
} from './ptmIngestion'

// Local enrichment of PTM sites with stoichiometric MS intensities.
export type MassSpecSite = PtmSite & {
  phosphoIntensity: number
  unmodifiedIntensity: number
  occupancy: number
  baseExpression: number
  y0: number
  diseaseHint?: 'tau_hyperphos' | 'kinase_activation' | 'oncogenic' | null
}

export type MassSpecParseResult = {
  sites: MassSpecSite[]
  bySymbol: Record<string, MassSpecSite[]>
  warnings: string[]
  format: 'maxquant' | 'fragpipe' | 'generic'
  sampleName?: string
}

function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = ''
  let inQ = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!
    if (ch === '"') {
      inQ = !inQ
      continue
    }
    if (ch === ',' && !inQ) {
      out.push(cur.trim())
      cur = ''
      continue
    }
    cur += ch
  }
  out.push(cur.trim())
  return out
}

function headerIndex(headers: string[], aliases: string[]): number {
  const norm = headers.map((h) => h.toLowerCase().replace(/[^a-z0-9]/g, ''))
  for (const a of aliases) {
    const key = a.toLowerCase().replace(/[^a-z0-9]/g, '')
    const i = norm.indexOf(key)
    if (i >= 0) return i
  }
  // partial contains
  for (const a of aliases) {
    const key = a.toLowerCase().replace(/[^a-z0-9]/g, '')
    const i = norm.findIndex((h) => h.includes(key) || key.includes(h))
    if (i >= 0) return i
  }
  return -1
}

function detectFormat(headers: string[]): MassSpecParseResult['format'] {
  const h = headers.join('|').toLowerCase()
  if (h.includes('protein.group') || h.includes('intensity') && h.includes('modification')) {
    return 'maxquant'
  }
  if (h.includes('peptideprophet') || h.includes('mappedgenes') || h.includes('spectrum')) {
    return 'fragpipe'
  }
  return 'generic'
}

function diseaseHint(symbol: string, occupancy: number): MassSpecSite['diseaseHint'] {
  const s = symbol.toUpperCase()
  if ((s === 'MAPT' || s === 'TAU') && occupancy > 0.55) return 'tau_hyperphos'
  if (['MTOR', 'EGFR', 'HIF1A', 'AKT1', 'MAPK1', 'SRC'].includes(s) && occupancy > 0.4) {
    return 'kinase_activation'
  }
  if (occupancy > 0.7) return 'oncogenic'
  return null
}

/**
 * Parse MaxQuant / FragPipe / generic LC-MS/MS CSV into stoichiometric PTM sites.
 */
export function parseMassSpecCsv(
  csvText: string,
  opts?: { sampleName?: string; baseExpressionBySymbol?: Record<string, number> },
): MassSpecParseResult {
  const warnings: string[] = []
  const lines = csvText
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))

  if (lines.length < 2) {
    return { sites: [], bySymbol: {}, warnings: ['Empty mass-spec table'], format: 'generic' }
  }

  const headers = splitCsvLine(lines[0]!)
  const format = detectFormat(headers)

  const iGene = headerIndex(headers, [
    'gene',
    'genes',
    'gene names',
    'genenames',
    'mappedgenes',
    'symbol',
    'protein',
  ])
  const iSite = headerIndex(headers, [
    'phosphosite',
    'modificationsites',
    'modifications',
    'site',
    'amino acid',
    'positions within proteins',
    'ptm',
  ])
  const iPhos = headerIndex(headers, [
    'intensity phospho',
    'intensity__ph',
    'phosphointensity',
    'intensity modified',
    'modintensity',
    'reporter intensity corrected 1',
  ])
  const iUnmod = headerIndex(headers, [
    'intensity',
    'unmodifiedintensity',
    'intensity unmodified',
    'baseintensity',
    'i_base',
  ])
  const iOcc = headerIndex(headers, ['occupancy', 'stoichiometry', 'phosphoratio', 'ratio'])

  if (iGene < 0 && iSite < 0) {
    return {
      sites: [],
      bySymbol: {},
      warnings: ['Need Gene / Protein or Site column (MaxQuant / FragPipe)'],
      format,
    }
  }

  const sites: MassSpecSite[] = []
  const seen = new Set<string>()
  const bases = opts?.baseExpressionBySymbol ?? {}

  for (let r = 1; r < lines.length; r++) {
    const cols = splitCsvLine(lines[r]!)
    const geneRaw = (iGene >= 0 ? cols[iGene] : '') || ''
    const siteRaw = (iSite >= 0 ? cols[iSite] : '') || ''
    // MaxQuant often has semicolon-separated gene lists
    const gene = geneRaw.split(/[;|/]/)[0]?.trim() || ''
    const token = siteRaw.includes('(') || siteRaw.includes('p') ? siteRaw : `${gene}_${siteRaw}`
    const parsed = parsePtmToken(token) || parsePtmToken(gene)
    if (!parsed || !parsed.symbol) {
      warnings.push(`Row ${r + 1}: could not parse site`)
      continue
    }

    let phos = iPhos >= 0 ? Number(cols[iPhos]) : NaN
    let unmod = iUnmod >= 0 ? Number(cols[iUnmod]) : NaN
    let occupancy = iOcc >= 0 ? Number(cols[iOcc]) : NaN

    if (!Number.isFinite(occupancy)) {
      if (!Number.isFinite(phos)) phos = 1
      if (!Number.isFinite(unmod) || unmod < 0) unmod = Math.max(phos * 0.4, 1)
      occupancy = phos / (phos + unmod + 1e-12)
    } else if (occupancy > 1.5) {
      // ratio-style occupancy → squash
      occupancy = occupancy / (1 + occupancy)
    }
    occupancy = Math.max(0.01, Math.min(0.99, occupancy))

    if (!Number.isFinite(phos)) phos = occupancy * 1000
    if (!Number.isFinite(unmod)) unmod = (1 - occupancy) * 1000

    const baseExpression = bases[parsed.symbol] ?? 0.55
    const y0 = Math.max(0.01, Math.min(0.99, baseExpression * occupancy))
    const id = `${parsed.symbol}:${parsed.residue}${parsed.position || 'x'}`
    if (seen.has(id)) continue
    seen.add(id)

    sites.push({
      id,
      symbol: parsed.symbol,
      residue: parsed.residue,
      position: parsed.position,
      phosphoRatio: occupancy / Math.max(0.2, 1 - occupancy), // keep PTM UI compatible
      log2FcSite: null,
      pValue: null,
      label: parsed.label,
      modality: 'phospho',
      phosphoIntensity: phos,
      unmodifiedIntensity: unmod,
      occupancy,
      baseExpression,
      y0,
      diseaseHint: diseaseHint(parsed.symbol, occupancy),
    })
  }

  const bySymbol: Record<string, MassSpecSite[]> = {}
  for (const s of sites) {
    if (!bySymbol[s.symbol]) bySymbol[s.symbol] = []
    bySymbol[s.symbol]!.push(s)
  }

  return {
    sites,
    bySymbol,
    warnings: warnings.slice(0, 8),
    format,
    sampleName: opts?.sampleName,
  }
}

/** Convert mass-spec sites into the shared PtmIngestResult shape. */
export function massSpecToPtmIngest(result: MassSpecParseResult): PtmIngestResult {
  return {
    sites: result.sites,
    bySymbol: result.bySymbol,
    warnings: result.warnings,
    sampleName: result.sampleName,
    condition: `LC-MS/MS (${result.format})`,
  }
}

export const EXAMPLE_MAXQUANT_CSV = `Gene names,Amino acid,Positions within proteins,Intensity,Intensity Phospho,Occupancy
HIF1A,S,643,1200,2800,0.70
MTOR,S,2448,900,2100,0.70
EGFR,Y,1068,1500,600,0.29
MAPT,S,396,800,3200,0.80
AKT1,S,473,1100,2400,0.69
MAPK1,T,202,1000,1500,0.60
`
