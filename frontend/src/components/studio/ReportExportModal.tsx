import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Download,
  FileText,
  Image as ImageIcon,
  Loader2,
  X,
} from 'lucide-react'
import { useLab } from '../../lab/LabContext'
import { MetaLabel } from '../ui'
import {
  assemblePublicationReport,
  downloadPublicationMarkdown,
  downloadPublicationPdf,
  type ReportBundle,
} from '../../services/reportExporter'

/**
 * 1-click Automated Scientific Report — PDF + Markdown from live LabContext.
 */
export function ReportExportModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const lab = useLab()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [bundle, setBundle] = useState<ReportBundle | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [hasCanvas, setHasCanvas] = useState(false)

  useEffect(() => {
    if (!open) return
    setHasCanvas(Boolean(document.querySelector('[data-cistron-export="topology"]')))
  }, [open])

  const previewAbstract = useMemo(() => {
    if (!open) return null
    const scenario = lab.controls.conditionQuery || 'Untitled scenario'
    const n = lab.graph ? Object.keys(lab.graph.nodes).length : 0
    const e = lab.graph?.edges.length ?? 0
    return `We analysed "${scenario}" on a causal network of ${n} nodes / ${e} edges. Export aggregates topology, trajectories, SL pairs, omics fit, and methodology.`
  }, [open, lab.controls.conditionQuery, lab.graph])

  if (!open) return null

  const assemble = async () => {
    setBusy(true)
    setError(null)
    setStatus('Capturing figures & compiling manuscript…')
    try {
      const next = await assemblePublicationReport(lab)
      setHasCanvas(Boolean(next.topologyPng))
      setBundle(next)
      setStatus('Report ready — download PDF or Markdown.')
      return next
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Report assembly failed'
      setError(msg)
      setStatus(null)
      return null
    } finally {
      setBusy(false)
    }
  }

  const onPdf = async () => {
    setBusy(true)
    setError(null)
    try {
      setStatus('Rendering publication PDF…')
      const b = await downloadPublicationPdf(lab)
      setBundle(b)
      setStatus('PDF downloaded.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF export failed')
    } finally {
      setBusy(false)
    }
  }

  const onMarkdown = async () => {
    setBusy(true)
    setError(null)
    try {
      setStatus('Writing Markdown + figures…')
      const b = await downloadPublicationMarkdown(lab)
      setBundle(b)
      setStatus('Markdown downloaded.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Markdown export failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="Close report export backdrop"
        onClick={onClose}
      />
      <div className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-700/80 bg-obsidian-panel shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-slate-800/80 px-4 py-3">
          <div>
            <MetaLabel className="text-emerald-300/90">Automated Scientific Report</MetaLabel>
            <h2 className="mt-1 text-lg font-extrabold tracking-tight text-slate-50">
              Export manuscript
            </h2>
            <p className="mt-0.5 text-[12px] text-slate-500">
              Abstract · Network Topology · Biophysical Trajectory · Target Identification ·
              Provenance
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700/80 p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
          <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 sm:grid-cols-3">
            <Stat label="Scenario" value={lab.controls.conditionQuery || '—'} />
            <Stat label="Provenance" value={lab.profileId || '—'} />
            <Stat
              label="Omics fit"
              value={
                lab.omicsAlignmentScore != null
                  ? `${lab.omicsAlignmentScore.toFixed(0)}%`
                  : '—'
              }
            />
            <Stat
              label="Network"
              value={
                lab.graph
                  ? `${Object.keys(lab.graph.nodes).length}n / ${lab.graph.edges.length}e`
                  : '—'
              }
            />
            <Stat
              label="Perturbations"
              value={String(Object.keys(lab.perturbations).length)}
            />
            <Stat label="3D target" value={lab.selectedNode || '—'} />
          </div>

          {!hasCanvas ? (
            <p className="rounded-lg border border-amber-500/30 bg-amber-950/30 px-3 py-2 text-[11px] text-amber-100">
              Topology figure captures from Simulation Studio.{' '}
              <button
                type="button"
                className="font-semibold text-cyan-300 underline"
                onClick={() => {
                  onClose()
                  navigate('/studio')
                }}
              >
                Open Studio
              </button>{' '}
              first for a canvas snapshot (text report still works here).
            </p>
          ) : null}

          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
            <MetaLabel className="mb-1.5">Preview · Abstract</MetaLabel>
            <p className="text-[12px] leading-relaxed text-slate-300">
              {bundle?.sections.find((s) => s.heading === 'Abstract')?.body ??
                previewAbstract ??
                '—'}
            </p>
          </div>

          {status ? (
            <p className="inline-flex items-center gap-2 text-[11px] text-cyan-200">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {status}
            </p>
          ) : null}
          {error ? (
            <p className="rounded-lg border border-coral-action/40 bg-coral-action/10 px-3 py-2 text-xs text-red-100">
              {error}
            </p>
          ) : null}
        </div>

        <footer className="flex flex-wrap gap-2 border-t border-slate-800/80 px-4 py-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void assemble()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-600 bg-slate-900/80 px-3 py-2 text-[12px] font-semibold text-slate-200 hover:border-slate-400 disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImageIcon className="h-3.5 w-3.5" />}
            Assemble
          </button>
          <button
            type="button"
            disabled={busy || !lab.graph}
            onClick={() => void onPdf()}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-[12px] font-bold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
            Download PDF
          </button>
          <button
            type="button"
            disabled={busy || !lab.graph}
            onClick={() => void onMarkdown()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-flux/40 bg-cyan-950/40 px-3 py-2 text-[12px] font-semibold text-cyan-100 hover:bg-cyan-900/40 disabled:opacity-40"
          >
            <FileText className="h-3.5 w-3.5" />
            Markdown
          </button>
        </footer>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800/80 bg-obsidian/60 px-2 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-600">
        {label}
      </div>
      <div className="truncate font-mono text-[11px] text-slate-200" title={value}>
        {value}
      </div>
    </div>
  )
}
