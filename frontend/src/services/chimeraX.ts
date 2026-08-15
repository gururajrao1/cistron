/**
 * ChimeraX bridge — publication-grade 3D outside the browser preview (3Dmol).
 *
 * ChimeraX is desktop software (UCSF). We cannot embed it in the SPA, so Cistron:
 * 1. Downloads a `.cxc` command script (always works)
 * 2. Optionally drives a local ChimeraX REST remotecontrol session
 *    (`remotecontrol rest start port 60985 cors true`)
 *
 * Hosted origins cannot CORS-fetch localhost; REST open uses a top-level
 * navigation to http://127.0.0.1:<port>/run?command=… which ChimeraX accepts.
 */

import type { PdbFetchResult } from '../utils/bioApi'

export const CHIMERAX_PORT_KEY = 'cistron.chimeraX.port'
export const CHIMERAX_DEFAULT_PORT = 60985

export type ChimeraXOpenTarget = {
  symbol: string
  structure: Pick<PdbFetchResult, 'structureId' | 'source' | 'accession' | 'structureUrl'>
  /** Optional PTM / focus residue (1-based UniProt / PDB numbering). */
  residue?: number | null
  residueLabel?: string | null
}

export function loadChimeraXPort(): number {
  try {
    const raw = localStorage.getItem(CHIMERAX_PORT_KEY)
    const n = raw ? Number(raw) : CHIMERAX_DEFAULT_PORT
    if (Number.isFinite(n) && n >= 1024 && n <= 65535) return Math.floor(n)
  } catch {
    /* ignore */
  }
  return CHIMERAX_DEFAULT_PORT
}

export function persistChimeraXPort(port: number) {
  try {
    localStorage.setItem(CHIMERAX_PORT_KEY, String(port))
  } catch {
    /* ignore */
  }
}

/** Public coordinate URL ChimeraX can `open` directly. */
export function structureFetchUrl(structure: ChimeraXOpenTarget['structure']): string {
  if (structure.source === 'pdb') {
    const id = structure.structureId.trim().toUpperCase()
    return `https://files.rcsb.org/download/${id}.pdb`
  }
  const acc = structure.accession.trim().toUpperCase()
  return `https://alphafold.ebi.ac.uk/files/AF-${acc}-F1-model_v4.pdb`
}

/** ChimeraX command list for the current Cistron structure context. */
export function buildChimeraXCommands(target: ChimeraXOpenTarget): string[] {
  const url = structureFetchUrl(target.structure)
  const cmds: string[] = [
    'close session',
    `open ${url}`,
    'cartoon',
    'hide atoms',
    'set bgColor #0b1220',
    'lighting soft',
  ]

  if (target.structure.source === 'alphafold') {
    cmds.push('color bfactor')
  } else {
    cmds.push('color bychain')
  }

  const resi = target.residue && target.residue > 0 ? target.residue : null
  if (resi != null) {
    const label = (target.residueLabel || `resi ${resi}`).replace(/"/g, '')
    cmds.push(
      `select :${resi}`,
      'show sel atoms',
      'style sel ball',
      'color sel #fb7185',
      `label sel "${label}"`,
      'view sel',
    )
  } else {
    cmds.push('view')
  }

  cmds.push(
    `log text Cistron · ${target.symbol} · ${target.structure.structureId}`,
  )
  return cmds
}

export function chimeraXScriptText(target: ChimeraXOpenTarget): string {
  const header = [
    `# Cistron → ChimeraX`,
    `# Gene: ${target.symbol}`,
    `# Structure: ${target.structure.structureId} (${target.structure.source})`,
    `# Generated: ${new Date().toISOString()}`,
    `#`,
    `# In ChimeraX: File → Open → this .cxc  (or drag onto the graphics window)`,
    `# Or enable REST:  remotecontrol rest start port ${loadChimeraXPort()} cors true`,
    ``,
  ]
  return [...header, ...buildChimeraXCommands(target), ``].join('\n')
}

export function downloadChimeraXScript(target: ChimeraXOpenTarget): void {
  const text = chimeraXScriptText(target)
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = `cistron_${target.symbol}_${target.structure.structureId}.cxc`
  a.click()
  URL.revokeObjectURL(href)
}

/** Batched command string for REST `/run?command=`. */
export function chimeraXRestCommand(target: ChimeraXOpenTarget): string {
  return buildChimeraXCommands(target).join(' ; ')
}

export function chimeraXRestRunUrl(target: ChimeraXOpenTarget, port = loadChimeraXPort()): string {
  const cmd = chimeraXRestCommand(target)
  return `http://127.0.0.1:${port}/run?command=${encodeURIComponent(cmd)}`
}

/**
 * Open structure in a running ChimeraX via top-level navigation to REST.
 * Works from hosted Cistron (no CORS) when ChimeraX remotecontrol is listening.
 */
export function openInChimeraXRest(target: ChimeraXOpenTarget, port = loadChimeraXPort()): void {
  const url = chimeraXRestRunUrl(target, port)
  window.open(url, '_blank', 'noopener,noreferrer')
}

/** Best-effort probe — only succeeds when page origin is allowed by ChimeraX CORS. */
export async function probeChimeraXRest(
  port = loadChimeraXPort(),
  timeoutMs = 900,
): Promise<boolean> {
  const ctrl = new AbortController()
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(
      `http://127.0.0.1:${port}/run?command=${encodeURIComponent('log text cistron-ping')}`,
      { method: 'GET', signal: ctrl.signal, mode: 'cors' },
    )
    return res.ok || res.status === 200 || res.type === 'opaque'
  } catch {
    return false
  } finally {
    window.clearTimeout(timer)
  }
}
