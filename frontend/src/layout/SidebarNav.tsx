import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { clsx } from 'clsx'

export type NavItem = {
  id: string
  path: string
  label: string
  shortLabel: string
  /** Compact rail code (mockup ST / PW / …) */
  code: string
  shortcut?: string
  comingSoon?: boolean
  phase?: number
}

export const PRIMARY_NAV: NavItem[] = [
  { id: 'studio', path: '/studio', label: 'Simulation Studio', shortLabel: 'Studio', code: 'ST', shortcut: '1' },
  { id: 'pathways', path: '/pathways', label: 'Disease Pathways', shortLabel: 'Pathways', code: 'PW', shortcut: '2' },
  { id: 'explorer', path: '/explorer', label: 'Network Builder', shortLabel: 'Explorer', code: 'EX', shortcut: '3' },
  { id: 'xai', path: '/xai', label: 'XAI & Prioritization', shortLabel: 'XAI', code: 'XA', shortcut: '4' },
  { id: 'pharmacology', path: '/pharmacology', label: 'Pharmacology Lab', shortLabel: 'Pharma', code: 'PH', shortcut: '5' },
  { id: 'briefs', path: '/briefs', label: 'Research Briefs', shortLabel: 'Briefs', code: 'BR', shortcut: '6' },
  { id: 'combinations', path: '/combinations', label: 'Combination Therapy', shortLabel: 'Combos', code: 'CB', shortcut: '7' },
  { id: 'omics', path: '/omics', label: 'VCF & Multi-Omics', shortLabel: 'Omics', code: 'OM', shortcut: '8' },
  { id: 'biophysics', path: '/biophysics', label: '3D Structure', shortLabel: '3D', code: '3D', shortcut: '9' },
]

export const FUTURE_NAV: NavItem[] = []

/**
 * Compact 54px icon rail — Cistron VCL Systems Biology IDE.
 */
export function SidebarNav({
  collapsed: _collapsed,
  onToggle: _onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const navigate = useNavigate()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const item = PRIMARY_NAV.find((n) => n.shortcut === e.key)
      if (item) {
        e.preventDefault()
        navigate(item.path)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])

  return (
    <aside className="relative z-20 flex h-full w-[54px] shrink-0 flex-col items-center border-r border-cyan-flux/20 bg-[#041820]/95 py-2 backdrop-blur-sm">
      <div
        className="pointer-events-none absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-cyan-flux via-phosphor/70 to-emerald-active"
        aria-hidden
      />
      <nav className="flex flex-1 flex-col items-center gap-1">
        {PRIMARY_NAV.map((item) => (
          <NavLink
            key={item.id}
            to={item.path}
            title={`${item.label}${item.shortcut ? ` (⌘${item.shortcut})` : ''}`}
            className={({ isActive }) =>
              clsx(
                'vcl-rail-btn font-mono text-[10.5px] font-semibold tracking-wide transition',
                isActive
                  ? 'bg-[#0a3040] text-cyan-flux shadow-[inset_0_0_0_1px_rgba(45,212,191,0.45),0_0_14px_rgba(45,212,191,0.2)]'
                  : 'text-vcl-muted hover:bg-vcl-surface/70 hover:text-phosphor',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={clsx(
                    'absolute -left-[5px] top-[9px] h-4 w-0.5 rounded-sm transition',
                    isActive ? 'bg-phosphor glow-phosphor' : 'bg-transparent',
                  )}
                />
                {item.code}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div
        className="mb-1 grid h-[26px] w-[26px] place-items-center rounded-md border border-cyan-flux/35 bg-[#0a2834] font-mono text-[9.5px] font-semibold text-phosphor"
        title="Operator"
      >
        AV
      </div>
    </aside>
  )
}
