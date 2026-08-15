import { clsx } from 'clsx'

type Props = {
  /** 0–100 energy fill (ATP proxy). */
  percentage: number
  label?: string
  className?: string
}

/** Metabolic energy metaphor — battery fill with exact % in tooltip. */
export function BatteryGauge({ percentage, label = 'ATP energy', className }: Props) {
  const pct = Math.max(0, Math.min(100, percentage))
  const tone =
    pct >= 55 ? 'bg-emerald-active' : pct >= 30 ? 'bg-amber-kinase' : 'bg-coral-action'

  return (
    <div
      className={clsx('flex flex-col gap-1', className)}
      title={`${label}: ${pct.toFixed(1)}%`}
    >
      <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-vcl-dim">
        <span>{label}</span>
        <span className="text-vcl-muted">{pct.toFixed(0)}%</span>
      </div>
      <div className="flex items-center gap-0.5">
        <div className="relative h-7 w-full overflow-hidden rounded-md border border-vcl-border bg-obsidian">
          <div
            className={clsx('absolute inset-y-0 left-0 transition-[width] duration-300', tone)}
            style={{ width: `${pct}%`, opacity: 0.85 }}
          />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,transparent_0%,rgba(255,255,255,0.06)_50%,transparent_100%)]" />
        </div>
        <div className="h-4 w-1.5 rounded-r-sm border border-vcl-border bg-vcl-raised" />
      </div>
    </div>
  )
}
