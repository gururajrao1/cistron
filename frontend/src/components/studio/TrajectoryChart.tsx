import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from 'recharts'
import { Loader2 } from 'lucide-react'
import type { ScrubberPayload } from '../../api/types'
import { GlassCard } from '../GlassCard'

const SERIES_COLORS: Record<string, string> = {
  O2: '#06B6D4',
  EGLN1: '#A855F7',
  HIF1A: '#EF4444',
  VEGFA: '#10B981',
  GLUT1: '#F59E0B',
  SLC2A1: '#F59E0B',
  MTOR: '#F43F5E',
  LDHA: '#38BDF8',
  AKT1: '#F472B6',
}

type ChartRow = { t: number; [key: string]: number }

function untreatedKey(sym: string) {
  return `${sym}__u`
}

function treatedKey(sym: string) {
  return `${sym}__t`
}

function DeltaTooltip({
  active,
  payload,
  label,
  focus,
}: {
  active?: boolean
  payload?: Array<{ dataKey?: string | number; value?: number; color?: string }>
  label?: number | string
  focus: string[]
}) {
  if (!active || !payload?.length) return null
  const byKey = Object.fromEntries(
    payload.map((p) => [String(p.dataKey), Number(p.value ?? 0)]),
  )
  return (
    <div className="rounded-lg border border-slate-700 bg-obsidian px-2.5 py-2 text-[11px] shadow-xl">
      <div className="mb-1 font-semibold text-slate-300">t = {label} min</div>
      <ul className="space-y-1">
        {focus.map((sym) => {
          const yU = byKey[untreatedKey(sym)]
          const yT = byKey[treatedKey(sym)]
          const color = SERIES_COLORS[sym] ?? '#94A3B8'
          if (yU == null && yT == null) return null
          const delta =
            yU != null && yT != null ? yT - yU : null
          return (
            <li key={sym} className="flex items-center justify-between gap-3">
              <span className="font-mono font-semibold" style={{ color }}>
                {sym}
              </span>
              <span className="lab-mono text-slate-400">
                {yU != null ? `u ${yU.toFixed(3)}` : '—'}
                {yT != null ? ` · t ${yT.toFixed(3)}` : ''}
                {delta != null ? (
                  <span
                    className={
                      delta < -0.02
                        ? ' text-red-300'
                        : delta > 0.02
                          ? ' text-emerald-300'
                          : ' text-slate-500'
                    }
                  >
                    {' '}
                    Δy={delta >= 0 ? '+' : ''}
                    {delta.toFixed(3)}
                  </span>
                ) : null}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function TrajectoryChart({
  untreatedRun,
  treatedRun,
  focus,
  scrubT,
  loading = false,
}: {
  untreatedRun: ScrubberPayload | null
  treatedRun: ScrubberPayload | null
  focus: string[]
  scrubT: number
  loading?: boolean
}) {
  const compare = Boolean(untreatedRun && treatedRun)
  const active = treatedRun ?? untreatedRun

  const chartData = useMemo(() => {
    if (!active) return [] as ChartRow[]
    const base = untreatedRun ?? active
    const treated = treatedRun
    const times = active.time_steps
    return times.map((t, i) => {
      const row: ChartRow = { t }
      for (const sym of focus) {
        const uSeries = base.nodes[sym]
        const tSeries = treated?.nodes[sym]
        if (uSeries) row[untreatedKey(sym)] = uSeries[i] ?? uSeries[uSeries.length - 1] ?? 0
        if (compare && tSeries) {
          row[treatedKey(sym)] = tSeries[i] ?? tSeries[tSeries.length - 1] ?? 0
        } else if (!compare && uSeries) {
          // Single-run mode: plot untreated key only (solid).
        }
      }
      return row
    })
  }, [active, untreatedRun, treatedRun, focus, compare])

  return (
    <GlassCard
      title="Activation trajectories"
      hint={
        compare
          ? 'Solid = untreated · dashed glow = treated · hover for Δy'
          : 'Multi-protein yᵢ(t) · playhead locked to scrubber'
      }
      className="h-[220px] shrink-0 overflow-hidden"
    >
      {active ? (
        <div className="h-[150px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#1E293B" strokeDasharray="3 3" />
              <XAxis
                dataKey="t"
                stroke="#64748B"
                tick={{ fill: '#64748B', fontSize: 11 }}
                label={{
                  value: 'min',
                  position: 'insideBottomRight',
                  fill: '#64748B',
                  offset: -2,
                }}
              />
              <YAxis
                domain={[0, 1.05]}
                stroke="#64748B"
                tick={{ fill: '#64748B', fontSize: 11 }}
              />
              <Tooltip content={<DeltaTooltip focus={focus} />} />
              <Legend
                wrapperStyle={{ fontSize: 10 }}
                formatter={(value) => {
                  const s = String(value)
                  if (s.endsWith('__u')) return `${s.slice(0, -3)} (untreated)`
                  if (s.endsWith('__t')) return `${s.slice(0, -3)} (treated)`
                  return s
                }}
              />
              <ReferenceLine
                x={scrubT}
                stroke="#10B981"
                strokeWidth={2}
                strokeDasharray="4 4"
                label={`t=${scrubT}`}
              />
              {focus.map((sym) => {
                const color = SERIES_COLORS[sym] ?? '#94A3B8'
                return (
                  <Line
                    key={untreatedKey(sym)}
                    type="monotone"
                    dataKey={untreatedKey(sym)}
                    name={untreatedKey(sym)}
                    stroke={color}
                    strokeOpacity={compare ? 0.55 : 1}
                    dot={false}
                    strokeWidth={compare ? 1.8 : 2.3}
                    isAnimationActive={false}
                  />
                )
              })}
              {compare
                ? focus.map((sym) => {
                    const color = SERIES_COLORS[sym] ?? '#94A3B8'
                    return (
                      <Line
                        key={treatedKey(sym)}
                        type="monotone"
                        dataKey={treatedKey(sym)}
                        name={treatedKey(sym)}
                        stroke={color}
                        strokeDasharray="5 4"
                        strokeWidth={2.6}
                        dot={false}
                        isAnimationActive={false}
                        style={{
                          filter: `drop-shadow(0 0 4px ${color})`,
                        }}
                      />
                    )
                  })
                : null}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="flex h-[120px] items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
          {loading ? 'Computing activation curves…' : 'No trajectory yet'}
        </div>
      )}
    </GlassCard>
  )
}
