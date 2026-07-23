import { useEffect, useState } from 'react'
import { Activity, Dna, Loader2, Search, WifiOff } from 'lucide-react'
import { useLab } from '../lab/LabContext'
import { GeneBadge, MetaLabel, MetricChip, StatusPill } from '../components/ui'

export function HeaderBar() {
  const {
    controls,
    patchControls,
    runQuery,
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
  } = useLab()

  const [draft, setDraft] = useState(controls.conditionQuery)

  useEffect(() => {
    setDraft(controls.conditionQuery)
  }, [controls.conditionQuery])

  const submit = () => {
    const q = draft.trim()
    if (!q || busy || !engineLive) return
    patchControls({ conditionQuery: q })
    runQuery(q)
  }

  const odeMs = latencyMs ?? scientist?.elapsed_ms ?? null

  return (
    <header className="flex shrink-0 flex-col gap-2 border-b border-slate-800/80 bg-obsidian-panel/80 px-4 py-2.5 backdrop-blur-xl">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-extrabold tracking-tight text-slate-50">
              Cistron
            </span>
            <span className="hidden rounded-full border border-cyan-flux/30 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-300 sm:inline">
              VCL
            </span>
          </div>
          <div className="mt-0.5 flex max-w-[16rem] items-center gap-1.5">
            <MetaLabel className="!normal-case !tracking-normal text-slate-500">
              Scenario
            </MetaLabel>
            <span
              className="truncate text-[11px] font-medium text-slate-300"
              title={controls.conditionQuery}
            >
              {controls.conditionQuery || 'No active scenario'}
            </span>
          </div>
        </div>

        <div className="relative min-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
            }}
            placeholder="Disease · stress · drug condition…"
            className="w-full rounded-xl border border-slate-700/80 bg-obsidian/70 py-2 pl-9 pr-20 text-[13px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-emerald-500/45 focus:shadow-[0_0_0_3px_rgba(16,185,129,0.12)]"
          />
          <button
            type="button"
            disabled={!engineLive || busy || !draft.trim()}
            onClick={submit}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-lg bg-emerald-500/15 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-300 transition hover:bg-emerald-500/25 disabled:opacity-40"
          >
            Run
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <StatusPill
            live={engineLive}
            busy={busy || initializing}
            label={
              initializing ? 'Integrating' : engineLive ? 'Engine Live' : 'Offline'
            }
          />
          <MetricChip>
            <span className="text-emerald-400/90">●</span>
            <span className="uppercase tracking-wider">Kraeutler ODE</span>
            <strong className="lab-mono text-slate-100">
              {odeMs != null ? `${odeMs.toFixed(0)}ms` : '—'}
            </strong>
          </MetricChip>
          <MetricChip>
            <Activity className="h-3 w-3 text-cyan-flux" />
            ping
            <strong className="lab-mono text-slate-100">
              {pingMs != null ? `${pingMs.toFixed(0)}ms` : '—'}
            </strong>
          </MetricChip>
          {profileId ? <GeneBadge name={profileId} tone="violet" /> : null}
          {activeOmicsProfile ? (
            <MetricChip className="border-orange-500/40 bg-orange-950/40 text-orange-100 shadow-[0_0_12px_rgba(249,115,22,0.2)]">
              <Dna className="h-3 w-3 text-orange-300" />
              <span className="uppercase tracking-wider">Omics-Conditioned</span>
              <strong className="lab-mono max-w-[7rem] truncate text-orange-50">
                {activeOmicsProfile.condition || activeOmicsProfile.sample_name}
              </strong>
              {omicsAlignmentScore != null ? (
                <strong className="lab-mono text-amber-200">
                  fit {omicsAlignmentScore.toFixed(0)}%
                </strong>
              ) : null}
            </MetricChip>
          ) : null}
          <MetricChip className="max-w-[9rem]">
            sim
            <strong className="lab-mono truncate text-slate-200">
              {payload?.simulation_id ?? '—'}
            </strong>
          </MetricChip>
          {busy ? (
            <MetricChip className="border-amber-kinase/30 text-amber-200">
              <Loader2 className="h-3 w-3 animate-spin" />
              Solving
            </MetricChip>
          ) : null}
        </div>
      </div>

      {offlineMessage ? (
        <div className="flex items-start gap-2 rounded-xl border border-coral-action/40 bg-coral-action/10 px-3 py-2 text-xs text-red-100">
          <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{offlineMessage}</span>
        </div>
      ) : null}
    </header>
  )
}
