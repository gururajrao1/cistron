import type { ReactNode } from 'react'
import { clsx } from 'clsx'

/** Compact uppercase metadata label used across the lab UI. */
export function MetaLabel({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={clsx('lab-meta', className)}>{children}</div>
}

/** Gene / protein symbol chip — Benchling-style monospace pill. */
export function GeneBadge({
  name,
  tone = 'emerald',
  className = '',
}: {
  name: string
  tone?: 'emerald' | 'cyan' | 'amber' | 'violet' | 'coral' | 'slate'
  className?: string
}) {
  const tones: Record<string, string> = {
    emerald:
      'bg-emerald-950/60 text-emerald-400 border-emerald-800/50',
    cyan: 'bg-cyan-950/60 text-cyan-300 border-cyan-800/50',
    amber: 'bg-amber-950/60 text-amber-300 border-amber-800/50',
    violet: 'bg-violet-950/60 text-violet-300 border-violet-800/50',
    coral: 'bg-rose-950/60 text-rose-300 border-rose-800/50',
    slate: 'bg-slate-900/80 text-slate-300 border-slate-700/70',
  }
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-xs font-semibold tracking-tight',
        tones[tone],
        className,
      )}
    >
      {name}
    </span>
  )
}

/** Live / offline / busy status pill for the header strip. */
export function StatusPill({
  live,
  busy,
  label,
}: {
  live: boolean
  busy?: boolean
  label: string
}) {
  return (
    <div
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider',
        live
          ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
          : 'border-slate-700 bg-slate-800/60 text-slate-400',
      )}
    >
      <span
        className={clsx(
          'h-1.5 w-1.5 rounded-full',
          busy
            ? 'animate-pulse bg-amber-kinase'
            : live
              ? 'bg-emerald-active glow-emerald'
              : 'bg-slate-500',
        )}
      />
      {label}
    </div>
  )
}

/** Compact header metric chip. */
export function MetricChip({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border border-slate-800/80 bg-slate-900/70 px-2.5 py-1 text-[10px] tracking-wide text-slate-400',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** Mini horizontal spark/bar for 5D feature magnitudes (0–1). */
export function SparkBar({
  value,
  max = 1,
  tone = 'emerald',
  className = '',
}: {
  value: number
  max?: number
  tone?: 'emerald' | 'cyan' | 'amber' | 'violet' | 'coral'
  className?: string
}) {
  const pct = Math.max(0, Math.min(100, (value / Math.max(max, 1e-9)) * 100))
  const fill: Record<string, string> = {
    emerald: 'bg-emerald-active',
    cyan: 'bg-cyan-flux',
    amber: 'bg-amber-kinase',
    violet: 'bg-violet-hub',
    coral: 'bg-coral-action',
  }
  return (
    <div
      className={clsx(
        'h-1.5 w-full overflow-hidden rounded-full bg-slate-800/90',
        className,
      )}
    >
      <div
        className={clsx('h-full rounded-full transition-[width] duration-200', fill[tone])}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

/** Dense diagnostic card shell for XAI / scientist observations. */
export function DiagnosticCard({
  title,
  hint,
  status,
  children,
  className = '',
}: {
  title: string
  hint?: string
  status?: 'up' | 'down' | 'mixed' | 'neutral' | 'live'
  children: ReactNode
  className?: string
}) {
  const ring =
    status === 'up' || status === 'live'
      ? 'border-emerald-500/35'
      : status === 'down'
        ? 'border-coral-action/35'
        : status === 'mixed'
          ? 'border-amber-kinase/35'
          : 'border-slate-800/80'
  const glow =
    status === 'up' || status === 'live'
      ? 'shadow-[0_0_24px_rgba(16,185,129,0.12)]'
      : status === 'down'
        ? 'shadow-[0_0_24px_rgba(239,68,68,0.1)]'
        : ''
  return (
    <div className={clsx('lab-glass rounded-2xl p-3.5', ring, glow, className)}>
      <div className="mb-2.5 flex items-start justify-between gap-2">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-100">
            {title}
          </div>
          {hint ? <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p> : null}
        </div>
        {status ? (
          <span
            className={clsx(
              'mt-0.5 h-2 w-2 shrink-0 rounded-full',
              status === 'up' || status === 'live'
                ? 'bg-emerald-active glow-emerald'
                : status === 'down'
                  ? 'bg-coral-action glow-coral'
                  : status === 'mixed'
                    ? 'bg-amber-kinase'
                    : 'bg-slate-500',
            )}
          />
        ) : null}
      </div>
      {children}
    </div>
  )
}
