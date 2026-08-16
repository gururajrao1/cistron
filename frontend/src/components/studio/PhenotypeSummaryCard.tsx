import { clsx } from 'clsx'
import { Activity } from 'lucide-react'
import type { PhenotypeSummary } from '../../engine/phenotypeSummary'
import {
  AcidMeter,
  BatteryGauge,
  CompartmentCellGlyph,
  SynergyDial,
} from '../widgets'

const TONE: Record<PhenotypeSummary['sentences'][0]['tone'], string> = {
  good: 'border-emerald-active/35 bg-emerald-active/10 text-emerald-active',
  warn: 'border-amber-kinase/40 bg-amber-kinase/10 text-amber-kinase',
  bad: 'border-coral-action/40 bg-coral-action/10 text-coral-action',
  neutral: 'border-vcl-border bg-vcl-surface text-vcl-soft',
}

type Props = {
  summary: PhenotypeSummary
  /** Show visual gauges (Biologist + Researcher). */
  showGauges?: boolean
  /** Single-row overview for Biologist — less chrome, more map. */
  compact?: boolean
  className?: string
}

/**
 * Executive phenotype summary — 3 plain-English sentences + optional gauges.
 */
export function PhenotypeSummaryCard({
  summary,
  showGauges = true,
  compact = false,
  className,
}: Props) {
  if (compact) {
    return (
      <div
        className={clsx(
          'overflow-hidden rounded-xl border border-cyan-flux/20 bg-cyan-950/10 px-3 py-2.5',
          className,
        )}
      >
        <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-cyan-flux">
          <Activity className="h-3.5 w-3.5" />
          Phenotype
        </div>
        {showGauges ? (
          <div className="mb-2.5 grid grid-cols-2 gap-x-4 gap-y-2 lg:grid-cols-4">
            <BatteryGauge percentage={summary.atpPercent} />
            <AcidMeter level={summary.lactateLevel} />
            {summary.blissScore != null ? (
              <SynergyDial score={summary.blissScore} />
            ) : (
              <div className="flex min-h-[2.75rem] items-center text-[10px] text-vcl-dim">
                Synergy after Dual Screen
              </div>
            )}
            <CompartmentCellGlyph cyto={summary.cyto} nuc={summary.nuc} />
          </div>
        ) : null}
        <ul className="space-y-1 border-t border-vcl-border/60 pt-2">
          {summary.sentences.map((s, i) => (
            <li
              key={i}
              className={clsx(
                'border-l-2 pl-2 text-[11.5px] leading-snug text-vcl-soft',
                s.tone === 'good'
                  ? 'border-emerald-active'
                  : s.tone === 'warn'
                    ? 'border-amber-kinase'
                    : s.tone === 'bad'
                      ? 'border-coral-action'
                      : 'border-vcl-border',
              )}
            >
              {s.text}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <div
      className={clsx(
        'overflow-hidden rounded-xl border border-cyan-flux/25 bg-cyan-950/15 px-3.5 py-3',
        className,
      )}
    >
      <div className="mb-2.5 flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-cyan-flux">
        <Activity className="h-3.5 w-3.5" />
        Phenotype summary
      </div>
      <ol className="mb-3 space-y-2">
        {summary.sentences.map((s, i) => (
          <li
            key={i}
            className={clsx(
              'rounded-md border px-2.5 py-2 text-[12px] leading-relaxed',
              TONE[s.tone],
            )}
          >
            {s.text}
          </li>
        ))}
      </ol>
      {showGauges ? (
        <div className="grid gap-4 overflow-hidden sm:grid-cols-2 xl:grid-cols-4">
          <BatteryGauge percentage={summary.atpPercent} />
          <AcidMeter level={summary.lactateLevel} />
          {summary.blissScore != null ? (
            <SynergyDial score={summary.blissScore} />
          ) : (
            <div className="flex min-h-[3.25rem] items-center justify-center rounded-md border border-dashed border-vcl-border px-2 text-[10px] text-vcl-dim">
              Synergy dial after Dual Screen / SL pairs
            </div>
          )}
          <CompartmentCellGlyph cyto={summary.cyto} nuc={summary.nuc} />
        </div>
      ) : null}
    </div>
  )
}
