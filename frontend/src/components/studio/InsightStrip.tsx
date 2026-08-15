import { useState, type ReactNode } from 'react'
import { clsx } from 'clsx'
import { ChevronDown, ChevronRight, FlaskConical, Lightbulb } from 'lucide-react'
import type { DockInsight, InsightDelta } from '../../engine/insightRules'

function DeltaBadge({ d }: { d: InsightDelta }) {
  const tone =
    d.direction === 'up'
      ? 'border-emerald-active/40 bg-emerald-active/10 text-emerald-active'
      : d.direction === 'down'
        ? 'border-coral-action/40 bg-coral-action/10 text-coral-action'
        : 'border-vcl-border bg-vcl-surface text-vcl-muted'

  const arrow = d.direction === 'up' ? '↑' : d.direction === 'down' ? '↓' : '→'
  const showPct = Math.abs(d.pct) > 0.05 || d.direction !== 'flat'
  const pctLabel =
    d.label.toLowerCase().includes('fraction') && d.detail?.includes('%')
      ? d.detail
      : showPct
        ? `${arrow} ${d.pct >= 0 ? '+' : ''}${d.pct.toFixed(0)}%`
        : d.detail ?? '—'

  return (
    <span
      className={clsx(
        'inline-flex max-w-full items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] font-semibold',
        tone,
      )}
      title={d.detail}
    >
      <span className="truncate text-vcl-dim">{d.label}</span>
      <span className="whitespace-nowrap">{pctLabel}</span>
    </span>
  )
}

type Props = {
  insight: DockInsight
  /** Raw numbers / tables / charts behind progressive disclosure. */
  children?: ReactNode
  /** Default: hide advanced numbers. */
  defaultShowNumbers?: boolean
  className?: string
}

/**
 * Wet-lab Insight strip — headline + Δ badges + lab hint; numbers optional.
 */
export function InsightStrip({
  insight,
  children,
  defaultShowNumbers = false,
  className,
}: Props) {
  const [showNumbers, setShowNumbers] = useState(defaultShowNumbers)

  return (
    <div className={clsx('flex h-full min-h-0 flex-col gap-2 overflow-hidden', className)}>
      <div className="shrink-0 rounded-lg border border-cyan-flux/25 bg-cyan-950/20 px-2.5 py-2">
        <div className="mb-1 flex items-start gap-1.5">
          <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-flux" />
          <p className="text-[12px] leading-snug text-vcl-text">{insight.headline}</p>
        </div>
        {insight.deltas.length ? (
          <div className="mb-1.5 flex flex-wrap gap-1.5 pl-5">
            {insight.deltas.map((d) => (
              <DeltaBadge key={`${d.label}-${d.pct}`} d={d} />
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap items-start gap-2 pl-5">
          <FlaskConical className="mt-0.5 h-3 w-3 shrink-0 text-amber-kinase" />
          <p className="min-w-0 flex-1 text-[10.5px] leading-relaxed text-vcl-muted">
            <span className="font-semibold text-amber-kinase/90">Lab next step: </span>
            {insight.labHint}
          </p>
          {children ? (
            <button
              type="button"
              onClick={() => setShowNumbers((v) => !v)}
              className="inline-flex shrink-0 items-center gap-0.5 rounded border border-vcl-border bg-vcl-surface px-1.5 py-0.5 font-mono text-[10px] text-vcl-dim hover:text-vcl-text"
            >
              {showNumbers ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {showNumbers ? 'Hide numbers' : 'Show numbers'}
            </button>
          ) : null}
        </div>
      </div>
      {children && showNumbers ? (
        <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
      ) : null}
      {children && !showNumbers ? (
        <p className="shrink-0 px-1 text-[10px] text-vcl-dim">
          Raw series and tables are behind Show numbers — insight first.
        </p>
      ) : null}
    </div>
  )
}
