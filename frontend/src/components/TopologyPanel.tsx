import { GlassCard } from './GlassCard'
import type { TopologicalAnalysis } from '../api/types'
import { StatDisclosure } from './studio/StatDisclosure'
import { useViewMode } from '../layout/viewModeGates'

export function TopologyPanel({
  topo,
  compact = false,
}: {
  topo: TopologicalAnalysis | null
  compact?: boolean
}) {
  const mode = useViewMode()

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
  const topBn = bottlenecks[0]
  const topSl = pairs[0]

  const headline = topBn
    ? `${topBn.node} is a signaling bottleneck (${topBn.role}) — high traffic through this node makes it a strong intervention hinge.`
    : 'Topology ranked — inspect bottlenecks and synthetic-lethal pairs for combo ideas.'

  const labHint = topSl
    ? `Wet-lab: consider dual targeting ${(topSl.pair ?? []).join(' + ')} after confirming single-agent effects.`
    : 'Wet-lab: validate the top bottleneck with a single KO before designing combos.'

  const body = (
    <div className={compact ? 'space-y-3' : 'grid gap-4 lg:grid-cols-3'}>
      <GlassCard
        title="Signaling Bottlenecks"
        hint={mode === 'systems' ? `Betweenness · hub · PageRank · ${topo.elapsed_ms.toFixed(0)} ms` : 'Ranked control points'}
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
                  {mode === 'systems' ? (
                    <span className="font-mono text-[0.65rem] text-slate-500">
                      BC={b.betweenness.toFixed(2)}
                    </span>
                  ) : null}
                </div>
                <div className="mt-0.5 text-[0.7rem] text-slate-400">{b.role}</div>
                {mode === 'systems' ? (
                  <div className="mt-1 flex gap-3 font-mono text-[0.65rem] text-slate-500">
                    <span>hub={b.hub_degree.toFixed(2)}</span>
                    <span>PR={b.pagerank.toFixed(3)}</span>
                  </div>
                ) : null}
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
            {pairs.slice(0, compact ? 4 : 8).map((p) => {
              const pair = Array.isArray(p.pair) ? p.pair : []
              return (
                <li
                  key={pair.join('+')}
                  className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-3 py-2"
                >
                  <div className="font-mono text-xs font-semibold text-cyan-200">
                    {pair.join(' + ')}
                  </div>
                  <div className="mt-1 text-[0.7rem] text-slate-400">{p.explanation}</div>
                  {mode === 'systems' ? (
                    <div className="mt-1 font-mono text-[0.65rem] text-slate-500">
                      S={Number(p.synergy_score ?? 0).toFixed(3)}
                    </div>
                  ) : null}
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No SL pairs in this run.</p>
        )}
      </GlassCard>
    </div>
  )

  return (
    <StatDisclosure headline={headline} labHint={labHint} numbersLabel="Show topology details">
      {body}
    </StatDisclosure>
  )
}
