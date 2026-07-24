import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Ban, Box, RotateCcw, Search, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { GlassCard } from '../GlassCard'
import { GeneBadge, MetaLabel } from '../ui'
import { useLab } from '../../lab/LabContext'

function baselineFor(
  symbol: string,
  omicsClamps: Record<string, number>,
): number | null {
  if (symbol in omicsClamps) return omicsClamps[symbol]!
  const upper = symbol.toUpperCase()
  if (upper in omicsClamps) return omicsClamps[upper]!
  return null
}

export function PerturbationPanel() {
  const lab = useLab()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [drafts, setDrafts] = useState<Record<string, number>>({})

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase()
    const list = lab.nodes
    if (!q) return list
    return list.filter((n) => n.toUpperCase().includes(q))
  }, [lab.nodes, query])

  const activeEntries = useMemo(
    () =>
      Object.entries(lab.perturbations)
        .sort(([a], [b]) => a.localeCompare(b)),
    [lab.perturbations],
  )

  const valueOf = (sym: string) => {
    if (sym in drafts) return drafts[sym]!
    if (sym in lab.perturbations) return lab.perturbations[sym]!
    return baselineFor(sym, lab.omicsClamps) ?? 0.5
  }

  const isPerturbed = (sym: string) => sym in lab.perturbations

  return (
    <GlassCard
      title="Target perturbations"
      hint="CRISPR KO · dose titration · reset to baseline y₀"
    >
      <div className="mb-3 space-y-2">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search proteins…"
            className="w-full rounded-lg border border-slate-800 bg-obsidian/80 py-2 pl-8 pr-2.5 text-[12px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-emerald-500/40"
          />
        </label>

        {activeEntries.length > 0 ? (
          <div className="rounded-lg border border-coral-action/25 bg-coral-action/5 px-2.5 py-2">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <MetaLabel className="!text-coral-action">Active targets</MetaLabel>
              <button
                type="button"
                disabled={lab.busy}
                onClick={() => {
                  setDrafts({})
                  lab.clearAllPerturbations()
                }}
                className="inline-flex items-center gap-1 rounded-md border border-slate-700/80 bg-slate-900/60 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300 hover:border-coral-action/40 hover:text-red-200 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
                Clear all
              </button>
            </div>
            <ul className="flex flex-wrap gap-1.5">
              {activeEntries.map(([sym, val]) => (
                <li key={sym}>
                  <button
                    type="button"
                    disabled={lab.busy}
                    onClick={() => lab.clearPerturbation(sym)}
                    className="inline-flex items-center gap-1 rounded-full border border-coral-action/35 bg-obsidian/70 px-2 py-0.5 text-[10px] font-semibold text-red-100 hover:bg-coral-action/15 disabled:opacity-40"
                    title="Reset this target"
                  >
                    <GeneBadge name={sym} tone="coral" />
                    <span className="lab-mono">
                      {val <= 1e-6 ? 'KO' : `y=${val.toFixed(2)}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-[11px] leading-relaxed text-slate-500">
            No interactive targets yet. Knock out a node or drag a titration slider.
          </p>
        )}
      </div>

      <div className="max-h-[320px] space-y-2 overflow-y-auto pr-0.5">
        {filtered.length === 0 ? (
          <p className="text-[11px] text-slate-500">No nodes match “{query}”.</p>
        ) : (
          filtered.map((sym) => {
            const val = valueOf(sym)
            const ko = isPerturbed(sym) && val <= 1e-6
            const baseline = baselineFor(sym, lab.omicsClamps)
            return (
              <div
                key={sym}
                className={clsx(
                  'rounded-xl border px-2.5 py-2 transition',
                  isPerturbed(sym)
                    ? 'border-coral-action/35 bg-coral-action/[0.06]'
                    : 'border-slate-800/80 bg-obsidian/40',
                )}
              >
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <GeneBadge name={sym} tone={ko ? 'coral' : 'cyan'} />
                    {ko ? (
                      <span className="text-[10px] font-bold uppercase tracking-wide text-red-300">
                        🚫 KO
                      </span>
                    ) : isPerturbed(sym) ? (
                      <span className="lab-mono text-[10px] text-amber-200">
                        y={val.toFixed(2)}
                      </span>
                    ) : baseline != null ? (
                      <span className="lab-mono text-[10px] text-slate-500">
                        y₀={baseline.toFixed(2)}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      disabled={lab.busy}
                      onClick={() => {
                        setDrafts((d) => {
                          const next = { ...d }
                          delete next[sym]
                          return next
                        })
                        lab.setNodePerturbation(sym, 0)
                      }}
                      className={clsx(
                        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide disabled:opacity-40',
                        ko
                          ? 'border-coral-action/50 bg-coral-action/20 text-red-100'
                          : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:border-coral-action/40 hover:text-red-200',
                      )}
                    >
                      <Ban className="h-3 w-3" />
                      Knockout
                    </button>
                    <button
                      type="button"
                      disabled={lab.busy || !isPerturbed(sym)}
                      onClick={() => {
                        setDrafts((d) => {
                          const next = { ...d }
                          delete next[sym]
                          return next
                        })
                        lab.clearPerturbation(sym)
                      }}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/70 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300 hover:border-emerald-500/40 hover:text-emerald-200 disabled:opacity-40"
                    >
                      <RotateCcw className="h-3 w-3" />
                      Reset
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        navigate(`/biophysics?symbol=${encodeURIComponent(sym)}`)
                      }
                      className="inline-flex items-center gap-1 rounded-md border border-cyan-flux/35 bg-cyan-950/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-cyan-100 hover:bg-cyan-900/40"
                      title="Open full-page 3D structure"
                    >
                      <Box className="h-3 w-3" />
                      3D
                    </button>
                  </div>
                </div>
                <label className="block">
                  <div className="mb-1 flex justify-between text-[10px] text-slate-500">
                    <span>Titration</span>
                    <span className="lab-mono text-slate-400">{val.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={val}
                    disabled={lab.busy}
                    onChange={(e) => {
                      const next = Number(e.target.value)
                      setDrafts((d) => ({ ...d, [sym]: next }))
                    }}
                    onPointerUp={(e) => {
                      const next = Number((e.target as HTMLInputElement).value)
                      setDrafts((d) => {
                        const copy = { ...d }
                        delete copy[sym]
                        return copy
                      })
                      lab.setNodePerturbation(sym, next)
                    }}
                    className="w-full accent-coral-action disabled:opacity-40"
                  />
                  <div className="mt-0.5 flex justify-between text-[9px] uppercase tracking-wide text-slate-600">
                    <span>0 · KO</span>
                    <span>1 · full</span>
                  </div>
                </label>
              </div>
            )
          })
        )}
      </div>
    </GlassCard>
  )
}
