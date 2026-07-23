import { useEffect, useMemo, useState } from 'react'
import { Activity, ArrowRight, Loader2, Sparkles, Zap } from 'lucide-react'
import type { ScientistReasoning } from '../api/types'
import { GeneBadge } from './ui'

function formatDelta(v: number): string {
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(3)}`
}

function sentimentLabel(s: string): string {
  if (s === 'up') return 'Activating'
  if (s === 'down') return 'Attenuating'
  if (s === 'mixed') return 'Mixed'
  return 'Steady'
}

/** Soft-highlight gene symbols and math tokens inside the brief. */
function BriefText({ text, className }: { text: string; className?: string }) {
  const parts = useMemo(() => {
    const re =
      /(\b[A-Z][A-Z0-9_]{1,14}\b|Σy₆₀|Σy|Δy₆₀|Δy|Δα|αᵢⱼ|yᵢ\(t\)|y₆₀)/g
    const out: Array<{ t: string; kind: 'plain' | 'gene' | 'math' }> = []
    let last = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push({ t: text.slice(last, m.index), kind: 'plain' })
      const token = m[0]
      const isMath = /[ΣΔαy₆₀ᵢⱼ()]/.test(token) || token.startsWith('Σ') || token.startsWith('Δ')
      out.push({ t: token, kind: isMath ? 'math' : 'gene' })
      last = m.index + token.length
    }
    if (last < text.length) out.push({ t: text.slice(last), kind: 'plain' })
    return out
  }, [text])

  return (
    <p className={className}>
      {parts.map((p, i) => {
        if (p.kind === 'gene') {
          return (
            <span
              key={i}
              className="mx-0.5 inline-flex items-center rounded-full border border-emerald-800/50 bg-emerald-950/60 px-1.5 py-px font-mono text-[0.8em] font-semibold text-emerald-400"
            >
              {p.t}
            </span>
          )
        }
        if (p.kind === 'math') {
          return (
            <span key={i} className="font-mono text-sky-300/90">
              {p.t}
            </span>
          )
        }
        return <span key={i}>{p.t}</span>
      })}
    </p>
  )
}

export function ScientistPanel({
  scientist,
  loading,
  compact = false,
}: {
  scientist: ScientistReasoning | null
  loading?: boolean
  compact?: boolean
}) {
  const [pulse, setPulse] = useState(false)
  useEffect(() => {
    if (!scientist?.brief) return
    setPulse(true)
    const t = window.setTimeout(() => setPulse(false), 900)
    return () => window.clearTimeout(t)
  }, [scientist?.brief, scientist?.elapsed_ms])

  const sentiment = scientist?.sentiment ?? 'neutral'
  const accent =
    sentiment === 'up'
      ? {
          ring: 'border-emerald-500/45',
          glow: 'shadow-[0_0_28px_rgba(16,185,129,0.28)]',
          wash: 'from-emerald-500/18 via-emerald-500/5 to-transparent',
          icon: 'text-emerald-active',
          pill: 'border-emerald-500/35 bg-emerald-500/15 text-emerald-200',
          bar: 'bg-gradient-to-r from-emerald-400 via-teal-400 to-sky-400',
        }
      : sentiment === 'down'
        ? {
            ring: 'border-coral-action/45',
            glow: 'shadow-[0_0_28px_rgba(255,82,82,0.28)]',
            wash: 'from-coral-action/16 via-coral-action/5 to-transparent',
            icon: 'text-coral-action',
            pill: 'border-coral-action/35 bg-coral-action/15 text-red-200',
            bar: 'bg-gradient-to-r from-coral-action via-orange-400 to-amber-300',
          }
        : sentiment === 'mixed'
          ? {
              ring: 'border-amber-400/40',
              glow: 'shadow-[0_0_28px_rgba(251,191,36,0.22)]',
              wash: 'from-amber-400/14 via-amber-400/4 to-transparent',
              icon: 'text-amber-300',
              pill: 'border-amber-400/35 bg-amber-400/12 text-amber-100',
              bar: 'bg-gradient-to-r from-amber-300 via-emerald-400 to-sky-400',
            }
          : {
              ring: 'border-slate-700/90',
              glow: 'shadow-[0_0_20px_rgba(16,185,129,0.12)]',
              wash: 'from-emerald-500/10 via-sky-500/5 to-transparent',
              icon: 'text-emerald-active',
              pill: 'border-slate-600/60 bg-slate-800/60 text-slate-300',
              bar: 'bg-gradient-to-r from-emerald-500/70 via-sky-500/50 to-transparent',
            }

  const deltas = Object.entries(scientist?.top_node_deltas ?? {}).slice(0, 4)
  const reroutes = Object.entries(scientist?.attention_reroutes ?? {}).slice(0, 2)

  return (
    <div
      className={`lab-glass relative overflow-hidden rounded-2xl transition-shadow duration-500 ${accent.ring} ${
        pulse ? accent.glow : ''
      }`}
    >
      <div className={`pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b ${accent.wash}`} />
      <div className={`absolute inset-x-0 top-0 h-px ${accent.bar}`} />

      <div className={`relative ${compact ? 'p-3' : 'p-3.5'}`}>
        <div className="mb-2.5 flex items-center gap-2.5">
          <div
            className={`flex h-8 w-8 items-center justify-center rounded-xl border border-white/5 bg-slate-900/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] ${accent.icon}`}
          >
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <div className="text-sm font-extrabold tracking-tight text-slate-50">
                AI Scientist
              </div>
              {scientist ? (
                <span
                  className={`rounded-full border px-1.5 py-0.5 text-[0.58rem] font-semibold uppercase tracking-[0.06em] ${accent.pill}`}
                >
                  {sentimentLabel(sentiment)}
                </span>
              ) : null}
            </div>
            {scientist?.perturbation_summary ? (
              <div className="truncate text-[0.65rem] text-slate-500">
                {scientist.perturbation_summary}
              </div>
            ) : null}
          </div>
          {scientist ? (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-700/80 bg-slate-900/70 px-1.5 py-1 font-mono text-[0.62rem] text-slate-400">
              <Zap className="h-3 w-3 text-emerald-400/80" />
              {scientist.elapsed_ms.toFixed(1)} ms
            </span>
          ) : null}
        </div>

        {scientist?.brief ? (
          <>
            <BriefText
              text={scientist.brief}
              className={`leading-relaxed text-slate-200/95 ${compact ? 'text-xs' : 'text-[0.8125rem]'}`}
            />

            {(deltas.length > 0 || reroutes.length > 0) && !compact ? (
              <div className="mt-3 space-y-2 border-t border-slate-800/80 pt-3">
                {deltas.length ? (
                  <div>
                    <div className="mb-1.5 flex items-center gap-1.5 text-[0.62rem] font-semibold uppercase tracking-[0.08em] text-slate-500">
                      <Activity className="h-3 w-3 text-emerald-400/70" />
                      Top Δy
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {deltas.map(([n, d]) => (
                        <span
                          key={n}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800/80 bg-obsidian/50 px-1.5 py-1"
                        >
                          <GeneBadge name={n} tone={d >= 0 ? 'emerald' : 'coral'} />
                          <span
                            className={`lab-mono text-[10px] ${
                              d >= 0 ? 'text-emerald-400' : 'text-coral-action'
                            }`}
                          >
                            {formatDelta(d)}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {reroutes.length ? (
                  <div>
                    <div className="mb-1.5 text-[0.62rem] font-semibold uppercase tracking-[0.08em] text-slate-500">
                      Attention reroutes
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {reroutes.map(([edge, da]) => {
                        const [src, tgt] = edge.split('->')
                        return (
                          <span
                            key={edge}
                            className="inline-flex items-center gap-1 rounded-lg border border-sky-500/20 bg-sky-500/5 px-2 py-1 font-mono text-[0.65rem] text-sky-100/90"
                          >
                            <span>{src}</span>
                            <ArrowRight className="h-3 w-3 text-sky-400/70" />
                            <span>{tgt ?? edge}</span>
                            <span className="text-sky-300/80">
                              Δα={formatDelta(da)}
                            </span>
                          </span>
                        )
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            {typeof scientist.total_flux_delta === 'number' && !compact ? (
              <div className="mt-2.5 font-mono text-[0.62rem] text-slate-500">
                ΣΔflux = {formatDelta(scientist.total_flux_delta)}
              </div>
            ) : null}
          </>
        ) : loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
            Synthesizing live reasoning…
          </div>
        ) : (
          <p className="text-sm text-slate-500">Run a condition to hear the AI Scientist.</p>
        )}
      </div>
    </div>
  )
}
