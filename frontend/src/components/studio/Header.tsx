import { useEffect, useState } from 'react'
import { Download, Loader2, WifiOff } from 'lucide-react'
import { useLab } from '../../lab/LabContext'
import { ReportExportModal } from './ReportExportModal'

const SCENARIO_PRESETS = [
  { label: 'Hypoxia 1.5% O₂', query: 'Hypoxia-induced angiogenesis' },
  { label: 'Ischemic 0.5% O₂', query: 'Ischemic hypoxia signaling' },
  { label: 'Normoxia 21% O₂', query: 'Normoxia basal signaling' },
  { label: 'Pseudohypoxia VHL-null', query: 'VHL-null pseudohypoxia' },
] as const

type Props = {
  onOpenPalette?: () => void
}

/**
 * Top chrome — Cistron VCL Systems Biology IDE mockup (46px).
 */
export function Header({ onOpenPalette }: Props) {
  const {
    controls,
    patchControls,
    runQuery,
    runSimulation,
    engineLive,
    busy,
    initializing,
    latencyMs,
    offlineMessage,
    scientist,
    graph,
  } = useLab()

  const [reportOpen, setReportOpen] = useState(false)

  useEffect(() => {
    // keep scenario select in sync when Pathways / omics mutate conditionQuery
  }, [controls.conditionQuery])

  const runSim = () => {
    if (busy || !engineLive) return
    runSimulation()
  }

  const odeMs = latencyMs ?? scientist?.elapsed_ms ?? null
  const live = engineLive && !initializing
  const modKey = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform) ? '⌘' : 'Ctrl'

  const scenarioValue =
    SCENARIO_PRESETS.find((s) => s.query === controls.conditionQuery)?.query ?? '__custom__'

  return (
    <>
      <header className="flex h-[46px] shrink-0 items-center gap-3 border-b border-vcl-border bg-obsidian-panel px-3">
        <div className="flex shrink-0 items-center gap-2">
          <div className="relative grid h-5 w-5 place-items-center rounded-[5px] border border-vcl-border-strong bg-vcl-surface">
            <span className="h-[7px] w-[7px] rounded-full bg-emerald-active" />
          </div>
          <div className="flex items-baseline gap-1">
            <span className="font-mono text-[13px] font-bold tracking-[0.04em] text-vcl-text">
              CISTRON
            </span>
            <span className="font-mono text-[11px] font-semibold tracking-widest text-vcl-muted">
              ·VCL
            </span>
            <span className="ml-1 rounded border border-vcl-border bg-vcl-raised px-1 py-px font-mono text-[9.5px] text-vcl-dim">
              v4.2
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={() => onOpenPalette?.()}
          className="flex h-7 min-w-[12rem] max-w-xs flex-[0_1_320px] items-center gap-2 rounded-md border border-vcl-border bg-obsidian px-2.5 text-left transition hover:border-vcl-border-strong"
        >
          <span className="truncate font-mono text-[11px] text-vcl-dim">
            Search targets, pathways, commands…
          </span>
          <kbd className="ml-auto shrink-0 rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9px] text-vcl-dim">
            {modKey}K
          </kbd>
        </button>

        <div className="flex shrink-0 items-center gap-1.5">
          <span className="lab-meta hidden sm:inline">Scenario</span>
          <select
            value={scenarioValue}
            onChange={(e) => {
              const v = e.target.value
              if (v === '__custom__') return
              patchControls({ conditionQuery: v })
              if (engineLive && !busy) runQuery(v)
            }}
            title={controls.conditionQuery}
            className="h-7 max-w-[15rem] rounded-md border border-vcl-border bg-vcl-surface px-2 font-mono text-[11px] text-vcl-text outline-none focus:border-emerald-active/50"
          >
            {scenarioValue === '__custom__' ? (
              <option value="__custom__">
                {controls.conditionQuery.slice(0, 42) || 'Custom scenario'}
              </option>
            ) : null}
            {SCENARIO_PRESETS.map((s) => (
              <option key={s.query} value={s.query}>
                {s.label}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          disabled={!engineLive || busy}
          onClick={runSim}
          className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-emerald-active/45 bg-[#14361F] px-3 font-mono text-[10px] font-bold uppercase tracking-[0.08em] text-[#6EE7A0] transition hover:brightness-110 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <span>▶</span>}
          Run Simulation
        </button>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <div
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-vcl-border bg-vcl-surface px-2.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-vcl-muted"
            title={live ? `Solver ${odeMs != null ? `${odeMs.toFixed(0)}ms` : '—'}` : 'Engine offline'}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                live ? 'vcl-pulse bg-emerald-active' : 'bg-coral-action'
              }`}
            />
            {initializing ? 'Integrating' : live ? 'Engine Live' : 'Offline'}
            {live && odeMs != null ? (
              <span className="text-vcl-dim normal-case tracking-normal">
                {odeMs.toFixed(0)}ms
              </span>
            ) : null}
          </div>

          <button
            type="button"
            disabled={!graph}
            onClick={() => setReportOpen(true)}
            title={graph ? 'Export scientific report (PDF / Markdown)' : 'Run a scenario first'}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-vcl-border bg-transparent px-2.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-vcl-text transition hover:bg-vcl-raised disabled:opacity-40"
          >
            <Download className="h-3 w-3 text-vcl-muted" />
            Export Report (PDF)
          </button>
        </div>
      </header>

      {offlineMessage ? (
        <div className="flex items-start gap-2 border-b border-coral-action/40 bg-coral-action/10 px-3 py-2 text-xs text-red-100">
          <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{offlineMessage}</span>
        </div>
      ) : null}

      <ReportExportModal open={reportOpen} onClose={() => setReportOpen(false)} />
    </>
  )
}

/** @deprecated Prefer {@link Header} */
export { Header as HeaderBar }
