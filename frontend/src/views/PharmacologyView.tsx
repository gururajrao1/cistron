import { useMemo } from 'react'
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'
import { Play } from 'lucide-react'
import { GlassCard } from '../components/GlassCard'
import { useLab } from '../lab/LabContext'

function occupancy(c: number, ki: number): number {
  return c / (c + ki)
}

export function PharmacologyView() {
  const lab = useLab()
  const { controls, nodes, clampOptions } = lab

  const doseCurve = useMemo(() => {
    const ki = Math.max(0.05, controls.ki)
    const points = []
    for (let c = 0; c <= 50; c += 1) {
      const theta = occupancy(c, ki)
      points.push({
        c,
        occupancy: theta,
        capacity: 1 - theta,
      })
    }
    return points
  }, [controls.ki])

  const multiTargets = useMemo(() => {
    const pool = nodes.length ? nodes : [controls.drugTarget]
    return pool.slice(0, 8)
  }, [nodes, controls.drugTarget])

  const applyAndRun = () => lab.runSimulation()

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
            Pharmacology & Perturbation Lab
          </h1>
          <p className="text-sm text-slate-500">
            Dose–response θ = C/(C+Kᵢ) · knockouts wᵢ=0 · environmental clamps
          </p>
        </div>
        <button
          type="button"
          disabled={!lab.engineLive || lab.busy}
          onClick={applyAndRun}
          className="inline-flex items-center gap-2 rounded-xl bg-coral-action px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
        >
          <Play className="h-4 w-4" /> Apply & Resimulate
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard title="Drug Dose–Response" hint="Occupancy θ and residual capacity 1−θ">
          <label className="mb-3 flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={controls.drugEnabled}
              onChange={(e) => lab.patchControls({ drugEnabled: e.target.checked })}
              className="accent-coral-action"
            />
            Enable targeted inhibitor
          </label>
          <label className="mb-1 block text-xs text-slate-400">Primary target</label>
          <select
            className="mb-3 w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm"
            value={controls.drugTarget}
            onChange={(e) => lab.patchControls({ drugTarget: e.target.value })}
          >
            {(nodes.length ? nodes : [controls.drugTarget]).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <label className="mb-1 block text-xs text-slate-400">
            Concentration C ({controls.cDrug.toFixed(1)} µM)
          </label>
          <input
            type="range"
            min={0}
            max={50}
            step={0.5}
            value={controls.cDrug}
            onChange={(e) => lab.patchControls({ cDrug: Number(e.target.value) })}
            className="mb-3 w-full accent-coral-action"
          />
          <label className="mb-1 block text-xs text-slate-400">
            Inhibition constant Kᵢ ({controls.ki.toFixed(1)} µM)
          </label>
          <input
            type="range"
            min={0.1}
            max={20}
            step={0.1}
            value={controls.ki}
            onChange={(e) => lab.patchControls({ ki: Number(e.target.value) })}
            className="mb-4 w-full accent-coral-action"
          />
          <div className="mb-2 grid grid-cols-2 gap-2 text-xs">
            <Stat
              label="θ occupancy"
              value={occupancy(controls.cDrug, controls.ki).toFixed(3)}
            />
            <Stat
              label="w residual"
              value={(1 - occupancy(controls.cDrug, controls.ki)).toFixed(3)}
            />
          </div>
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={doseCurve} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#1E293B" strokeDasharray="3 3" />
                <XAxis
                  dataKey="c"
                  stroke="#64748B"
                  tick={{ fill: '#64748B', fontSize: 10 }}
                  label={{ value: 'C (µM)', fill: '#64748B', fontSize: 10, position: 'insideBottomRight' }}
                />
                <YAxis domain={[0, 1]} stroke="#64748B" tick={{ fill: '#64748B', fontSize: 10 }} />
                <Tooltip
                  contentStyle={{
                    background: '#0F172A',
                    border: '1px solid #1E293B',
                    borderRadius: 10,
                    fontSize: 11,
                  }}
                />
                <ReferenceLine
                  x={controls.cDrug}
                  stroke="#FF5252"
                  strokeDasharray="4 4"
                  label={{ value: 'C', fill: '#FF8A80', fontSize: 10 }}
                />
                <Line
                  type="monotone"
                  dataKey="occupancy"
                  stroke="#FF5252"
                  strokeWidth={2}
                  dot={false}
                  name="θ"
                />
                <Line
                  type="monotone"
                  dataKey="capacity"
                  stroke="#10B981"
                  strokeWidth={2}
                  dot={false}
                  name="1−θ"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        <GlassCard title="Gene Knockout Matrix" hint="Loss-of-function · wᵢ = 0">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {multiTargets.map((n) => {
              const on = controls.knockouts.includes(n)
              return (
                <button
                  key={n}
                  type="button"
                  onClick={() => {
                    const knockouts = on
                      ? controls.knockouts.filter((x) => x !== n)
                      : [...controls.knockouts, n]
                    lab.patchControls({ knockouts })
                  }}
                  className={`rounded-xl border px-3 py-3 text-left text-sm font-semibold transition ${
                    on
                      ? 'border-coral-action/50 bg-coral-action/15 text-red-200'
                      : 'border-slate-800 bg-slate-950/50 text-slate-300 hover:border-slate-600'
                  }`}
                >
                  <div>{n}</div>
                  <div className="mt-1 font-mono text-[0.65rem] text-slate-500">
                    {on ? 'w=0 · KO' : 'wild-type'}
                  </div>
                </button>
              )
            })}
          </div>
          {!nodes.length ? (
            <p className="mt-3 text-xs text-slate-500">Resolve a network to populate KO targets.</p>
          ) : null}
        </GlassCard>
      </div>

      <GlassCard title="Environmental State Clamps" hint="Hold yᵢ(t) at fixed basal / stressed levels">
        <div className="grid gap-4 md:grid-cols-[1fr_2fr]">
          <div>
            <label className="mb-1 block text-xs text-slate-400">Clamp node</label>
            <select
              className="mb-3 w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm"
              value={controls.clampNode}
              onChange={(e) => lab.patchControls({ clampNode: e.target.value })}
            >
              {(clampOptions.length ? clampOptions : [controls.clampNode]).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <label className="mb-1 block text-xs text-slate-400">
              Level ({controls.clampValue.toFixed(2)})
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={controls.clampValue}
              onChange={(e) => lab.patchControls({ clampValue: Number(e.target.value) })}
              className="w-full accent-emerald-active"
            />
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-400">
            <p className="mb-2 text-slate-300">
              Active perturbation summary (applied on <strong>Apply & Resimulate</strong>):
            </p>
            <ul className="space-y-1 font-mono text-slate-500">
              <li>
                clamp {controls.clampNode}={controls.clampValue.toFixed(2)}
              </li>
              <li>
                KOs [{controls.knockouts.join(', ') || 'none'}]
              </li>
              <li>
                drug{' '}
                {controls.drugEnabled
                  ? `${controls.drugTarget} C=${controls.cDrug} Ki=${controls.ki}`
                  : 'off'}
              </li>
            </ul>
          </div>
        </div>
      </GlassCard>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2">
      <div className="text-[0.65rem] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 font-mono text-sm font-semibold text-slate-100">{value}</div>
    </div>
  )
}
