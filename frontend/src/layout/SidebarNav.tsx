import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, PanelLeft } from 'lucide-react'
import { clsx } from 'clsx'
import { loadSidebarExpanded, persistSidebarExpanded } from './studioChrome'

export type NavItem = {
  id: string
  path: string
  label: string
  shortLabel: string
  code: string
  shortcut?: string
  hint?: string
  /** Optional research-phase tag for future/placeholder destinations. */
  phase?: number
}

type NavGroup = {
  id: string
  label: string
  items: NavItem[]
}

export const PRIMARY_NAV: NavItem[] = [
  { id: 'studio', path: '/studio', label: 'Simulation Studio', shortLabel: 'Studio', code: 'ST', shortcut: '1', hint: 'Pathway map' },
  { id: 'pathways', path: '/pathways', label: 'Disease Pathways', shortLabel: 'Pathways', code: 'PW', shortcut: '2', hint: 'Pick condition graph' },
  { id: 'explorer', path: '/explorer', label: 'Network Builder', shortLabel: 'Explorer', code: 'EX', shortcut: '3', hint: 'Edit topology' },
  { id: 'xai', path: '/xai', label: 'Perturbation Sensitivity', shortLabel: 'XAI', code: 'XA', shortcut: '4', hint: 'Drivers & Sobol' },
  { id: 'pharmacology', path: '/pharmacology', label: 'Pharmacology Lab', shortLabel: 'Pharma', code: 'PH', shortcut: '5', hint: 'Dose · KO · clamp' },
  { id: 'phenotype', path: '/phenotype', label: 'Phenotype Readout', shortLabel: 'Phenotype', code: 'PT', hint: 'Summary · wet-lab' },
  { id: 'briefs', path: '/briefs', label: 'Research Briefs', shortLabel: 'Briefs', code: 'BR', shortcut: '6', hint: 'Narratives & export' },
  { id: 'combinations', path: '/combinations', label: 'Combination Therapy', shortLabel: 'Combos', code: 'CB', shortcut: '7', hint: 'Bliss / Loewe' },
  { id: 'omics', path: '/omics', label: 'VCF & Multi-Omics', shortLabel: 'Omics', code: 'OM', shortcut: '8', hint: 'RNA-seq → y₀' },
  { id: 'biophysics', path: '/biophysics', label: '3D Structure', shortLabel: '3D', code: '3D', shortcut: '9', hint: '3Dmol · ChimeraX' },
]

/** Benchling-style module groups — one job per destination. */
export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'simulate',
    label: 'Simulate',
    items: PRIMARY_NAV.filter((n) => n.id === 'studio' || n.id === 'pathways'),
  },
  {
    id: 'build',
    label: 'Build',
    items: PRIMARY_NAV.filter((n) => n.id === 'explorer'),
  },
  {
    id: 'analyze',
    label: 'Analyze',
    items: PRIMARY_NAV.filter((n) =>
      ['xai', 'pharmacology', 'combinations'].includes(n.id),
    ),
  },
  {
    id: 'evidence',
    label: 'Evidence',
    items: PRIMARY_NAV.filter((n) =>
      ['phenotype', 'omics', 'briefs', 'biophysics'].includes(n.id),
    ),
  },
]

export const FUTURE_NAV: NavItem[] = []

/**
 * Left destination rail — collapsed codes or expanded labels (Benchling / VS Code).
 * Features live on routes, not stacked on Studio.
 */
export function SidebarNav({
  expanded,
  onExpandedChange,
}: {
  expanded: boolean
  onExpandedChange: (v: boolean) => void
}) {
  const navigate = useNavigate()
  const location = useLocation()

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
    <aside
      className={clsx(
        'relative z-20 flex h-full shrink-0 flex-col border-r border-cyan-flux/20 bg-[#041820]/95 py-2 backdrop-blur-sm transition-[width] duration-200',
        expanded ? 'w-[200px]' : 'w-[54px]',
      )}
    >
      <div
        className="pointer-events-none absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-cyan-flux via-phosphor/70 to-emerald-active"
        aria-hidden
      />

      <div
        className={clsx(
          'mb-2 flex shrink-0 items-center px-2',
          expanded ? 'justify-between' : 'justify-center',
        )}
      >
        {expanded ? (
          <span className="pl-1 font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-cyan-flux/80">
            Modules
          </span>
        ) : null}
        <button
          type="button"
          title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
          onClick={() => onExpandedChange(!expanded)}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-vcl-border text-vcl-muted hover:bg-vcl-surface hover:text-vcl-text"
        >
          {expanded ? <ChevronLeft className="h-3.5 w-3.5" /> : <PanelLeft className="h-3.5 w-3.5" />}
        </button>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1.5 pb-2">
        {NAV_GROUPS.map((group) => (
          <div key={group.id} className="flex flex-col gap-0.5">
            {expanded ? (
              <div className="px-2 pb-0.5 font-mono text-[8.5px] font-semibold uppercase tracking-[0.12em] text-vcl-dim">
                {group.label}
              </div>
            ) : null}
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                to={item.path}
                title={`${item.label}${item.shortcut ? ` (⌘${item.shortcut})` : ''}`}
                className={({ isActive }) =>
                  clsx(
                    'vcl-focus-ring relative flex items-center rounded-md transition',
                    expanded
                      ? 'gap-2 px-2 py-1.5'
                      : 'mx-auto h-[34px] w-[34px] justify-center',
                    isActive
                      ? 'bg-[#0a3040] text-cyan-flux shadow-[inset_0_0_0_1px_rgba(45,212,191,0.45),0_0_14px_rgba(45,212,191,0.15)]'
                      : 'text-vcl-muted hover:bg-vcl-surface/70 hover:text-phosphor',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={clsx(
                        'absolute left-0 top-1/2 h-3.5 w-0.5 -translate-y-1/2 rounded-sm transition',
                        isActive ? 'bg-phosphor' : 'bg-transparent',
                      )}
                    />
                    <span className="font-mono text-[10.5px] font-semibold tracking-wide">
                      {item.code}
                    </span>
                    {expanded ? (
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[11px] font-semibold leading-tight">
                          {item.shortLabel}
                        </span>
                        {item.hint ? (
                          <span className="block truncate text-[9px] font-normal text-vcl-dim">
                            {item.hint}
                          </span>
                        ) : null}
                      </span>
                    ) : null}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div
        className={clsx(
          'mx-auto mb-1 grid h-[26px] place-items-center rounded-md border border-cyan-flux/35 bg-[#0a2834] font-mono text-[9.5px] font-semibold text-phosphor',
          expanded ? 'w-[calc(100%-12px)]' : 'w-[26px]',
        )}
        title="Operator"
      >
        {expanded ? (
          <span className="flex items-center gap-1.5 px-2">
            <ChevronRight className="h-3 w-3 opacity-50" />
            {location.pathname.replace(/^\//, '') || 'studio'}
          </span>
        ) : (
          'AV'
        )}
      </div>
    </aside>
  )
}

/** Hook for shell-owned expanded state with persistence. */
export function useSidebarExpanded() {
  const [expanded, setExpanded] = useState(loadSidebarExpanded)
  const set = (v: boolean) => {
    setExpanded(v)
    persistSidebarExpanded(v)
  }
  return [expanded, set] as const
}
