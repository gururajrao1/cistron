import { FlaskConical, Play, Search, WifiOff } from 'lucide-react'
import { GlassCard } from './GlassCard'
import type { ConditionSuggestion, LabControls } from '../api/types'
import { SUGGESTION_QUERIES } from '../api/types'

export function ControlDock({
  suggestions,
  controls,
  nodes,
  clampOptions,
  busy,
  engineLive,
  statusStage,
  onChange,
  onRun,
}: {
  suggestions: ConditionSuggestion[]
  controls: LabControls
  nodes: string[]
  clampOptions: string[]
  busy: boolean
  engineLive: boolean
  statusStage?: string | null
  onChange: (next: LabControls) => void
  onRun: () => void
}) {
  const patch = (partial: Partial<LabControls>) => onChange({ ...controls, ...partial })
  const canRun = engineLive && !busy && controls.conditionQuery.trim().length > 0
  const chips =
    suggestions.length > 0
      ? suggestions
      : SUGGESTION_QUERIES.map((q) => ({ label: q.split(' ').slice(0, 2).join(' '), query: q }))

  return (
    <aside className="flex h-full flex-col gap-3 overflow-y-auto pr-1">
      <div>
        <div className="text-sm font-extrabold tracking-tight text-slate-50">Experiment Dock</div>
        <p className="text-xs text-slate-500">Any disease · stress · drug condition</p>
      </div>

      {!engineLive ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>Cellular engine offline — reconnect to resume experimentation.</span>
        </div>
      ) : null}

      <GlassCard title="Condition Search" hint="Free-text biological query → dynamic network">
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={controls.conditionQuery}
            onChange={(e) => patch({ conditionQuery: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && canRun) onRun()
            }}
            placeholder="e.g. Alzheimer's amyloid stress…"
            className="w-full rounded-xl border border-slate-700 bg-slate-950/70 py-2.5 pl-9 pr-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-emerald-500/50"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {chips.slice(0, 8).map((c) => (
            <button
              key={c.query}
              type="button"
              disabled={busy}
              onClick={() => patch({ conditionQuery: c.query })}
              className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1 text-[0.68rem] text-slate-300 transition hover:border-emerald-500/40 hover:text-emerald-200 disabled:opacity-50"
            >
              {c.label}
            </button>
          ))}
        </div>
        {statusStage ? (
          <p className="mt-3 text-xs leading-relaxed text-emerald-300/90">{statusStage}</p>
        ) : (
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            Resolves OmniPath / curated interactions, tags enzymatic vs transcriptional latency, then
            integrates Hill-cube dynamics.
          </p>
        )}
      </GlassCard>

      <GlassCard title="Gene Knockouts & Clamps" hint="Kraeutler logic kinetics · capacity wᵢ">
        {clampOptions.length > 0 ? (
          <>
            <label className="mb-1 block text-xs text-slate-400">Clamp node</label>
            <select
              className="mb-2 w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm"
              value={controls.clampNode}
              onChange={(e) => patch({ clampNode: e.target.value })}
            >
              {clampOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <label className="mb-1 block text-xs text-slate-400">
              Level ({controls.clampValue.toFixed(2)})
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={controls.clampValue}
              onChange={(e) => patch({ clampValue: Number(e.target.value) })}
              className="mb-4 w-full accent-emerald-active"
            />
          </>
        ) : (
          <p className="mb-3 text-xs text-slate-500">
            Clamp controls appear after the first condition resolves.
          </p>
        )}
        <div className="mb-2 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-slate-500">
          Loss-of-function knockouts
        </div>
        <div className="max-h-36 space-y-2 overflow-y-auto">
          {nodes.length === 0 ? (
            <p className="text-xs text-slate-500">Pathway nodes load after search.</p>
          ) : (
            nodes
              .filter((n) => n !== controls.clampNode)
              .map((n) => {
                const checked = controls.knockouts.includes(n)
                return (
                  <label
                    key={n}
                    className="flex cursor-pointer items-center gap-2 text-sm text-slate-300"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        const knockouts = checked
                          ? controls.knockouts.filter((x) => x !== n)
                          : [...controls.knockouts, n]
                        patch({ knockouts })
                      }}
                      className="accent-coral-action"
                    />
                    <span className="font-medium text-slate-200">{n}</span>
                  </label>
                )
              })
          )}
        </div>
      </GlassCard>

      <GlassCard title="Pharmacology" hint="PK/PD occupancy · C / (C + Kᵢ)">
        <label className="mb-3 flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={controls.drugEnabled}
            onChange={(e) => patch({ drugEnabled: e.target.checked })}
            className="accent-coral-action"
          />
          Apply targeted inhibitor
        </label>
        <label className="mb-1 block text-xs text-slate-400">Drug target</label>
        <select
          disabled={!controls.drugEnabled}
          className="mb-3 w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm disabled:opacity-40"
          value={controls.drugTarget}
          onChange={(e) => patch({ drugTarget: e.target.value })}
        >
          {(nodes.length ? nodes : [controls.drugTarget]).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <label className="mb-1 block text-xs text-slate-400">
          Concentration C ({controls.cDrug.toFixed(1)} µM)
        </label>
        <input
          type="range"
          min={0}
          max={50}
          step={0.5}
          disabled={!controls.drugEnabled}
          value={controls.cDrug}
          onChange={(e) => patch({ cDrug: Number(e.target.value) })}
          className="mb-3 w-full accent-coral-action disabled:opacity-40"
        />
        <label className="mb-1 block text-xs text-slate-400">
          Inhibition constant Kᵢ ({controls.ki.toFixed(1)} µM)
        </label>
        <input
          type="range"
          min={0.1}
          max={20}
          step={0.1}
          disabled={!controls.drugEnabled}
          value={controls.ki}
          onChange={(e) => patch({ ki: Number(e.target.value) })}
          className="w-full accent-coral-action disabled:opacity-40"
        />
      </GlassCard>

      <GlassCard title="Causal Query" hint="Pathway causal chains · driver → readout">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-xs text-slate-400">Driver</label>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-2 py-2 text-sm"
              value={controls.sourceNode}
              onChange={(e) => patch({ sourceNode: e.target.value })}
            >
              {(nodes.length ? nodes : [controls.sourceNode]).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">Readout</label>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-2 py-2 text-sm"
              value={controls.targetNode}
              onChange={(e) => patch({ targetNode: e.target.value })}
            >
              {(nodes.length ? nodes : [controls.targetNode]).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      </GlassCard>

      <button
        type="button"
        disabled={!canRun}
        onClick={onRun}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-[#FF6B6B] to-coral-action px-4 py-3 text-sm font-bold text-white shadow-[0_8px_24px_rgba(255,82,82,0.28)] transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? <FlaskConical className="h-4 w-4 animate-pulse" /> : <Play className="h-4 w-4" />}
        {busy ? 'Resolving & integrating…' : 'Search & Simulate'}
      </button>
    </aside>
  )
}
