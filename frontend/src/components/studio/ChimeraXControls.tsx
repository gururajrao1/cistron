import { useEffect, useState } from 'react'
import { Download, ExternalLink, Settings2 } from 'lucide-react'
import { clsx } from 'clsx'
import type { PdbFetchResult } from '../../utils/bioApi'
import {
  CHIMERAX_DEFAULT_PORT,
  downloadChimeraXScript,
  loadChimeraXPort,
  openInChimeraXRest,
  persistChimeraXPort,
  probeChimeraXRest,
  type ChimeraXOpenTarget,
} from '../../services/chimeraX'

type Props = {
  symbol: string
  structure: PdbFetchResult | null
  residue?: number | null
  residueLabel?: string | null
  disabled?: boolean
}

/**
 * Open the resolved fold in UCSF ChimeraX (desktop) via .cxc download or REST.
 */
export function ChimeraXControls({
  symbol,
  structure,
  residue,
  residueLabel,
  disabled,
}: Props) {
  const [port, setPort] = useState(loadChimeraXPort)
  const [restLive, setRestLive] = useState<boolean | null>(null)
  const [showPort, setShowPort] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void probeChimeraXRest(port).then((ok) => {
      if (!cancelled) setRestLive(ok)
    })
    return () => {
      cancelled = true
    }
  }, [port, structure?.structureId])

  const ready = Boolean(structure) && !disabled
  const target: ChimeraXOpenTarget | null = structure
    ? {
        symbol,
        structure: {
          structureId: structure.structureId,
          source: structure.source,
          accession: structure.accession,
          structureUrl: structure.structureUrl,
        },
        residue,
        residueLabel,
      }
    : null

  const notify = (msg: string) => {
    setFlash(msg)
    window.setTimeout(() => setFlash(null), 3200)
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={!ready || !target}
          title="Download a ChimeraX .cxc script (open in ChimeraX)"
          onClick={() => {
            if (!target) return
            downloadChimeraXScript(target)
            notify('Downloaded .cxc — open it in ChimeraX (File → Open)')
          }}
          className={clsx(
            'inline-flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px] font-semibold transition',
            ready
              ? 'border-violet-hub/45 bg-violet-950/40 text-violet-100 hover:brightness-110'
              : 'cursor-not-allowed border-vcl-border text-vcl-dim opacity-40',
          )}
        >
          <Download className="h-3 w-3" />
          ChimeraX · .cxc
        </button>
        <button
          type="button"
          disabled={!ready || !target}
          title={
            restLive
              ? `Send to ChimeraX REST on port ${port}`
              : `Open REST URL (start ChimeraX: remotecontrol rest start port ${port} cors true)`
          }
          onClick={() => {
            if (!target) return
            openInChimeraXRest(target, port)
            notify(
              restLive
                ? 'Sent to ChimeraX REST'
                : `Opened REST URL — if nothing happened, run: remotecontrol rest start port ${port} cors true`,
            )
          }}
          className={clsx(
            'inline-flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px] font-semibold transition',
            ready
              ? restLive
                ? 'border-emerald-500/45 bg-emerald-950/40 text-emerald-100 hover:brightness-110'
                : 'border-vcl-border bg-vcl-surface text-vcl-soft hover:border-cyan-flux/40'
              : 'cursor-not-allowed border-vcl-border text-vcl-dim opacity-40',
          )}
        >
          <ExternalLink className="h-3 w-3" />
          ChimeraX · REST
          {restLive === true ? (
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-active" />
          ) : null}
        </button>
        <button
          type="button"
          title="ChimeraX REST port"
          onClick={() => setShowPort((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md border border-vcl-border bg-vcl-surface px-1.5 py-1 font-mono text-[10px] text-vcl-muted hover:text-vcl-text"
        >
          <Settings2 className="h-3 w-3" />
          :{port}
        </button>
      </div>
      {showPort ? (
        <label className="flex flex-wrap items-center gap-2 font-mono text-[10px] text-vcl-dim">
          REST port
          <input
            type="number"
            min={1024}
            max={65535}
            value={port}
            onChange={(e) => {
              const n = Number(e.target.value) || CHIMERAX_DEFAULT_PORT
              setPort(n)
              persistChimeraXPort(n)
              setRestLive(null)
            }}
            className="w-20 rounded border border-vcl-border bg-obsidian px-1.5 py-0.5 text-vcl-text"
          />
          <span className="text-[9px] leading-snug text-vcl-dim">
            In ChimeraX: <code className="text-cyan-flux">remotecontrol rest start port {port} cors true</code>
          </span>
        </label>
      ) : null}
      {flash ? <p className="font-mono text-[9.5px] text-cyan-flux/90">{flash}</p> : null}
      <p className="text-[9.5px] leading-relaxed text-vcl-dim">
        Browser preview uses 3Dmol. ChimeraX is the desktop viewer for figures &amp; analysis — download
        .cxc, or enable REST remotecontrol on localhost.
      </p>
    </div>
  )
}
