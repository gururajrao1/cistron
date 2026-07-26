import { useEffect, useState } from 'react'
import { Download, Loader2, Search, WifiOff } from 'lucide-react'
import { useLab } from '../../lab/LabContext'
import { OmicsProvenanceBadge } from '../ui'
import { resolveOmicsProvenance } from '../../api/types'
import { ReportExportModal } from './ReportExportModal'

const SCENARIO_PRESETS = [
  'Hypoxia-induced angiogenesis',
  'EGFR oncogenic signaling',
  'TNF inflammatory cascade',
  'PI3K-AKT survival pathway',
  'WNT developmental signaling',
] as const

/**
 * Top chrome — Cistron VCL Systems Biology IDE mockup.
 */
export function Header() {
  const {
    controls,
    patchControls,
    runQuery,
    runSimulation,
    engineLive,
    busy,
    initializing,
    latencyMs,
    pingMs,
    payload,
    offlineMessage,
    profileId,
    scientist,
    activeOmicsProfile,
    omicsAlignmentScore,
    statusStage,
    graph,
  } = useLab()

  const [draft, setDraft] = useState(controls.conditionQuery)
  const [reportOpen, setReportOpen] = useState(false)

  useEffect(() => {
    setDraft(controls.conditionQuery)
  }, [controls.conditionQuery])

  const submit = () => {
    const q = draft.trim()
    if (!q || busy || !engineLive) return
    patchControls({ conditionQuery: q })
    runQuery(q)
  }

  const runSim = () => {
    if (busy || !engineLive) return
    const q = draft.trim()
    if (q && q !== controls.conditionQuery) {
      patchControls({ conditionQuery: q })
      runQuery(q)
      return
    }
    runSimulation()
  }

  const odeMs = latencyMs ?? scientist?.elapsed_ms ?? null
  const live = engineLive && !initializing

  return (
    <>
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-vcl-border bg-obsidian-panel px-3">
        <div className="flex shrink-0 items-baseline gap-1.5">
          <span className="font-mono text-[13px] font-bold tracking-[0.04em] text-vcl-text">
            CISTRON
          </span>
          <span className="font-mono text-[11px] font-semibold tracking-widest text-emerald-active">
            ·VCL
          </span>
        </div>

        <div className="relative min-w-[10rem] max-w-md flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-vcl-dim" />
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
            }}
            placeholder="Search condition…"
            className="h-8 w-full rounded-md border border-vcl-border bg-obsidian py-0 pl-8 pr-12 font-mono text-[11px] text-vcl-text outline-none placeholder:text-vcl-dim focus:border-emerald-active/50"
          />
          <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9px] text-vcl-dim">
            ⌘K
          </kbd>
        </div>

        <select
          value={
            SCENARIO_PRESETS.includes(
              controls.conditionQuery as (typeof SCENARIO_PRESETS)[number],
            )
              ? controls.conditionQuery
              : '__custom__'
          }
          onChange={(e) => {
            const v = e.target.value
            if (v === '__custom__') return
            setDraft(v)
            patchControls({ conditionQuery: v })
            if (engineLive && !busy) runQuery(v)
          }}
          title={controls.conditionQuery}
          className="h-8 max-w-[14rem] shrink-0 rounded-md border border-vcl-border bg-vcl-surface px-2 font-mono text-[11px] text-vcl-text outline-none focus:border-emerald-active/50"
        >
          {!SCENARIO_PRESETS.includes(
            controls.conditionQuery as (typeof SCENARIO_PRESETS)[number],
          ) ? (
            <option value="__custom__">
              {controls.conditionQuery.slice(0, 42) || 'Custom scenario'}
            </option>
          ) : null}
          {SCENARIO_PRESETS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <button
          type="button"
          disabled={!engineLive || busy}
          onClick={runSim}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-emerald-active px-3 font-mono text-[10px] font-bold uppercase tracking-[0.08em] text-obsidian transition hover:brightness-110 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          Run Simulation
        </button>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <div
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-vcl-border bg-vcl-surface px-2.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-vcl-muted"
            title={
              busy
                ? statusStage || 'Solving'
                : live
                  ? `ODE ${odeMs != null ? `${odeMs.toFixed(0)}ms` : '—'} · ping ${pingMs != null ? `${pingMs.toFixed(0)}ms` : '—'}`
                  : 'Engine offline'
            }
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                live
                  ? 'vcl-pulse bg-emerald-active'
                  : 'bg-coral-action'
              }`}
            />
            {initializing ? 'Integrating' : live ? 'Engine Live' : 'Offline'}
          </div>

          {profileId ? (
            <span
              className="hidden max-w-[9rem] truncate rounded-md border border-violet-hub/30 bg-violet-hub/10 px-2 py-1 font-mono text-[10px] text-violet-hub lg:inline"
              title={profileId}
            >
              {profileId}
            </span>
          ) : null}

          {activeOmicsProfile ? (
            <span className="hidden items-center gap-1 rounded-md border border-amber-kinase/35 bg-amber-kinase/10 px-2 py-1 font-mono text-[10px] text-amber-200 sm:inline-flex">
              Omics
              <OmicsProvenanceBadge
                provenance={resolveOmicsProvenance(activeOmicsProfile)}
              />
              {omicsAlignmentScore != null
                ? `${omicsAlignmentScore.toFixed(0)}%`
                : null}
            </span>
          ) : null}

          {payload?.simulation_id ? (
            <span
              className="hidden max-w-[7rem] truncate font-mono text-[10px] text-vcl-dim xl:inline"
              title={payload.simulation_id}
            >
              {payload.simulation_id}
            </span>
          ) : null}

          <button
            type="button"
            disabled={!graph}
            onClick={() => setReportOpen(true)}
            title={
              graph ? 'Export scientific report (PDF / Markdown)' : 'Run a scenario first'
            }
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-vcl-border bg-vcl-raised px-2.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-vcl-text transition hover:border-vcl-border-strong disabled:opacity-40"
          >
            <Download className="h-3 w-3 text-vcl-muted" />
            Export Report
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
