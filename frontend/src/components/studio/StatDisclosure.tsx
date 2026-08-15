import { useEffect, useState, type ReactNode } from 'react'
import { clsx } from 'clsx'
import { ChevronDown, ChevronRight, Lightbulb } from 'lucide-react'
import { useViewMode, defaultShowNumbers } from '../../layout/viewModeGates'

type Props = {
  /** Plain-English takeaway (always visible). */
  headline: string
  /** Optional lab / wet-lab next step. */
  labHint?: string
  /** Raw tables, heatmaps, score grids — progressive disclosure. */
  children?: ReactNode
  /** Force numbers open (overrides systems default). */
  forceShowNumbers?: boolean
  className?: string
  /** Label on the disclosure toggle. */
  numbersLabel?: string
}

/**
 * App-wide progressive disclosure: insight first, raw stats behind a toggle.
 * Systems Math opens numbers by default; Biologist keeps them closed.
 */
export function StatDisclosure({
  headline,
  labHint,
  children,
  forceShowNumbers,
  className,
  numbersLabel = 'Show numbers',
}: Props) {
  const mode = useViewMode()
  const [open, setOpen] = useState(
    () => forceShowNumbers ?? defaultShowNumbers(mode),
  )

  useEffect(() => {
    setOpen(forceShowNumbers ?? defaultShowNumbers(mode))
  }, [mode, forceShowNumbers])

  return (
    <div className={clsx('flex min-h-0 flex-col gap-2', className)}>
      <div className="shrink-0 rounded-lg border border-cyan-flux/25 bg-cyan-950/20 px-2.5 py-2">
        <div className="mb-1 flex items-start gap-1.5">
          <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-flux" />
          <p className="text-[12px] leading-snug text-vcl-text">{headline}</p>
        </div>
        {labHint ? (
          <p className="mb-1.5 pl-5 text-[10.5px] leading-relaxed text-vcl-muted">
            <span className="font-semibold text-amber-kinase/90">Next: </span>
            {labHint}
          </p>
        ) : null}
        {children ? (
          <div className="flex justify-end pl-5">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-0.5 rounded border border-vcl-border bg-vcl-surface px-1.5 py-0.5 font-mono text-[10px] text-vcl-dim hover:text-vcl-text"
            >
              {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              {open ? 'Hide numbers' : numbersLabel}
            </button>
          </div>
        ) : null}
      </div>
      {children && open ? <div className="min-h-0 flex-1 overflow-auto">{children}</div> : null}
      {children && !open ? (
        <p className="shrink-0 px-1 text-[10px] text-vcl-dim">
          Raw scores stay hidden until you need them — switch to Systems Math to expand by default.
        </p>
      ) : null}
    </div>
  )
}
