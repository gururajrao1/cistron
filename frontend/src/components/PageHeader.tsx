import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { clsx } from 'clsx'

/** Consistent page title block for non-Studio workspaces. */
export function PageHeader({
  code,
  title,
  description,
  actions,
  className,
}: {
  code?: string
  title: string
  description?: string
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      className={clsx(
        'flex flex-wrap items-end justify-between gap-3 border-b border-cyan-flux/25 pb-4',
        className,
      )}
    >
      <div className="min-w-0 max-w-2xl">
        {code ? <p className="lab-meta">{code}</p> : null}
        <h1 className="font-display mt-1 text-xl font-semibold tracking-tight text-vcl-text md:text-[1.65rem]">
          {title}
        </h1>
        {description ? (
          <p className="mt-1.5 text-[13px] leading-relaxed text-vcl-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/** Shared action button — phosphor / cyan CTAs. */
export function VclButton({
  children,
  variant = 'primary',
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
}) {
  const styles = {
    primary:
      'border-phosphor/40 bg-[#1a2a0a] text-phosphor hover:brightness-110',
    secondary:
      'border-cyan-flux/40 bg-[#0a1f28] text-cyan-flux hover:brightness-110',
    ghost:
      'border-vcl-border bg-transparent text-vcl-text hover:border-vcl-border-strong hover:bg-vcl-raised',
    danger:
      'border-coral-action/45 bg-[#3A1418] text-[#F87171] hover:brightness-110',
  }
  return (
    <button
      type="button"
      className={clsx(
        'vcl-focus-ring inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-semibold transition active:scale-[0.98] disabled:opacity-40',
        styles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}
