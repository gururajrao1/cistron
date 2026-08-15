import { useEffect, useMemo, useState } from 'react'
import { Bookmark, Download, Loader2, WifiOff } from 'lucide-react'
import { useLab } from '../../lab/LabContext'
import { ViewModeSwitcher } from '../../layout/ViewModeSwitcher'
import { RawMathOnly } from '../../layout/viewModeGates'
import { ReportExportModal } from './ReportExportModal'
import { OmicsProvenanceBadge } from '../ui'
import { resolveOmicsProvenance } from '../../api/types'
import {
  deleteSnapshot,
  listSnapshots,
  saveSnapshot,
  type ExperimentSnapshot,
} from '../../services/experimentSnapshots'
import { markFirstRunExportDone } from './FirstRunChecklist'

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
 * Top chrome — CISTRON·VCL + provenance strip + snapshots + export.
 */
export function Header({ onOpenPalette }: Props) {
  const lab = useLab()
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
    profileId,
    activeOmicsProfile,
    omicsAlignmentScore,
    clearAllPerturbations,
    setNodePerturbation,
    setScrubT,
    viewMode,
    setViewMode,
  } = lab

  const [reportOpen, setReportOpen] = useState(false)
  const [snapOpen, setSnapOpen] = useState(false)
  const [snaps, setSnaps] = useState<ExperimentSnapshot[]>(() => listSnapshots())

  useEffect(() => {
    // keep scenario select in sync when Pathways / omics mutate conditionQuery
  }, [controls.conditionQuery])

  const runSim = () => {
    if (busy || !engineLive) return
    runSimulation()
  }

  const odeMs = latencyMs ?? scientist?.elapsed_ms ?? null
  const live = engineLive && !initializing
  const modKey =
    typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform) ? '⌘' : 'Ctrl'

  const scenarioValue =
    SCENARIO_PRESETS.find((s) => s.query === controls.conditionQuery)?.query ??
    '__custom__'

  const sourceBadge = useMemo(() => {
    const sources = controls.selectedSources?.filter((s) => s !== 'local') ?? []
    if (sources.length) return sources.slice(0, 2).join('+')
    if (profileId?.startsWith('dynamic')) return 'Reactome·STRING'
    return 'local'
  }, [controls.selectedSources, profileId])

  const saveCurrent = () => {
    const name =
      window.prompt(
        'Snapshot name',
        controls.conditionQuery.slice(0, 40) || 'Experiment',
      )?.trim() || 'Experiment'
    saveSnapshot({
      name,
      conditionQuery: controls.conditionQuery,
      profileId,
      scrubT: lab.scrubT,
      perturbations: { ...lab.perturbations },
      knockouts: [...controls.knockouts],
      simId: lab.lastSimId,
      controls: {
        clampNode: controls.clampNode,
        clampValue: controls.clampValue,
        drugEnabled: controls.drugEnabled,
        drugTarget: controls.drugTarget,
        cDrug: controls.cDrug,
        ki: controls.ki,
        sourceNode: controls.sourceNode,
        targetNode: controls.targetNode,
        selectedSources: [...controls.selectedSources],
      },
    })
    setSnaps(listSnapshots())
    setSnapOpen(true)
  }

  const restore = (snap: ExperimentSnapshot) => {
    clearAllPerturbations({ resim: false })
    patchControls({
      conditionQuery: snap.conditionQuery,
      knockouts: snap.knockouts,
      ...snap.controls,
    })
    Object.entries(snap.perturbations).forEach(([sym, v]) => {
      setNodePerturbation(sym, v, { resim: false })
    })
    setScrubT(snap.scrubT)
    setSnapOpen(false)
    if (engineLive && !busy) {
      runQuery(snap.conditionQuery)
    }
  }

  return (
    <>
      <header className="relative flex h-[48px] shrink-0 items-center gap-3 border-b border-cyan-flux/25 bg-[#041820]/95 px-3 backdrop-blur-md">
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-[2px] lab-membrane-bar"
          aria-hidden
        />
        <div className="flex shrink-0 items-center gap-2.5">
          {/* Helix mark — life-sciences brand cue */}
          <div
            className="relative grid h-7 w-7 place-items-center rounded-md border border-cyan-flux/45 bg-[#0a2834] shadow-[0_0_18px_rgba(45,212,191,0.35)]"
            aria-hidden
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M4 2c3 2.5 5 2.5 8 0M4 8c3 2.5 5 2.5 8 0M4 14c3 2.5 5 2.5 8 0"
                stroke="#2dd4bf"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
              <path
                d="M12 2c-3 2.5-5 2.5-8 0M12 8c-3 2.5-5 2.5-8 0M12 14c-3 2.5-5 2.5-8 0"
                stroke="#c8f542"
                strokeWidth="1.2"
                strokeLinecap="round"
                opacity="0.85"
              />
            </svg>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-display text-[15px] font-bold tracking-tight text-vcl-text">
              CISTRON
            </span>
            <span className="font-mono text-[10px] font-bold tracking-[0.16em] text-phosphor">
              VCL
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={() => onOpenPalette?.()}
          className="vcl-focus-ring flex h-7 min-w-[10rem] max-w-xs flex-[0_1_280px] items-center gap-2 rounded-md border border-vcl-border bg-obsidian px-2.5 text-left transition hover:border-cyan-flux/35 hover:bg-vcl-surface/60 active:scale-[0.99]"
        >
          <span className="truncate font-mono text-[11px] text-vcl-dim">
            Search targets, pathways, commands…
          </span>
          <kbd className="ml-auto shrink-0 rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9px] text-vcl-dim">
            {modKey}K
          </kbd>
        </button>

        <div className="flex shrink-0 items-center gap-1.5">
          <select
            value={scenarioValue}
            onChange={(e) => {
              const v = e.target.value
              if (v === '__custom__') return
              patchControls({ conditionQuery: v })
              if (engineLive && !busy) runQuery(v)
            }}
            title={controls.conditionQuery}
            className="vcl-focus-ring h-7 max-w-[13rem] rounded-md border border-vcl-border bg-vcl-surface px-2 font-mono text-[11px] text-vcl-text outline-none transition hover:border-vcl-border-strong focus:border-cyan-flux/50"
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

        {/* Provenance strip */}
        <div className="hidden min-w-0 items-center gap-1.5 lg:flex">
          <span
            className="max-w-[7rem] truncate rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9.5px] text-vcl-link"
            title={profileId || 'profile'}
          >
            {profileId ? (profileId.length > 18 ? `${profileId.slice(0, 16)}…` : profileId) : '—'}
          </span>
          <span className="rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9.5px] text-vcl-muted">
            {sourceBadge}
          </span>
          {lab.lastSimId ? (
            <span
              className="rounded border border-cyan-flux/30 bg-[#0a2834] px-1.5 py-0.5 font-mono text-[9.5px] text-cyan-flux/90"
              title="FAIR simulation hash"
            >
              sim {lab.lastSimId.slice(0, 8)}
            </span>
          ) : null}
          {activeOmicsProfile ? (
            <>
              <OmicsProvenanceBadge
                provenance={resolveOmicsProvenance(activeOmicsProfile)}
              />
              {omicsAlignmentScore != null ? (
                <RawMathOnly>
                  <span className="font-mono text-[9.5px] text-amber-kinase">
                    fit {omicsAlignmentScore.toFixed(0)}%
                  </span>
                </RawMathOnly>
              ) : null}
            </>
          ) : null}
        </div>

        <button
          type="button"
          disabled={!engineLive || busy}
          onClick={runSim}
          className="vcl-focus-ring inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-phosphor/40 bg-[#1a2a0a] px-3 font-mono text-[10px] font-bold uppercase tracking-[0.08em] text-phosphor transition hover:brightness-110 active:scale-[0.98] disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <span>▶</span>}
          Run
        </button>

        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <ViewModeSwitcher mode={viewMode} onChange={setViewMode} />
          <div
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-vcl-border bg-vcl-surface px-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-vcl-muted"
            title={live ? `Solver ${odeMs != null ? `${odeMs.toFixed(0)}ms` : '—'}` : 'Engine offline'}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                live ? 'vcl-pulse bg-emerald-active' : 'bg-coral-action'
              }`}
            />
            {initializing ? 'Integrating' : live ? 'Live' : 'Offline'}
            {live && odeMs != null ? (
              <RawMathOnly>
                <span className="text-vcl-dim normal-case tracking-normal">
                  {odeMs.toFixed(0)}ms
                </span>
              </RawMathOnly>
            ) : null}
          </div>

          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setSnaps(listSnapshots())
                setSnapOpen((o) => !o)
              }}
              title="Experiment snapshots"
              className="vcl-focus-ring inline-flex h-7 items-center gap-1 rounded-md border border-vcl-border px-2 font-mono text-[10px] text-vcl-soft transition hover:border-vcl-border-strong hover:bg-vcl-raised active:scale-[0.98]"
            >
              <Bookmark className="h-3 w-3" />
              Snap
            </button>
            {snapOpen ? (
              <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-lg border border-vcl-border bg-obsidian-panel/95 p-2 shadow-2xl backdrop-blur-md">
                <button
                  type="button"
                  disabled={!graph}
                  onClick={saveCurrent}
                  className="vcl-focus-ring mb-2 w-full rounded-[5px] border border-cyan-flux/40 bg-[#0a1f28] px-2 py-1.5 text-[11px] font-semibold text-cyan-flux transition hover:brightness-110 disabled:opacity-40"
                >
                  Save current experiment
                </button>
                <ul className="max-h-48 space-y-1 overflow-y-auto">
                  {snaps.length === 0 ? (
                    <li className="px-1 py-2 text-[10px] text-vcl-dim">No snapshots yet.</li>
                  ) : (
                    snaps.map((s) => (
                      <li
                        key={s.id}
                        className="flex items-center gap-1 rounded-md border border-vcl-border/80 px-1.5 py-1 transition hover:border-vcl-border-strong"
                      >
                        <button
                          type="button"
                          onClick={() => restore(s)}
                          className="vcl-focus-ring min-w-0 flex-1 rounded text-left"
                        >
                          <div className="truncate text-[11px] text-vcl-text">{s.name}</div>
                          <div className="truncate font-mono text-[9px] text-vcl-dim">
                            {new Date(s.savedAt).toLocaleString()}
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            deleteSnapshot(s.id)
                            setSnaps(listSnapshots())
                          }}
                          className="vcl-focus-ring rounded px-1 text-[10px] text-vcl-dim hover:text-coral-action"
                        >
                          ×
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            ) : null}
          </div>

          <button
            type="button"
            disabled={!graph}
            onClick={() => {
              setReportOpen(true)
              markFirstRunExportDone()
            }}
            title={graph ? 'Export scientific report (PDF / Markdown)' : 'Run a scenario first'}
            className="vcl-focus-ring inline-flex h-7 items-center gap-1.5 rounded-md border border-vcl-border bg-transparent px-2.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-vcl-text transition hover:border-vcl-border-strong hover:bg-vcl-raised active:scale-[0.98] disabled:opacity-40"
          >
            <Download className="h-3 w-3 text-vcl-muted" />
            Export
          </button>
        </div>
      </header>

      {!live && !offlineMessage ? (
        <div className="flex items-start gap-2 border-b border-vcl-border bg-vcl-surface/80 px-3 py-1.5 text-[11px] text-vcl-muted">
          <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
          <span>Connecting to API…</span>
        </div>
      ) : null}
      {offlineMessage ? (
        <div className="flex items-start gap-2 border-b border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-50">
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
