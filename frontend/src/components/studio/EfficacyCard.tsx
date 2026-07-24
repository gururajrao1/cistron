import { useMemo } from 'react'
import { Crosshair, Loader2 } from 'lucide-react'
import { GlassCard } from '../GlassCard'
import { GeneBadge, MetaLabel } from '../ui'
import { useLab } from '../../lab/LabContext'
import type { ScrubberPayload } from '../../api/types'

function terminalY(payload: ScrubberPayload, sym: string): number {
  const series = payload.nodes[sym]
  if (!series?.length) return 0
  return series[series.length - 1] ?? 0
}

export type EfficacyHit = {
  symbol: string
  pct: number
  delta: number
  yU: number
  yT: number
}

/** Rank downstream nodes by relative inhibition vs untreated baseline. */
export function rankInhibitionEfficacy(
  untreated: ScrubberPayload,
  treated: ScrubberPayload,
  exclude: Set<string>,
  topN = 5,
): EfficacyHit[] {
  const symbols = new Set([
    ...Object.keys(untreated.nodes),
    ...Object.keys(treated.nodes),
  ])
  const hits: EfficacyHit[] = []
  for (const sym of symbols) {
    if (exclude.has(sym) || exclude.has(sym.toUpperCase())) continue
    const yU = terminalY(untreated, sym)
    const yT = terminalY(treated, sym)
    const delta = yT - yU
    if (Math.abs(delta) < 0.01) continue
    const pct = yU > 1e-4 ? (delta / yU) * 100 : delta * 100
    hits.push({ symbol: sym, pct, delta, yU, yT })
  }
  return hits.sort((a, b) => a.pct - b.pct).slice(0, topN)
}

export function EfficacyCard() {
  const lab = useLab()
  const exclude = useMemo(
    () => new Set(Object.keys(lab.perturbations).map((s) => s.toUpperCase())),
    [lab.perturbations],
  )

  const hits = useMemo(() => {
    if (!lab.untreatedRun || !lab.treatedRun) return [] as EfficacyHit[]
    return rankInhibitionEfficacy(lab.untreatedRun, lab.treatedRun, exclude, 5)
  }, [lab.untreatedRun, lab.treatedRun, exclude])

  const pairs = lab.topologicalAnalysis?.synthetic_lethal_pairs ?? []
  const hasCompare = Boolean(lab.untreatedRun && lab.treatedRun)

  const summary =
    hits.length > 0
      ? hits
          .map((h) => `${h.symbol} (${h.pct >= 0 ? '+' : ''}${h.pct.toFixed(0)}%)`)
          .join(', ')
      : null

  return (
    <GlassCard
      title="Impact & synergy"
      hint="Untreated vs treated Δy₆₀ · dual-target SL screen"
    >
      <div className="space-y-3">
        <div>
          <MetaLabel className="mb-1">Inhibition efficacy</MetaLabel>
          {hasCompare && summary ? (
            <p className="text-[12px] leading-relaxed text-slate-200">
              <span className="font-semibold text-coral-action">Top downstream:</span>{' '}
              {hits.map((h, i) => (
                <span key={h.symbol}>
                  {i > 0 ? ', ' : null}
                  <GeneBadge
                    name={h.symbol}
                    tone={h.pct < -20 ? 'coral' : h.pct < 0 ? 'amber' : 'emerald'}
                    className="!align-middle"
                  />{' '}
                  <span
                    className={
                      h.pct < 0 ? 'lab-mono text-red-300' : 'lab-mono text-emerald-300'
                    }
                  >
                    ({h.pct >= 0 ? '+' : ''}
                    {h.pct.toFixed(0)}%)
                  </span>
                </span>
              ))}
            </p>
          ) : (
            <p className="text-[11px] leading-relaxed text-slate-500">
              Apply a knockout or titration to compare against the untreated baseline.
            </p>
          )}
        </div>

        <button
          type="button"
          disabled={!lab.engineLive || lab.busy}
          onClick={() => lab.runDualTargetScreen()}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-violet-hub/40 bg-violet-950/40 px-3 py-2.5 text-[12px] font-bold text-violet-100 shadow-[0_0_16px_rgba(139,92,246,0.15)] hover:bg-violet-900/50 disabled:opacity-40"
        >
          {lab.busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Crosshair className="h-3.5 w-3.5" />
          )}
          Synthetic Lethality / Dual Screen
        </button>

        {pairs.length > 0 ? (
          <div className="rounded-lg border border-violet-hub/30 bg-violet-950/30 px-2.5 py-2">
            <MetaLabel className="mb-1.5 !text-violet-300">SL pairs</MetaLabel>
            <ul className="space-y-1.5">
              {pairs.slice(0, 4).map((p) => {
                const pair = Array.isArray(p.pair) ? p.pair : []
                const key = pair.join('+') || String(p.synergy_score ?? Math.random())
                return (
                  <li key={key} className="text-[11px] leading-snug text-slate-300">
                    <span className="font-mono font-semibold text-violet-200">
                      {pair.join(' + ') || '—'}
                    </span>
                    <span className="lab-mono text-slate-500">
                      {' '}
                      · syn={Number(p.synergy_score ?? 0).toFixed(2)}
                    </span>
                    <div className="mt-0.5 text-[10px] text-slate-500">
                      {p.explanation || ''}
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : (
          <p className="text-[10px] leading-relaxed text-slate-600">
            Dual Screen runs a pairwise KO permutation (preferring your selected targets) and
            lists synthetic-lethal combinations here.
          </p>
        )}
      </div>
    </GlassCard>
  )
}
