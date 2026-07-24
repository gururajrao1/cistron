/**
 * Phospho-proteomics / PTM mass-spec ingestion.
 *
 * Maps site-level phospho ratios onto Hill-cube baselines:
 *   y₀,i = Boltzmann_Map(log2FC_transcript) × Phospho_Ratio_Site
 *
 * Supported site tokens: p-HIF1A(Ser643), HIF1A_pS643, MTOR(S2448), …
 */

import { mapLog2FcToY0, OMICS_Y0_MAX, OMICS_Y0_MIN } from '../api/types'

export type AaCode = 'S' | 'T' | 'Y' | 'K' | 'R' | string

export type PtmSite = {
  id: string
  symbol: string
  residue: AaCode
  position: number
  /** Observed phospho / modified peptide ratio (typically 0–~5) */
  phosphoRatio: number
  log2FcSite?: number | null
  pValue?: number | null
  /** Display label e.g. p-HIF1A(Ser643) */
  label: string
  modality: 'phospho' | 'acetyl' | 'ubiquitin' | 'other'
}

export type PtmIngestResult = {
  sites: PtmSite[]
  bySymbol: Record<string, PtmSite[]>
  warnings: string[]
  sampleName?: string
  condition?: string
}

export type CombinedBaseline = {
  symbol: string
  log2FcTranscript: number
  boltzmannY0: number
  /** Selected / aggregated phospho ratio (1 = unchanged) */
  phosphoRatio: number
  /** y₀,i = boltzmann × phospho (clamped) */
  y0: number
  sites: PtmSite[]
  activeSiteId: string | null
}

const AA3: Record<string, AaCode> = {
  SER: 'S',
  THR: 'T',
  TYR: 'Y',
  LYS: 'K',
  ARG: 'R',
  S: 'S',
  T: 'T',
  Y: 'Y',
  K: 'K',
  R: 'R',
}

/** Softmax-style Boltzmann map of transcript log2FC → occupancy in (0,1). */
export function boltzmannMapLog2Fc(
  log2Fc: number,
  opts?: { beta?: number; baseline?: number },
): number {
  const beta = opts?.beta ?? 1.0
  const baseline = opts?.baseline ?? 0.5
  // Energy proxy E = −log2FC; P ∝ e^{−βE} with baseline offset → logistic
  const p = baseline + (1 - baseline) * (1 / (1 + Math.exp(-beta * log2Fc)) - 0.5) * 2
  // Align with existing omics sigmoid when beta≈1, baseline≈0.5 ≈ mapLog2FcToY0
  if (Math.abs(beta - 1) < 1e-9 && Math.abs(baseline - 0.5) < 1e-9) {
    return mapLog2FcToY0(log2Fc)
  }
  return Math.max(OMICS_Y0_MIN, Math.min(OMICS_Y0_MAX, p))
}

/**
 * Combine transcript Boltzmann occupancy with site phospho ratio.
 * Phospho_Ratio_Site is treated as a relative activity multiplier (1 = basal).
 */
export function combineTranscriptAndPhospho(
  log2FcTranscript: number,
  phosphoRatio: number,
  opts?: { beta?: number },
): number {
  const boltz = boltzmannMapLog2Fc(log2FcTranscript, { beta: opts?.beta ?? 1 })
  const ratio = Number.isFinite(phosphoRatio) ? Math.max(0, phosphoRatio) : 1
  return Math.max(OMICS_Y0_MIN, Math.min(OMICS_Y0_MAX, boltz * ratio))
}

/** Parse free-text PTM tokens into symbol + residue + position. */
export function parsePtmToken(raw: string): {
  symbol: string
  residue: AaCode
  position: number
  label: string
  modality: PtmSite['modality']
} | null {
  const s = String(raw ?? '').trim()
  if (!s) return null

  // p-HIF1A(Ser643) | p-MTOR(Ser2448)
  let m = /^p[_-]?([A-Za-z0-9]+)[\s(]+(?:Ser|Thr|Tyr|Lys|Arg|S|T|Y|K|R)[a-z]*\s*(\d+)\)?$/i.exec(s)
  if (m) {
    const aaMatch = /\((Ser|Thr|Tyr|Lys|Arg|S|T|Y|K|R)/i.exec(s)
    const aaRaw = (aaMatch?.[1] ?? 'S').toUpperCase()
    const residue = AA3[aaRaw] ?? (aaRaw[0] as AaCode)
    return {
      symbol: m[1]!.toUpperCase(),
      residue,
      position: Number(m[2]),
      label: `p-${m[1]!.toUpperCase()}(${residue === 'S' ? 'Ser' : residue === 'T' ? 'Thr' : residue === 'Y' ? 'Tyr' : residue}${m[2]})`,
      modality: 'phospho',
    }
  }

  // HIF1A_pS643 / MTOR-pS2448 / HIF1A(S643)
  m =
    /^([A-Za-z0-9]+)(?:_|-)?(?:p)?[\(]?([STYKR])[\)]?(\d+)\)?$/i.exec(s) ||
    /^([A-Za-z0-9]+)\((Ser|Thr|Tyr|Lys|Arg)(\d+)\)$/i.exec(s)
  if (m) {
    const aaRaw = m[2]!.toUpperCase()
    const residue = AA3[aaRaw] ?? (aaRaw[0] as AaCode)
    const pos = Number(m[3])
    return {
      symbol: m[1]!.toUpperCase(),
      residue,
      position: pos,
      label: `p-${m[1]!.toUpperCase()}(${residue === 'S' ? 'Ser' : residue === 'T' ? 'Thr' : residue === 'Y' ? 'Tyr' : residue}${pos})`,
      modality: 'phospho',
    }
  }

  // Gene-only fallback (no site)
  if (/^[A-Za-z][A-Za-z0-9]{1,14}$/.test(s)) {
    return {
      symbol: s.toUpperCase(),
      residue: 'S',
      position: 0,
      label: s.toUpperCase(),
      modality: 'phospho',
    }
  }
  return null
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
    const i = norm.indexOf(a.replace(/[^a-z0-9]/g, ''))
    if (i >= 0) return i
  }
  return -1
}

/**
 * Ingest a mass-spec PTM / phospho quantification table (CSV).
 * Expected columns (flexible headers): site/ptm/gene, ratio/intensity, log2fc, padj.
 */
export function ingestPtmCsv(
  csvText: string,
  opts?: { sampleName?: string; condition?: string },
): PtmIngestResult {
  const warnings: string[] = []
  const lines = csvText
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))

  if (lines.length < 2) {
    return { sites: [], bySymbol: {}, warnings: ['Empty PTM table'], ...opts }
  }

  const headers = splitCsvLine(lines[0]!)
  const iSite = headerIndex(headers, [
    'site',
    'ptm',
    'phosphosite',
    'modification',
    'feature',
    'peptide',
  ])
  const iGene = headerIndex(headers, ['gene', 'symbol', 'protein', 'genename'])
  const iRes = headerIndex(headers, ['residue', 'aa', 'aminoacid'])
  const iPos = headerIndex(headers, ['position', 'pos', 'sitepos', 'residueposition'])
  const iRatio = headerIndex(headers, [
    'phosphoratio',
    'ratio',
    'intensity',
    'abundance',
    'occupancy',
    'localizedprobability',
  ])
  const iLfc = headerIndex(headers, ['log2fc', 'log2foldchange', 'lfc', 'foldchange'])
  const iP = headerIndex(headers, ['pvalue', 'padj', 'fdr', 'qvalue'])

  if (iSite < 0 && iGene < 0) {
    return {
      sites: [],
      bySymbol: {},
      warnings: ['Need a Site/PTM or Gene column'],
      ...opts,
    }
  }

  const sites: PtmSite[] = []
  const seen = new Set<string>()

  for (let r = 1; r < lines.length; r++) {
    const cols = splitCsvLine(lines[r]!)
    const siteRaw = iSite >= 0 ? cols[iSite] ?? '' : ''
    const geneRaw = iGene >= 0 ? cols[iGene] ?? '' : ''
    const token = siteRaw || geneRaw
    let parsed = parsePtmToken(token)

    if (!parsed && geneRaw) {
      const resCol = iRes >= 0 ? cols[iRes] ?? 'S' : 'S'
      const posCol = iPos >= 0 ? Number(cols[iPos]) : 0
      const aa = AA3[resCol.toUpperCase()] ?? (resCol[0]?.toUpperCase() as AaCode) ?? 'S'
      parsed = {
        symbol: geneRaw.toUpperCase(),
        residue: aa,
        position: Number.isFinite(posCol) ? posCol : 0,
        label:
          posCol > 0
            ? `p-${geneRaw.toUpperCase()}(${aa === 'S' ? 'Ser' : aa}${posCol})`
            : geneRaw.toUpperCase(),
        modality: 'phospho',
      }
    }

    if (!parsed) {
      warnings.push(`Row ${r + 1}: could not parse “${token}”`)
      continue
    }

    // Override residue/pos from dedicated columns when present
    if (iRes >= 0 && cols[iRes]) {
      const aa = AA3[cols[iRes]!.toUpperCase()]
      if (aa) parsed.residue = aa
    }
    if (iPos >= 0 && cols[iPos] && Number(cols[iPos]) > 0) {
      parsed.position = Number(cols[iPos])
      parsed.label = `p-${parsed.symbol}(${parsed.residue === 'S' ? 'Ser' : parsed.residue === 'T' ? 'Thr' : parsed.residue === 'Y' ? 'Tyr' : parsed.residue}${parsed.position})`
    }

    let ratio = iRatio >= 0 ? Number(cols[iRatio]) : NaN
    if (!Number.isFinite(ratio)) {
      // If only site log2FC given, map to a soft ratio around 1
      const lfcSite = iLfc >= 0 ? Number(cols[iLfc]) : NaN
      ratio = Number.isFinite(lfcSite) ? Math.pow(2, lfcSite / 2) : 1
    }
    // Normalize extreme MS ratios into a usable multiplier band
    ratio = Math.max(0.05, Math.min(5, ratio))

    const log2FcSite = iLfc >= 0 && cols[iLfc] !== '' ? Number(cols[iLfc]) : null
    const pValue = iP >= 0 && cols[iP] !== '' ? Number(cols[iP]) : null
    const id = `${parsed.symbol}:${parsed.residue}${parsed.position || 'x'}`
    if (seen.has(id)) continue
    seen.add(id)

    sites.push({
      id,
      symbol: parsed.symbol,
      residue: parsed.residue,
      position: parsed.position,
      phosphoRatio: ratio,
      log2FcSite: log2FcSite != null && Number.isFinite(log2FcSite) ? log2FcSite : null,
      pValue: pValue != null && Number.isFinite(pValue) ? pValue : null,
      label: parsed.label,
      modality: parsed.modality,
    })
  }

  const bySymbol: Record<string, PtmSite[]> = {}
  for (const s of sites) {
    if (!bySymbol[s.symbol]) bySymbol[s.symbol] = []
    bySymbol[s.symbol]!.push(s)
  }
  for (const list of Object.values(bySymbol)) {
    list.sort((a, b) => b.phosphoRatio - a.phosphoRatio)
  }

  return {
    sites,
    bySymbol,
    warnings,
    sampleName: opts?.sampleName,
    condition: opts?.condition,
  }
}

/** Build per-gene y₀ from transcript features × selected PTM sites. */
export function buildPtmBaselines(
  transcriptLog2Fc: Record<string, number>,
  ptmBySymbol: Record<string, PtmSite[]>,
  activeSiteBySymbol?: Record<string, string | null>,
): CombinedBaseline[] {
  const symbols = new Set([
    ...Object.keys(transcriptLog2Fc).map((s) => s.toUpperCase()),
    ...Object.keys(ptmBySymbol),
  ])
  const out: CombinedBaseline[] = []
  for (const symbol of symbols) {
    const sites = ptmBySymbol[symbol] ?? []
    const activeId = activeSiteBySymbol?.[symbol] ?? sites[0]?.id ?? null
    const active = sites.find((s) => s.id === activeId) ?? sites[0] ?? null
    const lfc = transcriptLog2Fc[symbol] ?? transcriptLog2Fc[symbol.toLowerCase()] ?? 0
    const ratio = active?.phosphoRatio ?? 1
    const boltzmannY0 = boltzmannMapLog2Fc(lfc)
    const y0 = combineTranscriptAndPhospho(lfc, ratio)
    out.push({
      symbol,
      log2FcTranscript: lfc,
      boltzmannY0,
      phosphoRatio: ratio,
      y0,
      sites,
      activeSiteId: active?.id ?? null,
    })
  }
  return out.sort((a, b) => b.y0 - a.y0)
}

/** Convert PTM baselines into perturbation clamps for LabContext. */
export function baselinesToClamps(rows: CombinedBaseline[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const r of rows) {
    if (r.sites.length === 0 && Math.abs(r.log2FcTranscript) < 1e-9) continue
    out[r.symbol] = r.y0
  }
  return out
}

export const EXAMPLE_PHOSPHO_CSV = `Site,Gene,Residue,Position,PhosphoRatio,Log2FC,padj
p-HIF1A(Ser643),HIF1A,S,643,2.40,1.10,0.001
p-MTOR(Ser2448),MTOR,S,2448,1.85,0.70,0.012
p-AKT1(Ser473),AKT1,S,473,2.10,0.55,0.008
p-MAPK1(Thr202),MAPK1,T,202,1.60,0.40,0.04
p-EGFR(Tyr1068),EGFR,Y,1068,0.45,-0.80,0.02
VEGFA_pS126,VEGFA,S,126,1.25,0.30,0.09
`
