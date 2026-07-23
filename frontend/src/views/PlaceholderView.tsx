import { Link } from 'react-router-dom'
import { GlassCard } from '../components/GlassCard'
import { FUTURE_NAV } from '../layout/SidebarNav'

export function PlaceholderView({
  title,
  phase,
  description,
}: {
  title: string
  phase: number
  description: string
}) {
  const item = FUTURE_NAV.find((n) => n.phase === phase)

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-8">
      <GlassCard>
        <div className="mb-2 text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-emerald-400/80">
          Phase {phase} · Coming soon
        </div>
        <h1 className="text-xl font-extrabold tracking-tight text-slate-50">{title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">{description}</p>
        {item ? (
          <p className="mt-3 font-mono text-xs text-slate-600">{item.path}</p>
        ) : null}
        <Link
          to="/studio"
          className="mt-6 inline-flex rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/20"
        >
          Return to Simulation Studio
        </Link>
      </GlassCard>
    </div>
  )
}
