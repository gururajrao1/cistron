import { useMemo } from 'react'
import { Crosshair, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { GlassCard } from '../GlassCard'
import { GeneBadge, MetaLabel } from '../ui'
import { useLab } from '../../lab/LabContext'
import type { ScrubberPayload } from '../../api/types'

function terminalY(payload: ScrubberPayload, sym: string): number {
  const series = payload.nodes[sym]
  if (!series?.length) return 0
  return series[series.length - 1] ?? 0
}

function deltaPct(untreated: ScrubberPayload, treated: ScrubberPayload, sym: string): number | null {
  const yU = terminalY(untreated, sym)
  const yT = terminalY(treated, sym)
  if (Math.abs(yU) < 1e-6 && Math.abs(yT) < 1e-6) return null
  if (Math.abs(yU) < 1e-4) return (yT - yU) * 100
  return ((yT - yU) / yU) * 100
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

function ImpactTile({
  label,
  pct,
}: {
  label: string
  pct: number | null
}) {
  return (
    <div className="rounded-md border border-vcl-border bg-vcl-surface px-2 py-1.5">
      <div className="lab-meta !normal-case !tracking-normal">{label}</div>
      <div
        className={clsx(
          'mt-0.5 font-mono text-[13px] font-semibold',
          pct == null
            ? 'text-vcl-dim'
            : pct < 0
              ? 'text-coral-action'
              : pct > 0
                ? 'text-emerald-active'
                : 'text-vcl-muted',
        )}
      >
        {pct == null ? '—' : `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`}
      </div>
    </div>
  )
}

export function EfficacyCard({
  variant = 'card',
}: {
  variant?: 'card' | 'dock'
}) {
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

  const impact = useMemo(() => {
    if (!lab.untreatedRun || !lab.treatedRun) {
      return { vegfa: null, hif: null, lac: null, ocr: null } as const
    }
    const u = lab.untreatedRun
    const t = lab.treatedRun
    return {
      vegfa: deltaPct(u, t, 'VEGFA'),
      hif: deltaPct(u, t, 'HIF1A'),
      lac: deltaPct(u, t, 'LDHA') ?? deltaPct(u, t, 'GLUT1'),
      ocr: deltaPct(u, t, 'PDK1') ?? deltaPct(u, t, 'MTOR'),
    }
  }, [lab.untreatedRun, lab.treatedRun])

  const applyPair = (a: string, b: string) => {
    lab.setNodePerturbation(a, 0, { resim: false })
    lab.setNodePerturbation(b, 0, { resim: true })
  }

  if (variant === 'dock') {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="border-b border-vcl-border px-2.5 py-2">
          <div className="lab-meta mb-1.5 !text-vcl-muted">Impact · vs baseline</div>
          <div className="grid grid-cols-2 gap-1.5">
            <ImpactTile label="Δ VEGFA" pct={impact.vegfa} />
            <ImpactTile label="Δ HIF1A" pct={impact.hif} />
            <ImpactTile label="Δ Lactate proxy" pct={impact.lac} />
            <ImpactTile label="Δ OCR proxy" pct={impact.ocr} />
          </div>
          {!hasCompare ? (
            <p className="mt-2 text-[10px] leading-relaxed text-vcl-dim">
              Apply a KO or titration to compare against the untreated baseline.
            </p>
          ) : null}
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-2.5 py-2">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="lab-meta !text-vcl-muted">Synergy · top dual KO</span>
            <button
              type="button"
              disabled={!lab.engineLive || lab.busy}
              onClick={() => lab.runDualTargetScreen()}
              className="inline-flex items-center gap-1 rounded border border-violet-hub/40 bg-violet-hub/10 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold uppercase tracking-wide text-violet-hub disabled:opacity-40"
            >
              {lab.busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Crosshair className="h-3 w-3" />}
              Screen
            </button>
          </div>
          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            {pairs.length === 0 ? (
              <li className="text-[10px] leading-relaxed text-vcl-dim">
                Run Dual Screen for synthetic-lethal pairs. Click a pair to apply both KOs.
              </li>
            ) : (
              pairs.slice(0, 6).map((p) => {
                const pair = Array.isArray(p.pair) ? p.pair : []
                const key = pair.join('+') || String(p.synergy_score ?? Math.random())
                return (
                  <li key={key}>
                    <button
                      type="button"
                      disabled={lab.busy || pair.length < 2}
                      onClick={() => {
                        if (pair[0] && pair[1]) applyPair(pair[0], pair[1])
                      }}
                      className="flex w-full items-center justify-between gap-2 rounded-md border border-vcl-border bg-vcl-surface px-2 py-1.5 text-left hover:border-violet-hub/40 disabled:opacity-40"
                    >
                      <span className="font-mono text-[11px] font-semibold text-vcl-text">
                        {pair.join(' + ') || '—'}
                      </span>
                      <span className="lab-mono text-[10px] text-violet-hub">
                        {Number(p.synergy_score ?? 0).toFixed(2)}
                      </span>
                    </button>
                  </li>
                )
              })
            )}
          </ul>
        </div>
      </div>
    )
  }

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
