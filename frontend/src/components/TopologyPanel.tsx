import { GlassCard } from './GlassCard'
import type { TopologicalAnalysis } from '../api/types'

export function TopologyPanel({
  topo,
  compact = false,
}: {
  topo: TopologicalAnalysis | null
  compact?: boolean
}) {
  if (!topo) {
    return (
      <GlassCard title="Topological Vulnerability" hint="Bottlenecks · feedback · synthetic lethality">
        <p className="text-sm text-slate-500">
          Run a simulation to compute network bottlenecks, feedback loops, and synthetic-lethal pairs.
        </p>
      </GlassCard>
    )
  }

  const bottlenecks = topo.bottlenecks ?? []
  const loops = topo.feedback_loops ?? []
  const pairs = topo.synthetic_lethal_pairs ?? []

  return (
    <div className={compact ? 'space-y-3' : 'grid gap-4 lg:grid-cols-3'}>
      <GlassCard
        title="Signaling Bottlenecks"
        hint={`Betweenness · hub · PageRank · ${topo.elapsed_ms.toFixed(0)} ms`}
      >
        {bottlenecks.length ? (
          <ul className="space-y-2">
            {bottlenecks.map((b) => (
              <li
                key={b.node}
                className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-3 py-2"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold text-emerald-200">{b.node}</span>
                  <span className="font-mono text-[0.65rem] text-slate-500">
                    BC={b.betweenness.toFixed(2)}
                  </span>
                </div>
                <div className="mt-0.5 text-[0.7rem] text-slate-400">{b.role}</div>
                <div className="mt-1 flex gap-3 font-mono text-[0.65rem] text-slate-500">
                  <span>hub={b.hub_degree.toFixed(2)}</span>
                  <span>PR={b.pagerank.toFixed(3)}</span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No bottlenecks ranked.</p>
        )}
      </GlassCard>

      <GlassCard title="Feedback Loops" hint="Signed directed cycles">
        {loops.length ? (
          <ul className="space-y-2">
            {loops.slice(0, compact ? 4 : 8).map((loop, i) => (
              <li
                key={`${loop.cycle.join('-')}-${i}`}
                className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-3 py-2"
              >
                <div className="mb-1 text-[0.68rem] font-semibold uppercase tracking-wide text-sky-300/90">
                  {loop.type}
                </div>
                <div className="font-mono text-xs text-slate-300">
                  {loop.cycle.join(' → ')}
                  {loop.cycle.length > 1 ? ` → ${loop.cycle[0]}` : ''}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No short feedback cycles detected.</p>
        )}
      </GlassCard>

      <GlassCard title="Synthetic Lethality" hint="Pairwise virtual KO · Σy_out collapse">
        {pairs.length ? (
          <ul className="space-y-2">
            {pairs.slice(0, compact ? 4 : 10).map((p) => (
              <li
                key={p.pair.join('+')}
                className="rounded-xl border border-coral-action/25 bg-coral-action/5 px-3 py-2"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold text-coral-action">
                    {p.pair.join(' + ')}
                  </span>
                  <span className="font-mono text-[0.65rem] text-emerald-300">
                    S={p.synergy_score.toFixed(2)}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-slate-400">{p.explanation}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">
            No synthetic-lethal pairs under the dual-collapse criterion.
          </p>
        )}
      </GlassCard>
    </div>
  )
}
