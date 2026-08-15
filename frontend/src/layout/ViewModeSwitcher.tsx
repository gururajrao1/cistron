import { clsx } from 'clsx'
import type { ViewMode } from '../../lab/viewMode'

const MODES: Array<{
  id: ViewMode
  label: string
  short: string
  title: string
}> = [
  {
    id: 'biologist',
    label: 'Biologist',
    short: 'Simple',
    title: 'Gauges, badges, and plain-English summaries only',
  },
  {
    id: 'researcher',
    label: 'Lab Researcher',
    short: 'Standard',
    title: 'Charts, spatial mesh, and drug controls (default)',
  },
  {
    id: 'systems',
    label: 'Systems Math',
    short: 'Deep',
    title: 'Raw ODE parameters, FBA vectors, and sensitivity derivatives',
  },
]

type Props = {
  mode: ViewMode
  onChange: (mode: ViewMode) => void
  className?: string
}

/**
 * 3-tier progressive-disclosure switcher — Linear × Benchling chrome.
 */
export function ViewModeSwitcher({ mode, onChange, className }: Props) {
  return (
    <div
      className={clsx(
        'inline-flex h-7 items-center rounded-md border border-vcl-border bg-obsidian p-0.5',
        className,
      )}
      role="radiogroup"
      aria-label="Workspace view depth"
    >
      {MODES.map((m) => {
        const active = mode === m.id
        return (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={active}
            title={m.title}
            onClick={() => onChange(m.id)}
            className={clsx(
              'vcl-focus-ring inline-flex h-full items-center gap-1 rounded-[5px] px-2 font-mono text-[10px] font-semibold transition',
              active
                ? 'bg-vcl-raised text-vcl-text shadow-[inset_0_0_0_1px_rgba(34,211,238,0.28)]'
                : 'text-vcl-muted hover:text-vcl-text',
            )}
          >
            <span className="hidden sm:inline">{m.label}</span>
            <span className="sm:hidden">{m.short}</span>
            <span
              className={clsx(
                'hidden text-[9px] font-medium md:inline',
                active ? 'text-cyan-flux/80' : 'text-vcl-dim',
              )}
            >
              {m.short}
            </span>
          </button>
        )
      })}
    </div>
  )
}
