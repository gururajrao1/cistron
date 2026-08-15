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
  className?: string
}

/**
 * Executive phenotype summary — 3 plain-English sentences + optional gauges.
 */
export function PhenotypeSummaryCard({ summary, showGauges = true, className }: Props) {
  return (
    <div
      className={clsx(
        'rounded-lg border border-cyan-flux/25 bg-cyan-950/15 px-3 py-2.5',
        className,
      )}
    >
      <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-cyan-flux">
        <Activity className="h-3.5 w-3.5" />
        Phenotype summary
      </div>
      <ol className="mb-3 space-y-1.5">
        {summary.sentences.map((s, i) => (
          <li
            key={i}
            className={clsx(
              'rounded-md border px-2.5 py-1.5 text-[12px] leading-snug',
              TONE[s.tone],
            )}
          >
            {s.text}
          </li>
        ))}
      </ol>
      {showGauges ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <BatteryGauge percentage={summary.atpPercent} />
          <AcidMeter level={summary.lactateLevel} />
          {summary.blissScore != null ? (
            <SynergyDial score={summary.blissScore} />
          ) : (
            <div className="flex items-center justify-center rounded-md border border-dashed border-vcl-border px-2 text-[10px] text-vcl-dim">
              Synergy dial after Dual Screen / SL pairs
            </div>
          )}
          <CompartmentCellGlyph cyto={summary.cyto} nuc={summary.nuc} />
        </div>
      ) : null}
    </div>
  )
}
