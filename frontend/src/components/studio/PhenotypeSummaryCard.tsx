import { clsx } from 'clsx'
import { Activity } from 'lucide-react'
import type { PhenotypeSummary } from '../../engine/phenotypeSummary'

const TONE: Record<PhenotypeSummary['sentences'][0]['tone'], string> = {
  good: 'border-emerald-active/35 bg-emerald-active/10 text-emerald-active',
  warn: 'border-amber-kinase/40 bg-amber-kinase/10 text-amber-kinase',
  bad: 'border-coral-action/40 bg-coral-action/10 text-coral-action',
  neutral: 'border-vcl-border bg-vcl-surface text-vcl-soft',
}

type Props = {
  summary: PhenotypeSummary
  className?: string
}

/**
 * Compact phenotype strip — three condensed sentences in one horizontal band.
 * ATP / lactate gauges live in the Metabolic Flux (FBA) dock, not here.
 */
export function PhenotypeSummaryCard({ summary, className }: Props) {
  return (
    <div
      className={clsx(
        'overflow-hidden rounded-xl border border-cyan-flux/25 bg-cyan-950/15 px-4 py-2',
        className,
      )}
    >
      <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-cyan-flux">
        <Activity className="h-3 w-3" />
        Phenotype summary
      </div>
      <ol
        className={clsx(
          'grid grid-cols-3 gap-2',
          'sm:flex sm:flex-row sm:items-center sm:justify-between sm:gap-4',
        )}
      >
        {summary.sentences.map((s, i) => (
          <li
            key={i}
            className={clsx(
              'min-w-0 rounded-md border px-2 py-1.5 text-[11px] leading-snug',
              'line-clamp-3 sm:line-clamp-2 sm:flex-1',
              TONE[s.tone],
            )}
            title={s.text}
          >
            {s.text}
          </li>
        ))}
      </ol>
    </div>
  )
}
