import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Crosshair, Loader2, Play } from 'lucide-react'
import { GlassCard } from '../GlassCard'
import { GeneBadge, MetaLabel } from '../ui'
import { HypothesisCardList } from './HypothesisCard'
import { TopologyPanel } from '../TopologyPanel'
import { useLab } from '../../lab/LabContext'
import {
  runDualKnockoutScreen,
  type ComboPairResult,
  type DualKnockoutScreenResult,
} from '../../engine/comboScreen'

/**
 * Synthetic lethality / dual-target combinatorial screen workspace.
 * Matrix heatmap + click-to-apply dual titration on Studio canvas.
 */
export function CombosWorkspace() {
  const lab = useLab()
  const navigate = useNavigate()
  const [local, setLocal] = useState<DualKnockoutScreenResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<ComboPairResult | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  const topo = lab.topologicalAnalysis
  const serverPairs = topo?.synthetic_lethal_pairs ?? []

  const runClientScreen = useCallback(() => {
    if (!lab.graph) {
      setStatus('Load a Studio graph first.')
      return
    }
    setBusy(true)
    setStatus(null)
    // Defer so UI can paint spinner
    window.setTimeout(() => {
      try {
        const preferred = Object.keys(lab.perturbations)
        const result = runDualKnockoutScreen(lab.graph, {
          maxCandidates: 8,
          preferredCandidates: preferred,
          lethalThreshold: 0.4,
          synergyThreshold: 0.06,
          tEnd: 36,
          dt: 1.2,
        })
        setLocal(result)
        setSelected(result.pairs[0] ?? null)
        setStatus(
          `Screened ${result.candidates.length}×${result.candidates.length} · ${result.lethalPairs.length} SL · ${result.elapsedMs.toFixed(0)} ms`,
        )
      } catch (err) {
        setStatus(err instanceof Error ? err.message : 'Combo screen failed')
      } finally {
        setBusy(false)
      }
    }, 30)
  }, [lab.graph, lab.perturbations])

  const runServerScreen = () => {
    lab.runDualTargetScreen()
    setStatus('Server Dual Screen running…')
  }

  const applyDual = (pair: ComboPairResult) => {
    setSelected(pair)
    lab.setNodePerturbation(pair.a, 0, { resim: false })
    lab.setNodePerturbation(pair.b, 0, { resim: true })
    setStatus(`Applied dual KO: ${pair.a} + ${pair.b} → Studio`)
    navigate('/studio')
  }

  const candidates = local?.candidates ?? []
  const matrix = local?.matrix ?? {}

  const synergyExtent = useMemo(() => {
    const vals = Object.values(matrix)
    if (!vals.length) return 0.2
    return Math.max(0.12, ...vals.map((v) => Math.abs(v)))
  }, [matrix])

  return (
    <div className="mx-auto flex max-w-[100rem] flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
            Combination Therapy & Synthetic Lethality
          </h1>
          <p className="text-sm text-slate-500">
            Pairwise Bliss synergy matrix · click a cell to dual-titrate on Studio
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!lab.graph || busy}
            onClick={runClientScreen}
            className="inline-flex items-center gap-2 rounded-xl border border-violet-hub/40 bg-violet-950/50 px-4 py-2.5 text-sm font-bold text-violet-100 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />}
            Client Dual Screen
          </button>
          <button
            type="button"
            disabled={!lab.engineLive || lab.busy}
            onClick={runServerScreen}
            className="inline-flex items-center gap-2 rounded-xl bg-coral-action px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Server SL scan
          </button>
        </div>
      </div>

      {status ? (
        <p className="text-[11px] text-cyan-200/90">{status}</p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <GlassCard
          title="Bliss synergy heatmap"
          hint="S = E_A + E_B − E_AB · red = synergistic / SL"
        >
          {candidates.length >= 2 ? (
            <div className="overflow-auto">
              <table className="border-collapse text-[10px]">
                <thead>
                  <tr>
                    <th className="p-1" />
                    {candidates.map((c) => (
                      <th key={c} className="p-1 font-mono text-slate-400">
                        {c.slice(0, 5)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((row) => (
                    <tr key={row}>
                      <td className="p-1 font-mono font-semibold text-slate-300">{row.slice(0, 5)}</td>
                      {candidates.map((col) => {
                        const key = `${row}|${col}`
                        const v = matrix[key] ?? 0
                        const t = Math.max(-1, Math.min(1, v / synergyExtent))
                        const bg =
                          row === col
                            ? 'rgba(100,116,139,0.35)'
                            : t >= 0
                              ? `rgba(244,63,94,${0.12 + t * 0.75})`
                              : `rgba(16,185,129,${0.12 + -t * 0.55})`
                        const pair =
                          local?.pairs.find(
                            (p) =>
                              (p.a === row && p.b === col) || (p.a === col && p.b === row),
                          ) ?? null
                        return (
                          <td key={col} className="p-0.5">
                            <button
                              type="button"
                              disabled={row === col || !pair}
                              title={
                                pair
                                  ? `${pair.a}+${pair.b} Bliss=${pair.blissSynergy.toFixed(3)}${
                                      pair.syntheticLethal ? ' · SL' : ''
                                    }`
                                  : key
                              }
                              onClick={() => pair && applyDual(pair)}
                              className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-800/80 font-mono text-[9px] text-slate-100 disabled:cursor-default"
                              style={{ background: bg }}
                            >
                              {row === col ? '—' : v.toFixed(2)}
                            </button>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-[10px] text-slate-500">
                Readouts: {(local?.readouts ?? []).join(', ') || '—'} · click off-diagonal to apply
                dual KO
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              Run <span className="font-semibold text-violet-200">Client Dual Screen</span> to build
              the N×N Bliss matrix from the active graph.
            </p>
          )}
        </GlassCard>

        <div className="space-y-3">
          <GlassCard title="Selected pair" hint="Apply dual titration → Studio">
            {selected ? (
              <div className="space-y-2 text-[12px] text-slate-300">
                <div className="flex flex-wrap items-center gap-2">
                  <GeneBadge name={selected.a} tone="coral" />
                  <span className="text-slate-500">+</span>
                  <GeneBadge name={selected.b} tone="coral" />
                  {selected.syntheticLethal ? (
                    <span className="rounded-md border border-coral-action/40 bg-coral-action/15 px-1.5 py-0.5 text-[9px] font-bold uppercase text-red-200">
                      Synthetic lethal
                    </span>
                  ) : null}
                </div>
                <div className="lab-mono text-[11px] text-slate-400">
                  Bliss S={selected.blissSynergy.toFixed(3)} · Loewe Δ=
                  {selected.loeweExcess.toFixed(3)}
                </div>
                <div className="lab-mono text-[10px] text-slate-500">
                  V_base={selected.viabilityBaseline.toFixed(3)} · V_A=
                  {selected.viabilityA.toFixed(3)} · V_B={selected.viabilityB.toFixed(3)} · V_AB=
                  {selected.viabilityAB.toFixed(3)}
                </div>
                <button
                  type="button"
                  onClick={() => applyDual(selected)}
                  className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-[12px] font-bold text-emerald-100"
                >
                  Apply dual KO on Studio
                </button>
              </div>
            ) : (
              <p className="text-[11px] text-slate-500">Select a matrix cell or run a screen.</p>
            )}
          </GlassCard>

          <GlassCard title="Top synergistic pairs" hint="Ranked by Bliss excess">
            <ul className="max-h-48 space-y-1.5 overflow-y-auto">
              {(local?.pairs ?? [])
                .slice(0, 8)
                .map((p) => (
                  <li key={`${p.a}+${p.b}`}>
                    <button
                      type="button"
                      onClick={() => setSelected(p)}
                      onDoubleClick={() => applyDual(p)}
                      className="flex w-full items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-1.5 text-left text-[11px] hover:border-violet-500/40"
                    >
                      <span className="font-mono text-violet-100">
                        {p.a} + {p.b}
                      </span>
                      <span className="lab-mono text-slate-400">
                        S={p.blissSynergy.toFixed(2)}
                        {p.syntheticLethal ? ' · SL' : ''}
                      </span>
                    </button>
                  </li>
                ))}
              {!local?.pairs.length && serverPairs.length ? (
                serverPairs.slice(0, 6).map((p) => {
                  const pair = Array.isArray(p.pair) ? p.pair : []
                  return (
                    <li key={pair.join('+')} className="text-[11px] text-slate-400">
                      <span className="font-mono text-violet-200">{pair.join(' + ')}</span>
                      <span className="lab-mono text-slate-500">
                        {' '}
                        · syn={Number(p.synergy_score ?? 0).toFixed(2)}
                      </span>
                    </li>
                  )
                })
              ) : null}
              {!local?.pairs.length && !serverPairs.length ? (
                <p className="text-[11px] text-slate-600">No pairs yet.</p>
              ) : null}
            </ul>
          </GlassCard>
        </div>
      </div>

      <TopologyPanel topo={topo} />

      {lab.causalHypotheses.length > 0 ? (
        <div className="max-w-xl">
          <MetaLabel className="mb-2">Causal hypotheses</MetaLabel>
          <HypothesisCardList hypotheses={lab.causalHypotheses} />
        </div>
      ) : null}
    </div>
  )
}
