import { useNavigate } from 'react-router-dom'
import { FlaskConical, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'

type Props = {
  label?: string
  disabled?: boolean
  busy?: boolean
  className?: string
  /** Optional action before navigating (e.g. apply drug / build pathway). */
  onBeforeNavigate?: () => void | Promise<void>
}

/**
 * Consistent discovery → Studio CTA used across Pathways / Pharma / Omics / XAI / Combos.
 */
export function ApplyToStudioButton({
  label = 'Apply → Studio',
  disabled,
  busy,
  className,
  onBeforeNavigate,
}: Props) {
  const navigate = useNavigate()

  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={() => {
        void (async () => {
          await onBeforeNavigate?.()
          navigate('/studio')
        })()
      }}
      className={clsx(
        'inline-flex h-[28px] items-center gap-1.5 rounded-[5px] border border-emerald-active/45 bg-[#0d2818] px-3 text-[11px] font-semibold text-emerald-soft transition hover:border-emerald-active disabled:opacity-40',
        className,
      )}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <FlaskConical className="h-3.5 w-3.5" />
      )}
      {label}
    </button>
  )
}
