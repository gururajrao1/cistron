import { clsx } from 'clsx'

type Props = {
  /** Normalized lactate / acidity 0–1. */
  level: number
  label?: string
  className?: string
}

/** Extracellular acidification metaphor from lactate export. */
export function AcidMeter({ level, label = 'Lactate / acid load', className }: Props) {
  const v = Math.max(0, Math.min(1, level))
  const pct = v * 100
  const tip = `${label}: ${v.toFixed(3)} (${pct.toFixed(0)}% of scale)`

  return (
    <div className={clsx('flex flex-col gap-1', className)} title={tip}>
      <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-vcl-dim">
        <span>{label}</span>
        <span className="text-vcl-muted">{v.toFixed(2)}</span>
      </div>
      <div className="relative h-7 overflow-hidden rounded-md border border-vcl-border bg-obsidian">
        <div
          className="absolute inset-0 opacity-90"
          style={{
            background:
              'linear-gradient(90deg, #10B981 0%, #F59E0B 55%, #F43F5E 100%)',
          }}
        />
        <div
          className="absolute inset-y-0 right-0 bg-obsidian/90 transition-[left] duration-300"
          style={{ left: `${pct}%` }}
        />
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-vcl-text shadow-[0_0_6px_rgba(255,255,255,0.5)]"
          style={{ left: `calc(${pct}% - 1px)` }}
        />
      </div>
      <div className="flex justify-between font-mono text-[8px] text-vcl-dim">
        <span>neutral</span>
        <span>acidic</span>
      </div>
    </div>
  )
}
