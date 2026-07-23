import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Dna,
  FileText,
  FlaskConical,
  GitBranch,
  Pill,
  Search,
  Sparkles,
} from 'lucide-react'
import { clsx } from 'clsx'
import { MetaLabel } from '../components/ui'

export type NavItem = {
  id: string
  path: string
  label: string
  shortLabel: string
  icon: typeof FlaskConical
  shortcut?: string
  comingSoon?: boolean
  phase?: number
}

export const PRIMARY_NAV: NavItem[] = [
  {
    id: 'studio',
    path: '/studio',
    label: 'Simulation Studio',
    shortLabel: 'Studio',
    icon: FlaskConical,
    shortcut: '1',
  },
  {
    id: 'explorer',
    path: '/explorer',
    label: 'Network Builder',
    shortLabel: 'Explorer',
    icon: Search,
    shortcut: '2',
  },
  {
    id: 'xai',
    path: '/xai',
    label: 'XAI & Prioritization',
    shortLabel: 'XAI',
    icon: BarChart3,
    shortcut: '3',
  },
  {
    id: 'pharmacology',
    path: '/pharmacology',
    label: 'Pharmacology Lab',
    shortLabel: 'Pharma',
    icon: Pill,
    shortcut: '4',
  },
  {
    id: 'briefs',
    path: '/briefs',
    label: 'Research Briefs',
    shortLabel: 'Briefs',
    icon: FileText,
    shortcut: '5',
  },
  {
    id: 'combinations',
    path: '/combinations',
    label: 'Combination Therapy',
    shortLabel: 'Combos',
    icon: GitBranch,
    shortcut: '6',
  },
]

export const FUTURE_NAV: NavItem[] = [
  {
    id: 'omics',
    path: '/omics',
    label: 'VCF & Multi-Omics',
    shortLabel: 'Omics',
    icon: Dna,
    comingSoon: true,
    phase: 2,
  },
  {
    id: 'biophysics',
    path: '/biophysics',
    label: 'AlphaFold Biophysics',
    shortLabel: '3D',
    icon: Sparkles,
    comingSoon: true,
    phase: 4,
  },
]

export function SidebarNav({
  collapsed,
  onToggle,
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
    <aside
      className={clsx(
        'relative z-20 flex h-full shrink-0 flex-col border-r border-slate-800/80 bg-obsidian-panel/95 backdrop-blur-xl transition-[width] duration-200 ease-out',
        collapsed ? 'w-[68px]' : 'w-[220px]',
      )}
    >
      <div className={clsx('flex items-center gap-2.5 px-3 py-3.5', collapsed && 'justify-center')}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-emerald-500/40 bg-gradient-to-br from-emerald-500/25 via-cyan-flux/15 to-violet-hub/20 text-[10px] font-extrabold tracking-wide text-emerald-50 glow-emerald">
          VS
        </div>
        {!collapsed ? (
          <div className="min-w-0">
            <div className="truncate text-[13px] font-extrabold tracking-tight text-slate-50">
              VoidSignal
            </div>
            <MetaLabel className="!normal-case !tracking-wide text-slate-500">
              Virtual Cellular Lab
            </MetaLabel>
          </div>
        ) : null}
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-2 pb-3">
        <SectionLabel collapsed={collapsed}>Workspaces</SectionLabel>
        {PRIMARY_NAV.map((item) => (
          <NavButton key={item.id} item={item} collapsed={collapsed} />
        ))}

        <div className="my-2.5 border-t border-slate-800/80" />
        <SectionLabel collapsed={collapsed}>Roadmap</SectionLabel>
        {FUTURE_NAV.map((item) => (
          <NavButton key={item.id} item={item} collapsed={collapsed} />
        ))}
      </nav>

      <button
        type="button"
        onClick={onToggle}
        className="m-2 inline-flex items-center justify-center gap-2 rounded-xl border border-slate-800/80 bg-slate-900/50 px-2 py-2 text-[11px] text-slate-400 transition hover:border-emerald-500/30 hover:text-emerald-200"
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
        {!collapsed ? <span>Collapse</span> : null}
      </button>
    </aside>
  )
}

function SectionLabel({ collapsed, children }: { collapsed: boolean; children: string }) {
  if (collapsed) return <div className="h-1.5" />
  return <div className="lab-meta px-2 pb-1.5 pt-1">{children}</div>
}

function NavButton({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const Icon = item.icon
  const [hovered, setHovered] = useState(false)

  if (item.comingSoon) {
    return (
      <div
        className={clsx(
          'relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-slate-600',
          collapsed && 'justify-center',
        )}
        title={`${item.label} · Phase ${item.phase}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <Icon className="h-3.5 w-3.5 shrink-0 opacity-50" />
        {!collapsed ? (
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12px] font-medium">{item.shortLabel}</div>
            <div className="text-[10px] text-slate-700">Phase {item.phase}</div>
          </div>
        ) : null}
        {collapsed && hovered ? (
          <Tooltip label={`${item.label} · Phase ${item.phase}`} />
        ) : null}
      </div>
    )
  }

  return (
    <NavLink
      to={item.path}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        clsx(
          'group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[12px] font-medium transition',
          collapsed && 'justify-center',
          isActive
            ? 'bg-emerald-500/10 text-emerald-200 shadow-[inset_0_0_0_1px_rgba(16,185,129,0.35),0_0_18px_rgba(16,185,129,0.1)]'
            : 'text-slate-400 hover:bg-slate-900/70 hover:text-slate-200',
        )
      }
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {({ isActive }) => (
        <>
          {isActive ? (
            <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-emerald-active glow-emerald" />
          ) : null}
          <Icon
            className={clsx(
              'h-3.5 w-3.5 shrink-0',
              isActive ? 'text-emerald-active' : 'text-slate-500 group-hover:text-slate-300',
            )}
          />
          {!collapsed ? (
            <>
              <span className="min-w-0 flex-1 truncate">{item.shortLabel}</span>
              {item.shortcut ? (
                <kbd className="lab-mono rounded border border-slate-800 bg-obsidian/80 px-1 py-0.5 text-[9px] text-slate-600">
                  ⌘{item.shortcut}
                </kbd>
              ) : null}
            </>
          ) : null}
          {collapsed && hovered ? <Tooltip label={item.label} shortcut={item.shortcut} /> : null}
        </>
      )}
    </NavLink>
  )
}

function Tooltip({ label, shortcut }: { label: string; shortcut?: string }) {
  return (
    <div className="pointer-events-none absolute left-full z-50 ml-2 whitespace-nowrap rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-[11px] text-slate-200 shadow-xl">
      {label}
      {shortcut ? (
        <span className="lab-mono ml-2 text-slate-500">⌘{shortcut}</span>
      ) : null}
    </div>
  )
}
