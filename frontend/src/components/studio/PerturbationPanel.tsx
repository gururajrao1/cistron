import { useMemo, useState } from 'react'
import { Ban, RotateCcw } from 'lucide-react'
import { clsx } from 'clsx'
import { GlassCard } from '../GlassCard'
import { GeneBadge, MetaLabel } from '../ui'
import { useLab } from '../../lab/LabContext'
import type { ModelContext } from '../../api/types'
import { useViewMode } from '../../layout/viewModeGates'

function baselineFor(
  symbol: string,
  omicsClamps: Record<string, number>,
): number | null {
  if (symbol in omicsClamps) return omicsClamps[symbol]!
  const upper = symbol.toUpperCase()
  if (upper in omicsClamps) return omicsClamps[upper]!
  return null
}

function setContextField(
  lab: ReturnType<typeof useLab>,
  key: keyof ModelContext,
  value: string,
) {
  const next: ModelContext = { ...(lab.controls.modelContext ?? {}) }
  const trimmed = value.trim()
  if (trimmed) next[key] = trimmed
  else delete next[key]
  lab.patchControls({ modelContext: next })
}

function ModelContextFields() {
  const lab = useLab()
  const ctx = lab.controls.modelContext ?? {}
  const meta = lab.payload?.metadata as Record<string, unknown> | undefined
  const flags = Array.isArray(meta?.confounder_flags)
    ? meta.confounder_flags.map((f) => String(f))
    : []
  const fields: Array<{ key: keyof ModelContext; label: string; hint: string }> = [
    { key: 'cell_line', label: 'Cell line', hint: 'e.g. HUVEC' },
    { key: 'tissue', label: 'Tissue', hint: 'e.g. endothelium' },
    { key: 'passage', label: 'Passage', hint: 'e.g. p5' },
    { key: 'batch_note', label: 'Batch note', hint: 'e.g. lot 7' },
  ]
  return (
    <div className="border-b border-vcl-border/70 px-2.5 py-2">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-vcl-dim">
        Model context
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {fields.map(({ key, label, hint }) => (
          <label key={key} className="block">
            <span className="mb-0.5 block text-[9.5px] text-vcl-dim">{label}</span>
            <input
              type="text"
              value={ctx[key] ?? ''}
              placeholder={hint}
              disabled={lab.busy}
              onChange={(e) => setContextField(lab, key, e.target.value)}
              className="w-full rounded border border-vcl-border bg-obsidian/40 px-1.5 py-1 font-mono text-[10.5px] text-vcl-text placeholder:text-vcl-dim/60 disabled:opacity-40"
            />
          </label>
        ))}
      </div>
      {flags.length > 0 ? (
        <ul className="mt-1.5 space-y-0.5">
          {flags.map((f) => (
            <li
              key={f}
              className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200"
            >
              {f}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function PerturbationPanel({
  variant = 'card',
}: {
  variant?: 'card' | 'dock'
}) {
  const lab = useLab()
  const mode = useViewMode()
  const [drafts, setDrafts] = useState<Record<string, number>>({})

  const nodes = useMemo(() => {
    const list = lab.nodes
    // Prefer perturbed + focus nodes first for dock density
    const pert = new Set(Object.keys(lab.perturbations).map((s) => s.toUpperCase()))
    return [...list].sort((a, b) => {
      const ap = pert.has(a.toUpperCase()) ? 0 : 1
      const bp = pert.has(b.toUpperCase()) ? 0 : 1
      if (ap !== bp) return ap - bp
      return a.localeCompare(b)
    })
  }, [lab.nodes, lab.perturbations])

  const valueOf = (sym: string) => {
    if (sym in drafts) return drafts[sym]!
    if (sym in lab.perturbations) return lab.perturbations[sym]!
    return baselineFor(sym, lab.omicsClamps) ?? 0.5
  }

  const isPerturbed = (sym: string) => sym in lab.perturbations

  const rows = (
    <div className={clsx(variant === 'dock' ? 'space-y-0' : 'max-h-[320px] space-y-2 overflow-y-auto pr-0.5')}>
      <ModelContextFields />
      {nodes.length === 0 ? (
        <p className="px-3 py-4 text-[11px] text-vcl-dim">No graph nodes yet — run a simulation.</p>
      ) : (
        nodes.map((sym) => {
          const val = valueOf(sym)
          const dosePct = Math.round(val * 100)
          const ko = isPerturbed(sym) && val <= 1e-6
          const baseline = baselineFor(sym, lab.omicsClamps)
          return (
            <div
              key={sym}
              className={clsx(
                variant === 'dock'
                  ? 'border-b border-vcl-border/70 px-2.5 py-2'
                  : 'rounded-xl border px-2.5 py-2',
                variant === 'dock'
                  ? isPerturbed(sym)
                    ? 'bg-coral-action/[0.04]'
                    : 'bg-transparent'
                  : isPerturbed(sym)
                    ? 'border-coral-action/35 bg-coral-action/[0.06]'
                    : 'border-vcl-border bg-obsidian/40',
              )}
            >
              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-mono text-[11.5px] font-semibold text-vcl-text">{sym}</div>
                  <div className="text-[10px] text-vcl-dim">
                    {ko
                      ? 'CRISPR knockout'
                      : isPerturbed(sym)
                        ? mode === 'biologist'
                          ? dosePct < 40
                            ? 'Low dose'
                            : dosePct < 90
                              ? 'Moderate dose'
                              : 'High / near WT'
                          : `Dose ${dosePct}%`
                        : baseline != null
                          ? mode === 'biologist'
                            ? 'Omics baseline set'
                            : `Baseline y₀=${baseline.toFixed(2)}`
                          : 'Wild-type activity'}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-1">
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
                      'inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9.5px] font-semibold uppercase tracking-wide disabled:opacity-40',
                      ko
                        ? 'border border-coral-action/50 bg-[#3A1418] text-[#F87171]'
                        : 'border border-vcl-border bg-vcl-raised text-vcl-muted hover:border-coral-action/40 hover:text-red-200',
                    )}
                  >
                    <Ban className="h-3 w-3" />
                    CRISPR KO
                  </button>
                  {isPerturbed(sym) ? (
                    <button
                      type="button"
                      disabled={lab.busy}
                      onClick={() => {
                        setDrafts((d) => {
                          const next = { ...d }
                          delete next[sym]
                          return next
                        })
                        lab.clearPerturbation(sym)
                      }}
                      className="inline-flex items-center gap-1 rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9.5px] font-semibold uppercase tracking-wide text-vcl-muted hover:text-vcl-text disabled:opacity-40"
                    >
                      <RotateCcw className="h-3 w-3" />
                    </button>
                  ) : null}
                </div>
              </div>
              <label className="block">
                <div className="mb-1 flex justify-between text-[10px] text-vcl-dim">
                  <span>Dose</span>
                  <span className="lab-mono text-vcl-muted">
                    {mode === 'biologist'
                      ? dosePct < 40
                        ? 'Low'
                        : dosePct < 90
                          ? 'Med'
                          : 'High'
                      : `${dosePct}%`}
                  </span>
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
                  className="w-full accent-emerald-active disabled:opacity-40"
                />
                <div className="mt-0.5 flex justify-between text-[9px] uppercase tracking-wide text-vcl-dim">
                  <span>0 · KO</span>
                  <span>{mode === 'biologist' ? 'WT' : '100 · full'}</span>
                  {mode === 'biologist' ? null : <span>200%</span>}
                </div>
              </label>
            </div>
          )
        })
      )}
    </div>
  )

  if (variant === 'dock') {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex h-8 shrink-0 items-center justify-between border-b border-vcl-border px-2.5">
          <span className="lab-meta !text-vcl-muted">Target perturbations</span>
          <button
            type="button"
            disabled={lab.busy || Object.keys(lab.perturbations).length === 0}
            onClick={() => {
              setDrafts({})
              lab.clearAllPerturbations()
            }}
            className="font-mono text-[10px] font-semibold uppercase tracking-wide text-vcl-dim hover:text-coral-action disabled:opacity-40"
          >
            reset
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{rows}</div>
      </div>
    )
  }

  return (
    <GlassCard
      title="Target perturbations"
      hint="CRISPR KO · dose titration · reset to baseline y₀"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <MetaLabel>Active</MetaLabel>
        <button
          type="button"
          disabled={lab.busy || Object.keys(lab.perturbations).length === 0}
          onClick={() => {
            setDrafts({})
            lab.clearAllPerturbations()
          }}
          className="font-mono text-[10px] uppercase text-slate-400 hover:text-red-200 disabled:opacity-40"
        >
          Clear all
        </button>
      </div>
      {Object.keys(lab.perturbations).length === 0 ? (
        <p className="mb-2 text-[11px] text-slate-500">
          No interactive targets yet. Knock out a node or drag a titration slider.
        </p>
      ) : (
        <ul className="mb-2 flex flex-wrap gap-1.5">
          {Object.entries(lab.perturbations).map(([sym, val]) => (
            <li key={sym}>
              <GeneBadge name={sym} tone={val <= 1e-6 ? 'coral' : 'amber'} />
            </li>
          ))}
        </ul>
      )}
      {rows}
    </GlassCard>
  )
}
