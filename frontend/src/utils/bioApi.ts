/**
 * Dynamic gene → 3D structure resolution via UniProt PDB xrefs + AlphaFold fallback.
 */

export type PdbFetchResult = {
  symbol: string
  accession: string
  /** Experimental PDB id, or AlphaFold model id e.g. AF-P04637-F1 */
  structureId: string
  source: 'pdb' | 'alphafold'
  /** Raw PDB coordinate text for 3Dmol */
  pdbText: string
  /** Human-facing provenance URL */
  structureUrl: string
  resolutionAngstrom?: number | null
}

type UniProtXref = {
  database?: string
  id?: string
  properties?: Array<{ key?: string; value?: string }>
}

type UniProtSearchHit = {
  primaryAccession?: string
  uniProtKBCrossReferences?: UniProtXref[]
}

type UniProtSearchResponse = {
  results?: UniProtSearchHit[]
}

function parseResolution(xref: UniProtXref): number | null {
  const props = xref.properties ?? []
  const raw =
    props.find((p) => /resolution/i.test(p.key || ''))?.value ??
    props.find((p) => /Å|A/.test(p.value || ''))?.value
  if (!raw || raw.trim() === '-' || raw.trim() === '') return null
  const m = String(raw).match(/(\d+(?:\.\d+)?)/)
  return m ? Number(m[1]) : null
}

/** Rank experimental PDB xrefs — prefer lowest Å resolution, then id. */
function pickBestPdb(xrefs: UniProtXref[]): { id: string; resolution: number | null } | null {
  const pdbs = xrefs
    .filter((x) => (x.database || '').toUpperCase() === 'PDB' && x.id)
    .map((x) => ({
      id: String(x.id).toUpperCase(),
      resolution: parseResolution(x),
    }))
  if (!pdbs.length) return null
  pdbs.sort((a, b) => {
    const ra = a.resolution ?? 999
    const rb = b.resolution ?? 999
    if (ra !== rb) return ra - rb
    return a.id.localeCompare(b.id)
  })
  return pdbs[0]!
}

async function searchUniProt(
  symbol: string,
  reviewedOnly: boolean,
): Promise<UniProtSearchHit | null> {
  const q = reviewedOnly
    ? `gene_exact:${symbol} AND organism_id:9606 AND reviewed:true`
    : `gene_exact:${symbol} AND organism_id:9606`
  const searchUrl =
    `https://rest.uniprot.org/uniprotkb/search?query=` +
    encodeURIComponent(q) +
    `&fields=accession,xref_pdb&size=5&format=json`
  let searchRes: Response
  try {
    searchRes = await fetch(searchUrl, { headers: { Accept: 'application/json' } })
  } catch {
    return null
  }
  if (!searchRes.ok) return null
  const body = (await searchRes.json()) as UniProtSearchResponse
  return body.results?.[0] ?? null
}

async function fetchRcsbPdbText(pdbId: string): Promise<string> {
  const id = pdbId.trim().toUpperCase()
  const url = `https://files.rcsb.org/download/${encodeURIComponent(id)}.pdb`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`RCSB download failed for ${id} (${res.status})`)
  const text = await res.text()
  if (!text.includes('ATOM') && !text.includes('HETATM')) {
    throw new Error(`PDB file for ${id} has no ATOM records`)
  }
  return text
}

async function fetchAlphaFoldPdbText(accession: string): Promise<string> {
  const acc = accession.trim().toUpperCase()
  const url = `https://alphafold.ebi.ac.uk/files/AF-${encodeURIComponent(acc)}-F1-model_v4.pdb`
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`AlphaFold model missing for ${acc} (${res.status})`)
  }
  const text = await res.text()
  if (!text.includes('ATOM')) {
    throw new Error(`AlphaFold file for ${acc} has no ATOM records`)
  }
  return text
}

/**
 * Resolve any human gene symbol to experimental PDB (best resolution) or AlphaFold.
 *
 * 1. UniProt search: gene_exact:{symbol} AND organism_id:9606
 * 2. Prefer best-resolution PDB xref
 * 3. Else AlphaFold AF-{accession}-F1-model_v4.pdb
 */
export async function fetchPdbForGeneSymbol(symbol: string): Promise<PdbFetchResult> {
  const sym = symbol.trim().toUpperCase()
  if (!sym || !/^[A-Z0-9][A-Z0-9\-.]{0,14}$/i.test(sym)) {
    throw new Error(`No 3D structural model found for ${symbol || 'unknown'}`)
  }

  // Skip obvious non-protein environmental nodes.
  if (['O2', 'ROS', 'LPS', 'EGF', 'ATP', 'GTP'].includes(sym)) {
    throw new Error(`No 3D structural model found for ${sym}`)
  }

  // Prefer Swiss-Prot (reviewed) — gene_exact alone can return TrEMBL isoforms first (e.g. TP53 → K7PPA8).
  const hit =
    (await searchUniProt(sym, true)) ?? (await searchUniProt(sym, false))
  const accession = (hit?.primaryAccession || '').trim().toUpperCase()
  if (!accession) {
    throw new Error(`No 3D structural model found for ${sym}`)
  }

  const best = pickBestPdb(hit?.uniProtKBCrossReferences ?? [])
  if (best) {
    try {
      const pdbText = await fetchRcsbPdbText(best.id)
      return {
        symbol: sym,
        accession,
        structureId: best.id,
        source: 'pdb',
        pdbText,
        structureUrl: `https://www.rcsb.org/structure/${best.id}`,
        resolutionAngstrom: best.resolution,
      }
    } catch {
      // Fall through to AlphaFold if RCSB download fails.
    }
  }

  try {
    const pdbText = await fetchAlphaFoldPdbText(accession)
    return {
      symbol: sym,
      accession,
      structureId: `AF-${accession}-F1`,
      source: 'alphafold',
      pdbText,
      structureUrl: `https://alphafold.ebi.ac.uk/entry/${accession}`,
      resolutionAngstrom: null,
    }
  } catch {
    throw new Error(`No 3D structural model found for ${sym}`)
  }
}
