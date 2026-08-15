import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { Loader2, Radar, Server } from 'lucide-react'
import { GlassCard } from '../GlassCard'
import { ScientistPanel } from '../ScientistPanel'
import { TopologyPanel } from '../TopologyPanel'
import { PageHeader, VclButton } from '../PageHeader'
import { ApplyToStudioButton } from './ApplyToStudioButton'
import { runSaltelliLite } from '../../api/client'
import { useLab } from '../../lab/LabContext'
import {
  computeSensitivityXAI,
  type SensitivityXAIResult,
} from '../../engine/sensitivityXAI'

/**
 * Perturbation sensitivity workspace — Sobol indices, parameter-force attributions,
 * plus server flux-attention overlays from LabContext.
 */
export function XAIWorkspace() {
  const lab = useLab()
  const xai = lab.xai
  const regs = lab.prioritization?.master_regulators ?? []
  const vectors = lab.prioritization?.node_vectors ?? {}

  const [local, setLocal] = useState<SensitivityXAIResult | null>(null)
  const [serverSaltelli, setServerSaltelli] = useState<{
    node: string
    S_i: number
    S_Ti: number
  }[]>([])
  const [busy, setBusy] = useState(false)
  const [serverBusy, setServerBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  const runSobol = () => {
    if (!lab.graph) {
      setStatus('Load a Studio graph first.')
      return
    }
    setBusy(true)
    setStatus(null)
    window.setTimeout(() => {
      try {
        const result = computeSensitivityXAI({
          graph: lab.graph,
          payload: lab.payload,
          xai: lab.xai,
          maxNodes: 10,
        })
        setLocal(result)
        setStatus(
          `Client Sobol on targets [${result.targets.join(', ')}] · ${result.elapsedMs.toFixed(0)} ms`,
        )
      } catch (err) {
        setStatus(err instanceof Error ? err.message : 'Sensitivity failed')
      } finally {
        setBusy(false)
      }
    }, 20)
  }

  const runServerSaltelli = async () => {
    const graphId = lab.graph?.id
    if (!graphId) {
      setStatus('Run Studio first so the server caches an active graph_id.')
      return
    }
    setServerBusy(true)
    setStatus(null)
    try {
      const data = await runSaltelliLite({
        graph_id: graphId,
        readout: lab.controls.targetNode || lab.controls.sourceNode,
        n_base: 5,
        clamps: lab.omicsClamps,
        knockouts: lab.controls.knockouts,
        t_end: 60,
      })
      if (!data.ok) {
        setStatus(data.detail || 'Saltelli-lite returned empty')
        setServerSaltelli([])
        return
      }
      setServerSaltelli(
        data.factors.slice(0, 12).map((label, i) => ({
          node: label,
          S_i: data.S_i[i] ?? 0,
          S_Ti: data.S_Ti[i] ?? 0,
        })),
      )
      setStatus(
        `Server Saltelli-lite · readout ${data.readout} · ${data.elapsed_ms.toFixed(0)} ms (${data.method})`,
      )
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Server Saltelli failed')
      setServerSaltelli([])
    } finally {
      setServerBusy(false)
    }
  }

  const shapChart = useMemo(
    () =>
      (xai?.node_attributions ?? []).slice(0, 10).map((a) => ({
        node: a.node,
        importance: a.importance,
      })),
    [xai],
  )

  const sobolChart = useMemo(() => {
    if (serverSaltelli.length) return serverSaltelli.slice(0, 10)
    return (local?.sobol ?? []).slice(0, 10).map((s) => ({
      node: s.node,
      S_i: s.S_i,
      S_Ti: s.S_Ti,
    }))
  }, [local, serverSaltelli])

  const forceChart = useMemo(
    () =>
      (local?.paramForce ?? []).slice(0, 12).map((p) => ({
        label: p.label.length > 28 ? `${p.label.slice(0, 26)}…` : p.label,
        force: p.shapForce,
        full: p.label,
      })),
    [local],
  )

  const scatterData = useMemo(() => local?.scatter ?? [], [local])

  return (
    <div className="mx-auto flex max-w-[100rem] flex-col gap-4 p-4 md:p-5">
      <PageHeader
        code="XA · Perturbation Sensitivity"
        title="Perturbation Sensitivity"
        description="Sobol Sᵢ / S_Ti and parameter-force attributions (flux attention — not a trained GAT/SHAP model)."
        actions={
          <>
            <VclButton variant="secondary" disabled={!lab.graph || busy} onClick={runSobol}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />}
              Client Sobol
            </VclButton>
            <VclButton
              variant="ghost"
              disabled={!lab.graph || serverBusy}
              onClick={() => void runServerSaltelli()}
            >
              {serverBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Server className="h-4 w-4" />
              )}
              Server Saltelli-lite
            </VclButton>
            <ApplyToStudioButton disabled={!lab.graph} />
          </>
        }
      />

      {status ? <p className="text-[11px] text-cyan-200/90">{status}</p> : null}

      <ScientistPanel scientist={lab.scientist} loading={lab.busy} compact />

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard
          title="Sobol / Saltelli indices"
          hint={
            serverSaltelli.length
              ? 'Server Saltelli-lite (numpy) · Sᵢ first-order · S_Ti total'
              : local?.targets?.length
                ? `Client Sobol · targets: ${local.targets.join(', ')}`
                : 'Sᵢ first-order · S_Ti total-effect'
          }
        >
          {sobolChart.length ? (
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={sobolChart} layout="vertical" margin={{ left: 8, right: 12 }}>
                  <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="node"
                    width={serverSaltelli.length ? 88 : 58}
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
                  <Bar dataKey="S_i" fill="#38BDF8" name="Sᵢ" radius={[0, 4, 4, 0]} />
                  <Bar dataKey="S_Ti" fill="#A78BFA" name="S_Ti" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty hint="Run Client Sobol or Server Saltelli-lite to rank network drivers." />
          )}
        </GlassCard>

        <GlassCard title="Parameter-force attributions" hint="k_cat · τ · transport · degradation">
          {forceChart.length ? (
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={forceChart} layout="vertical" margin={{ left: 8, right: 12 }}>
                  <XAxis type="number" stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={120}
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
                  <Bar dataKey="force" radius={[0, 4, 4, 0]}>
                    {forceChart.map((row) => (
                      <Cell
                        key={row.full}
                        fill={row.force >= 0 ? '#10B981' : '#FF5252'}
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
        <GlassCard title="Influence scatter" hint="Sᵢ vs Δy (parameter influence)">
          {scatterData.length ? (
            <div className="h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ left: 8, right: 12, top: 8, bottom: 8 }}>
                  <CartesianGrid stroke="#1E293B" />
                  <XAxis
                    type="number"
                    dataKey="S_i"
                    name="Sᵢ"
                    stroke="#64748B"
                    tick={{ fill: '#64748B', fontSize: 10 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="deltaY"
                    name="Δy"
                    stroke="#64748B"
                    tick={{ fill: '#64748B', fontSize: 10 }}
                  />
                  <ZAxis range={[40, 160]} />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    contentStyle={{
                      background: '#0F172A',
                      border: '1px solid #1E293B',
                      borderRadius: 10,
                      fontSize: 11,
                    }}
                  />
                  <Scatter data={scatterData} fill="#22D3EE">
                    {scatterData.map((row) => (
                      <Cell key={row.node} fill={row.deltaY >= 0 ? '#10B981' : '#F43F5E'} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty />
          )}
        </GlassCard>

        <GlassCard title="Server node importance" hint="Marginal contribution to ΣΔy_output (flux-attention proxy)">
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
            <Empty hint="Run a Studio simulation to populate server XAI attributions." />
          )}
        </GlassCard>
      </div>

      <TopologyPanel topo={lab.topologicalAnalysis} />

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
    </div>
  )
}

function Empty({ hint }: { hint?: string }) {
  return (
    <p className="text-sm text-slate-500">
      {hint ?? 'Run a simulation or Sobol analysis to populate charts.'}
    </p>
  )
}
