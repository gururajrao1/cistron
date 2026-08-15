import { clsx } from 'clsx'
import { FlaskConical } from 'lucide-react'
import type { WetLabProtocol } from '../../engine/phenotypeSummary'

type Props = {
  protocol: WetLabProtocol
  className?: string
}

/**
 * Translates simulation timing / localization into physical wet-lab actions.
 */
export function WetLabProtocolCard({ protocol, className }: Props) {
  const rows = [
    { label: 'Assay timing', body: protocol.assayTiming },
    { label: 'Suggested targets', body: protocol.suggestedTargets },
    { label: 'Localization', body: protocol.localization },
  ]

  return (
    <div
      className={clsx(
        'rounded-lg border border-amber-kinase/30 bg-[#1a1408]/80 px-3 py-2.5',
        className,
      )}
    >
      <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-amber-kinase">
        <FlaskConical className="h-3.5 w-3.5" />
        Wet-lab protocol
      </div>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.label} className="text-[12px] leading-snug text-vcl-soft">
            <span className="font-mono text-[9px] font-semibold uppercase tracking-wider text-vcl-dim">
              {r.label}
            </span>
            <p className="mt-0.5">{r.body}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
