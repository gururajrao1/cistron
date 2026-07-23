import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { GlassCard } from '../components/GlassCard'
import { ScientistPanel } from '../components/ScientistPanel'
import { TopologyPanel } from '../components/TopologyPanel'
import { useLab } from '../lab/LabContext'

export function XaiView() {
  const lab = useLab()
  const xai = lab.xai
  const regs = lab.prioritization?.master_regulators ?? []
  const vectors = lab.prioritization?.node_vectors ?? {}

  const shapChart = useMemo(
    () =>
      (xai?.node_attributions ?? []).slice(0, 10).map((a) => ({
        node: a.node,
        importance: a.importance,
      })),
    [xai],
  )

  const featureRows = useMemo(() => {
    const top = xai?.node_attributions?.[0]
    if (!top) return []
    return top.feature_attributions.map((f) => ({
      feature: f.feature_name,
      attribution: f.attribution,
      value: f.value,
    }))
  }, [xai])

  const attentionHeat = useMemo(() => {
    const matrix = lab.prioritization?.attention_matrix ?? {}
    const keys = Object.keys(matrix).sort()
    const nodes = Array.from(
      new Set(keys.flatMap((k) => k.split('->')).filter(Boolean)),
    ).sort()
    return { nodes, matrix, keys: keys.slice(0, 36) }
  }, [lab.prioritization])

  const edgeChart = useMemo(
    () =>
      (xai?.edge_flow_impacts ?? []).slice(0, 10).map((e) => ({
        edge: `${e.source}→${e.target}`,
        impact: e.impact_score,
        alpha: e.alpha,
      })),
    [xai],
  )

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      <div>
        <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
          XAI & Target Prioritization
        </h1>
        <p className="text-sm text-slate-500">
          SHAP / IG proxy · GAT αᵢⱼ · counterfactual path analysis
        </p>
      </div>

      <ScientistPanel scientist={lab.scientist} loading={lab.busy} compact />

      <TopologyPanel topo={lab.topologicalAnalysis} />

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard title="SHAP Node Importance" hint="Marginal contribution to ΣΔy_output">
          {shapChart.length ? (
            <div className="h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={shapChart} layout="vertical" margin={{ left: 8, right: 12 }}>
                  <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="node"
                    width={58}
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
          ) : (
            <Empty />
          )}
        </GlassCard>

        <GlassCard
          title="Feature Attribution Waterfall"
          hint={
            xai?.node_attributions?.[0]
              ? `Top node ${xai.node_attributions[0].node} · y₀ · y₆₀ · Δy · wᵢ · KO`
              : 'y₀ · y₆₀ · Δy · wᵢ · is_knocked_out'
          }
        >
          {featureRows.length ? (
            <div className="h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={featureRows} layout="vertical" margin={{ left: 8, right: 12 }}>
                  <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="feature"
                    width={90}
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
                  <Bar dataKey="attribution" radius={[0, 4, 4, 0]}>
                    {featureRows.map((row) => (
                      <Cell
                        key={row.feature}
                        fill={row.attribution >= 0 ? '#10B981' : '#FF5252'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty />
          )}
        </GlassCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard title="GAT Attention Heatmap" hint="αᵢⱼ dynamic flow matrix">
          {attentionHeat.keys.length ? (
            <div className="max-h-72 overflow-auto">
              <div
                className="grid gap-1"
                style={{
                  gridTemplateColumns: `repeat(${Math.min(6, attentionHeat.keys.length)}, minmax(0, 1fr))`,
                }}
              >
                {attentionHeat.keys.map((key) => {
                  const a = attentionHeat.matrix[key] ?? 0
                  return (
                    <div
                      key={key}
                      title={`${key}: α=${a.toFixed(3)}`}
                      className="rounded-lg border border-slate-800 p-2 text-center"
                      style={{
                        background: `rgba(16, 185, 129, ${0.08 + a * 0.7})`,
                      }}
                    >
                      <div className="truncate text-[0.58rem] text-slate-400">{key}</div>
                      <div className="font-mono text-xs text-emerald-100">{a.toFixed(2)}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : (
            <Empty />
          )}
        </GlassCard>

        <GlassCard title="Edge Flow Impact" hint="Attentive flux decomposition">
          {edgeChart.length ? (
            <div className="h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={edgeChart} layout="vertical" margin={{ left: 8, right: 12 }}>
                  <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="edge"
                    width={78}
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
          ) : (
            <Empty />
          )}
        </GlassCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard title="Master Regulators" hint="Sᵢ = |Δy| · Σα_out">
          {regs.length ? (
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1">#</th>
                  <th>Gene</th>
                  <th>Sᵢ</th>
                  <th>Δy</th>
                </tr>
              </thead>
              <tbody>
                {regs.slice(0, 10).map(([name, score], i) => (
                  <tr key={name} className="border-t border-slate-800/70 text-slate-300">
                    <td className="py-1.5 text-slate-600">{i + 1}</td>
                    <td className="font-semibold text-emerald-200">{name}</td>
                    <td className="font-mono text-emerald-300">{score.toFixed(4)}</td>
                    <td className="font-mono">
                      {vectors[name] ? vectors[name]!.delta_y.toFixed(3) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty />
          )}
        </GlassCard>

        <GlassCard title="Counterfactual Path Analyzer" hint="What-if capacity restore / knockout">
          {xai?.counterfactuals?.length ? (
            <div className="space-y-3">
              {xai.counterfactuals.map((cf) => (
                <div
                  key={`${cf.node}-${cf.intervention}`}
                  className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 text-sm text-emerald-50/90"
                >
                  <div className="mb-1 flex flex-wrap gap-2 text-[0.7rem] text-slate-400">
                    <span className="font-semibold text-emerald-200">{cf.node}</span>
                    <span>→ {cf.readout_node}</span>
                    <span className="font-mono">
                      {cf.fold_change.toFixed(1)}× @ {cf.horizon_min.toFixed(0)} min
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed text-slate-300">{cf.narrative}</p>
                </div>
              ))}
            </div>
          ) : (
            <Empty />
          )}
        </GlassCard>
      </div>
    </div>
  )
}

function Empty() {
  return <p className="text-sm text-slate-500">Run a simulation to populate XAI analytics.</p>
}
