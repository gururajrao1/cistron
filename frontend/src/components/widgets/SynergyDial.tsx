import { clsx } from 'clsx'

type Props = {
  /** Bliss excess-style score; negative = antagonistic, positive = synergistic. */
  score: number
  label?: string
  className?: string
}

/**
 * Drug synergy dial — Antagonistic (red) → Additive (gray) → Synergistic (green).
 */
export function SynergyDial({ score, label = 'Drug synergy', className }: Props) {
  const clamped = Math.max(-1, Math.min(1, score))
  // Map -1..1 → 0..180 degrees (left to right arc)
  const angle = ((clamped + 1) / 2) * 180
  const verdict =
    clamped > 0.1 ? 'Synergistic' : clamped < -0.1 ? 'Antagonistic' : 'Additive'
  const tip = `${label}: Bliss≈${clamped.toFixed(3)} (${verdict})`

  return (
    <div className={clsx('flex flex-col gap-1', className)} title={tip}>
      <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-vcl-dim">
        <span>{label}</span>
        <span
          className={clsx(
            'normal-case tracking-normal',
            clamped > 0.1
              ? 'text-emerald-active'
              : clamped < -0.1
                ? 'text-coral-action'
                : 'text-vcl-muted',
          )}
        >
          {verdict}
        </span>
      </div>
      <svg viewBox="0 0 120 70" className="h-14 w-full" aria-hidden>
        <defs>
          <linearGradient id="synergyArc" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#F43F5E" />
            <stop offset="50%" stopColor="#64748B" />
            <stop offset="100%" stopColor="#10B981" />
          </linearGradient>
        </defs>
        <path
          d="M 10 60 A 50 50 0 0 1 110 60"
          fill="none"
          stroke="url(#synergyArc)"
          strokeWidth="8"
          strokeLinecap="round"
          opacity="0.85"
        />
        <g transform={`rotate(${angle - 90} 60 60)`}>
          <line
            x1="60"
            y1="60"
            x2="60"
            y2="18"
            stroke="#E8F1F8"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <circle cx="60" cy="60" r="4" fill="#E8F1F8" />
        </g>
        <text x="8" y="68" fill="#7C8DA3" fontSize="7" fontFamily="monospace">
          antag.
        </text>
        <text x="88" y="68" fill="#7C8DA3" fontSize="7" fontFamily="monospace">
          syn.
        </text>
      </svg>
      <div className="text-center font-mono text-[10px] text-vcl-soft">
        S = {clamped.toFixed(2)}
      </div>
    </div>
  )
}
