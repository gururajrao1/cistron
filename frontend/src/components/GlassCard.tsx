import type { ReactNode } from 'react'
import { clsx } from 'clsx'

export function GlassCard({
  title,
  hint,
  children,
  className = '',
}: {
  title?: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('lab-glass min-w-0 rounded-2xl p-3.5', className)}>
      {title ? (
        <div className="mb-2.5 shrink-0">
          <h3 className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-100">
            {title}
          </h3>
          {hint ? <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{hint}</p> : null}
        </div>
      ) : null}
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </div>
  )
}
