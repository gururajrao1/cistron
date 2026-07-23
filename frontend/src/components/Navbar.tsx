import { Activity, Loader2 } from 'lucide-react'

export function Navbar({
  engineLive,
  latencyMs,
  simulationId,
  initializing = false,
}: {
  engineLive: boolean
  latencyMs?: number | null
  simulationId?: string | null
  initializing?: boolean
}) {
  return (
    <header className="flex items-center justify-between gap-4 rounded-2xl border border-slate-800 bg-slate-900/50 px-4 py-3 backdrop-blur-md">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-500/40 bg-gradient-to-br from-emerald-500/25 to-coral-action/20 text-sm font-extrabold text-emerald-50 shadow-[0_0_24px_rgba(16,185,129,0.35)]">
          VS
        </div>
        <div>
          <div className="font-[family-name:var(--font-sans)] text-base font-extrabold tracking-tight text-slate-50">
            VoidSignal
          </div>
          <div className="text-xs text-slate-500">Virtual Cellular Laboratory</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <div
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[0.7rem] font-semibold tracking-wide ${
            engineLive
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-slate-700 bg-slate-800/60 text-slate-400'
          }`}
        >
          {initializing ? (
            <Loader2 className="h-3 w-3 animate-spin text-emerald-active" />
          ) : (
            <span
              className={`h-2 w-2 rounded-full ${
                engineLive ? 'bg-emerald-active shadow-[0_0_10px_#10B981]' : 'bg-slate-500'
              }`}
            />
          )}
          {initializing ? 'INTEGRATING' : engineLive ? 'ENGINE LIVE' : 'ENGINE OFFLINE'}
        </div>
        <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900/70 px-3 py-1 text-[0.7rem] text-slate-400">
          <Activity className="h-3.5 w-3.5 text-emerald-active" />
          Cycle
          <strong className="ml-1 font-semibold text-slate-100">
            {latencyMs != null ? `${latencyMs.toFixed(0)} ms` : '—'}
          </strong>
        </div>
        <div className="inline-flex items-center rounded-full border border-slate-800 bg-slate-900/70 px-3 py-1 text-[0.7rem] text-slate-400">
          Experiment
          <strong className="ml-1 max-w-[9rem] truncate font-semibold text-slate-100">
            {simulationId ?? '—'}
          </strong>
        </div>
      </div>
    </header>
  )
}
