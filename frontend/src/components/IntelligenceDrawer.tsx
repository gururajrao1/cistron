import { useEffect, useMemo, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { GlassCard } from './GlassCard'
import type {
  PrioritizationResult,
  ReasonResponse,
  ScientistReasoning,
  XAIAttributionResult,
} from '../api/types'

function GeneBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[0.7rem] font-semibold tracking-wide text-emerald-200">
      {name}
    </span>
  )
}

function DeltaChip({ value }: { value: number }) {
  const up = value >= 0
  return (
    <span
      className={`inline-flex rounded-md border px-1.5 py-0.5 font-mono text-[0.68rem] font-semibold ${
        up
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
          : 'border-coral-action/30 bg-coral-action/10 text-red-300'
      }`}
    >
      {up ? '+' : ''}
      {value.toFixed(3)}
    </span>
  )
}

function MechTag({ label }: { label: string }) {
  return (
    <span className="inline-flex rounded-full border border-slate-700 bg-slate-800/80 px-2 py-0.5 text-[0.65rem] uppercase tracking-wide text-slate-400">
      {label}
    </span>
  )
}

function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-7 animate-pulse rounded-lg bg-slate-800/60" />
      ))}
    </div>
  )
}

function ScientistFeed({
  scientist,
  loading,
}: {
  scientist: ScientistReasoning | null
  loading?: boolean
}) {
  const [pulse, setPulse] = useState(false)
  useEffect(() => {
    if (!scientist?.brief) return
    setPulse(true)
    const t = window.setTimeout(() => setPulse(false), 900)
    return () => window.clearTimeout(t)
  }, [scientist?.brief, scientist?.elapsed_ms])

  const sentiment = scientist?.sentiment ?? 'neutral'
  const border =
    sentiment === 'up'
      ? 'border-emerald-500/50'
      : sentiment === 'down'
        ? 'border-coral-action/50'
        : sentiment === 'mixed'
          ? 'border-amber-400/40'
          : 'border-slate-700'
  const glow = pulse
    ? sentiment === 'down'
      ? 'shadow-[0_0_24px_rgba(255,82,82,0.35)]'
      : 'shadow-[0_0_24px_rgba(16,185,129,0.35)]'
    : ''

  return (
    <div
      className={`rounded-2xl border bg-slate-950/70 p-3 transition-shadow duration-500 ${border} ${glow}`}
    >
      <div className="mb-2 flex items-center gap-2">
        <Sparkles
          className={`h-4 w-4 ${
            sentiment === 'down' ? 'text-coral-action' : 'text-emerald-active'
          }`}
        />
        <div className="text-sm font-extrabold text-slate-50">AI Scientist</div>
        {scientist ? (
          <span className="ml-auto font-mono text-[0.65rem] text-slate-500">
            {scientist.elapsed_ms.toFixed(1)} ms
          </span>
        ) : null}
      </div>
      {scientist?.brief ? (
        <>
          <p className="text-sm leading-relaxed text-slate-200">{scientist.brief}</p>
          {Object.keys(scientist.top_node_deltas ?? {}).length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(scientist.top_node_deltas)
                .slice(0, 4)
                .map(([n, d]) => (
                  <span key={n} className="inline-flex items-center gap-1">
                    <GeneBadge name={n} />
                    <DeltaChip value={d} />
                  </span>
                ))}
            </div>
          ) : null}
        </>
      ) : loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
          Synthesizing live reasoning…
        </div>
      ) : (
        <p className="text-sm text-slate-500">Run a condition to hear the AI Scientist.</p>
      )}
    </div>
  )
}

export function IntelligenceDrawer({
  prioritization,
  reason,
  xai,
  scientist,
  loading = false,
}: {
  prioritization: PrioritizationResult | null
  reason: ReasonResponse | null
  xai?: XAIAttributionResult | null
  scientist?: ScientistReasoning | null
  loading?: boolean
}) {
  const regs = prioritization?.master_regulators ?? []
  const vectors = prioritization?.node_vectors ?? {}
  const paths = reason?.context.extracted_paths ?? []

  const shapChart = useMemo(
    () =>
      (xai?.node_attributions ?? []).slice(0, 8).map((a) => ({
        node: a.node,
        importance: a.importance,
      })),
    [xai],
  )

  const edgeChart = useMemo(
    () =>
      (xai?.edge_flow_impacts ?? []).slice(0, 8).map((e) => ({
        edge: `${e.source}→${e.target}`,
        impact: e.impact_score,
        alpha: e.alpha,
      })),
    [xai],
  )

  return (
    <aside className="flex h-full flex-col gap-3 overflow-y-auto pl-1">
      <div>
        <div className="text-sm font-extrabold tracking-tight text-slate-50">Intelligence</div>
        <p className="text-xs text-slate-500">XAI attributions · live filter reasoning</p>
      </div>

      <ScientistFeed scientist={scientist ?? null} loading={loading} />

      <GlassCard title="XAI · SHAP Node Importance" hint="Marginal contribution to ΣΔy_output">
        {shapChart.length ? (
          <div className="h-[180px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={shapChart} layout="vertical" margin={{ left: 8, right: 8 }}>
                <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                <YAxis
                  type="category"
                  dataKey="node"
                  width={56}
                  stroke="#64748B"
                  tick={{ fill: '#94A3B8', fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{
                    background: '#0F172A',
                    border: '1px solid #1E293B',
                    borderRadius: 10,
                    fontSize: 11,
                  }}
                />
                <Bar dataKey="importance" radius={[0, 4, 4, 0]}>
                  {shapChart.map((row) => (
                    <Cell
                      key={row.node}
                      fill={row.importance >= 0 ? '#10B981' : '#FF5252'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : loading ? (
          <SkeletonRows rows={4} />
        ) : (
          <p className="text-sm text-slate-500">No SHAP attributions yet.</p>
        )}
        {xai?.counterfactuals?.[0]?.narrative ? (
          <p className="mt-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-2.5 text-xs leading-relaxed text-emerald-100/90">
            {xai.counterfactuals[0].narrative}
          </p>
        ) : null}
      </GlassCard>

      <GlassCard title="XAI · GAT Edge Flow" hint="Attentive flow decomposition αᵢⱼ">
        {edgeChart.length ? (
          <div className="h-[170px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={edgeChart} layout="vertical" margin={{ left: 8, right: 8 }}>
                <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                <YAxis
                  type="category"
                  dataKey="edge"
                  width={72}
                  stroke="#64748B"
                  tick={{ fill: '#94A3B8', fontSize: 9 }}
                />
                <Tooltip
                  contentStyle={{
                    background: '#0F172A',
                    border: '1px solid #1E293B',
                    borderRadius: 10,
                    fontSize: 11,
                  }}
                />
                <Bar dataKey="impact" fill="#38BDF8" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : loading ? (
          <SkeletonRows rows={3} />
        ) : (
          <p className="text-sm text-slate-500">No edge-flow ranks yet.</p>
        )}
      </GlassCard>

      <GlassCard
        title="Master Regulators"
        hint="Dynamic flow attention (αᵢⱼ) · driver score Sᵢ"
      >
        {regs.length ? (
          <div className="overflow-hidden rounded-xl border border-slate-800">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/70 text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Rank</th>
                  <th className="px-3 py-2 font-medium">Regulator</th>
                  <th className="px-3 py-2 font-medium">Sᵢ</th>
                  <th className="px-3 py-2 font-medium">Δy</th>
                </tr>
              </thead>
              <tbody>
                {regs.slice(0, 8).map(([name, score], i) => {
                  const vec = vectors[name]
                  return (
                    <tr key={name} className="border-t border-slate-800/80 text-slate-300">
                      <td className="px-3 py-2 text-slate-500">{i + 1}</td>
                      <td className="px-3 py-2">
                        <GeneBadge name={name} />
                      </td>
                      <td className="px-3 py-2 font-mono text-emerald-300">{score.toFixed(4)}</td>
                      <td className="px-3 py-2">
                        {vec ? <DeltaChip value={vec.delta_y} /> : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : loading ? (
          <SkeletonRows rows={4} />
        ) : (
          <p className="text-sm text-slate-500">No regulator ranking yet.</p>
        )}
      </GlassCard>

      <GlassCard title="Causal BioReasoner" hint="Pathway causal chains · mechanisms">
        {reason?.brief ? (
          <p className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm leading-relaxed text-slate-300">
            {reason.brief}
          </p>
        ) : loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
            Tracing causal cascade…
          </div>
        ) : (
          <p className="text-sm text-slate-500">No discovery brief yet.</p>
        )}

        {paths.length ? (
          <div className="mt-3 space-y-2">
            {paths.slice(0, 2).map((path, idx) => (
              <div
                key={`${path.nodes.join('-')}-${idx}`}
                className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5"
              >
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  {path.nodes.map((n, i) => (
                    <span key={`${n}-${i}`} className="inline-flex items-center gap-1">
                      <GeneBadge name={n} />
                      {i < path.nodes.length - 1 ? (
                        <span className="text-slate-600">
                          {path.signs?.[i] != null && path.signs[i]! < 0 ? '⊣' : '→'}
                        </span>
                      ) : null}
                    </span>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[0.68rem] text-slate-500">
                    Σα {path.cumulative_attention.toFixed(4)}
                  </span>
                  {path.mechanisms?.map((m) => (
                    <MechTag key={m} label={m} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </GlassCard>
    </aside>
  )
}
