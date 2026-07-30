import { useMemo, useState } from 'react'
import { clsx } from 'clsx'
import { TrajectoryChart } from '../../components/studio/TrajectoryChart'
import { useLab } from '../../lab/LabContext'
import { FOCUS_SERIES } from '../../api/types'
import {
  metabolicAtTime,
  simulateMetabolicBridge,
} from '../../engine/metabolicBridge'
import { stepHif1aTranslocation } from '../../components/studio/OrganelleCompartments'

type BottomTab = 'trajectory' | 'compare' | 'organelle' | 'flux'

function terminalY(
  nodes: Record<string, number[]> | undefined,
  sym: string,
): number {
  const s = nodes?.[sym]
  if (!s?.length) return 0
  return s[s.length - 1] ?? 0
}

function OrganelleTab() {
  const lab = useLab()
  const species = useMemo(() => {
    const focus =
      FOCUS_SERIES[lab.profileId] ??
      FOCUS_SERIES.hypoxia ??
      ['HIF1A', 'VEGFA', 'EGLN1']
    const fromGraph = lab.nodes.slice(0, 8)
    return Array.from(new Set(['HIF1A', ...focus, ...fromGraph])).slice(0, 10)
  }, [lab.profileId, lab.nodes])

  const o2 =
    lab.payload?.nodes?.O2?.[Math.min(lab.scrubT, (lab.payload.nodes.O2?.length ?? 1) - 1)] ??
    0.35

  return (
    <div className="h-full overflow-auto p-2">
      <table className="w-full border-collapse text-left font-mono text-[10.5px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.1em] text-vcl-dim">
            <th className="px-2 py-1.5 font-semibold">Species</th>
            <th className="px-2 py-1.5 font-semibold">Cytoplasm</th>
            <th className="px-2 py-1.5 font-semibold">Nucleus</th>
            <th className="px-2 py-1.5 font-semibold">Mitochondria</th>
            <th className="px-2 py-1.5 font-semibold">Δ Nuc</th>
          </tr>
        </thead>
        <tbody>
          {species.map((sym) => {
            const y = terminalY(lab.payload?.nodes, sym)
            let cyto = y * 0.55
            let nuc = y * 0.35
            let mito = y * 0.1
            if (sym === 'HIF1A') {
              let state = { cytoplasm: cyto, nucleus: nuc, mitochondria: mito }
              const { next } = stepHif1aTranslocation(state, o2, Math.max(1, lab.scrubT))
              cyto = next.cytoplasm
              nuc = next.nucleus
              mito = next.mitochondria
            }
            const deltaNuc = nuc - y * 0.2
            return (
              <tr key={sym} className="border-t border-vcl-border/80 hover:bg-vcl-surface/40">
                <td className="px-2 py-1.5 font-semibold text-vcl-text">{sym}</td>
                <td className="px-2 py-1.5 text-vcl-muted">{cyto.toFixed(3)}</td>
                <td className="px-2 py-1.5 text-violet-hub">{nuc.toFixed(3)}</td>
                <td className="px-2 py-1.5 text-amber-kinase">{mito.toFixed(3)}</td>
                <td
                  className={clsx(
                    'px-2 py-1.5',
                    deltaNuc >= 0 ? 'text-emerald-active' : 'text-coral-action',
                  )}
                >
                  {deltaNuc >= 0 ? '+' : ''}
                  {deltaNuc.toFixed(3)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 px-2 text-[10px] leading-relaxed text-vcl-dim">
        HIF1A nuclear import scales with hypoxia: k_import = base × (1 − local O₂). Scrub t
        advances the compartmental step.
      </p>
    </div>
  )
}

function FluxTab() {
  const lab = useLab()
  const bridge = useMemo(() => {
    if (!lab.payload) return null
    try {
      return simulateMetabolicBridge(lab.payload)
    } catch {
      return null
    }
  }, [lab.payload])

  const point = bridge ? metabolicAtTime(bridge, lab.scrubT) : null
  const atp = point?.atpYield ?? 0
  const lac = point?.lactateExport ?? 0
  const nad = point?.nadRatio ?? 1
  const ocr = Math.max(0, Math.min(100, (nad / (nad + 1)) * 100))

  const rows = point
    ? Object.entries(point.fluxes)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
        .slice(0, 8)
    : []

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-2">
      <div className="grid shrink-0 grid-cols-3 gap-2">
        {[
          { label: 'ATP yield', value: atp.toFixed(3), tone: 'text-emerald-active' },
          { label: 'Lactate', value: `${lac.toFixed(2)} mmol/L`, tone: 'text-amber-kinase' },
          { label: 'OCR proxy', value: `${ocr.toFixed(0)}%`, tone: 'text-cyan-flux' },
        ].map((k) => (
          <div
            key={k.label}
            className="rounded-md border border-vcl-border bg-vcl-surface px-2.5 py-2"
          >
            <div className="lab-meta">{k.label}</div>
            <div className={clsx('mt-1 font-mono text-[13px] font-semibold', k.tone)}>
              {bridge ? k.value : '—'}
            </div>
          </div>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-left font-mono text-[10.5px]">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.1em] text-vcl-dim">
              <th className="px-2 py-1 font-semibold">Reaction</th>
              <th className="px-2 py-1 font-semibold">Flux</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={2} className="px-2 py-3 text-vcl-dim">
                  Run a simulation to estimate glycolytic / oxidative flux.
                </td>
              </tr>
            ) : (
              rows.map(([rx, v]) => (
                <tr key={rx} className="border-t border-vcl-border/80">
                  <td className="px-2 py-1 text-vcl-text">{rx}</td>
                  <td className="px-2 py-1 text-vcl-muted">{v.toFixed(4)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CompareTab() {
  const lab = useLab()
  const focus = useMemo(() => {
    const preset = FOCUS_SERIES[lab.profileId] ?? FOCUS_SERIES.hypoxia
    const fromGraph = lab.nodes.slice(0, 8)
    return Array.from(new Set([...(preset ?? []), ...fromGraph])).slice(0, 8)
  }, [lab.profileId, lab.nodes])

  const untreated = lab.untreatedRun
  const treated = lab.treatedRun
  const hasBoth = Boolean(untreated && treated)

  return (
    <div className="h-full overflow-auto p-2">
      {!hasBoth ? (
        <p className="px-2 py-4 text-[11px] text-vcl-muted">
          Apply a knockout or titration, then re-run — baseline (untreated) vs treated trajectories
          will appear here as Δy at each scrub time.
        </p>
      ) : (
        <>
          <p className="mb-2 px-1 font-mono text-[10px] text-vcl-dim">
            Scenario A/B · untreated vs treated at t = {lab.scrubT.toFixed(0)} min
          </p>
          <table className="w-full border-collapse text-left font-mono text-[10.5px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-[0.1em] text-vcl-dim">
                <th className="px-2 py-1.5 font-semibold">Species</th>
                <th className="px-2 py-1.5 font-semibold text-right">Baseline</th>
                <th className="px-2 py-1.5 font-semibold text-right">Treated</th>
                <th className="px-2 py-1.5 font-semibold text-right">Δy</th>
                <th className="px-2 py-1.5 font-semibold text-right">Δ%</th>
              </tr>
            </thead>
            <tbody>
              {focus.map((sym) => {
                const i = Math.min(
                  lab.scrubT,
                  (untreated!.time_steps.length ?? 1) - 1,
                  (treated!.time_steps.length ?? 1) - 1,
                )
                const u = untreated!.nodes[sym]?.[i] ?? 0
                const t = treated!.nodes[sym]?.[i] ?? 0
                const d = t - u
                const pct = u > 1e-6 ? (d / u) * 100 : 0
                return (
                  <tr key={sym} className="border-t border-vcl-border/80 hover:bg-vcl-surface/40">
                    <td className="px-2 py-1.5 font-semibold text-vcl-text">{sym}</td>
                    <td className="px-2 py-1.5 text-right text-vcl-muted">{u.toFixed(3)}</td>
                    <td className="px-2 py-1.5 text-right text-vcl-soft">{t.toFixed(3)}</td>
                    <td
                      className={clsx(
                        'px-2 py-1.5 text-right',
                        d < -0.02
                          ? 'text-coral-action'
                          : d > 0.02
                            ? 'text-emerald-active'
                            : 'text-vcl-dim',
                      )}
                    >
                      {d >= 0 ? '+' : ''}
                      {d.toFixed(3)}
                    </td>
                    <td
                      className={clsx(
                        'px-2 py-1.5 text-right',
                        pct < -2
                          ? 'text-coral-action'
                          : pct > 2
                            ? 'text-emerald-active'
                            : 'text-vcl-dim',
                      )}
                    >
                      {pct >= 0 ? '+' : ''}
                      {pct.toFixed(1)}%
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="mt-2 px-1">
            <TrajectoryChart
              untreatedRun={untreated}
              treatedRun={treated}
              focus={focus.slice(0, 4)}
              scrubT={lab.scrubT}
              loading={lab.busy}
              compact
            />
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Persistent bottom analysis dock — Time-Series / Compare / Organelle / Metabolic tabs + scrub.
 */
export function BottomAnalysisDock() {
  const lab = useLab()
  const [tab, setTab] = useState<BottomTab>('trajectory')

  const focus = useMemo(() => {
    const preset = FOCUS_SERIES[lab.profileId] ?? FOCUS_SERIES.hypoxia
    const fromGraph = lab.nodes.slice(0, 6)
    return Array.from(new Set([...(preset ?? []), ...fromGraph])).slice(0, 6)
  }, [lab.profileId, lab.nodes])

  const tabs: { id: BottomTab; label: string }[] = [
    { id: 'trajectory', label: 'Time-Series Trajectory' },
    { id: 'compare', label: 'Scenario A/B' },
    { id: 'organelle', label: 'Organelle Translocation' },
    { id: 'flux', label: 'Metabolic Flux (FBA)' },
  ]

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-vcl-border px-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={clsx(
              'h-full border-b-2 px-2.5 font-mono text-[10.5px] font-semibold transition',
              tab === t.id
                ? 'border-emerald-active text-vcl-text'
                : 'border-transparent text-vcl-muted hover:text-vcl-text',
            )}
          >
            {t.label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2 pl-2">
          <span className="font-mono text-[10px] text-vcl-dim">t₀</span>
          <input
            type="range"
            min={0}
            max={60}
            step={1}
            value={lab.scrubT}
            disabled={!lab.payload}
            onChange={(e) => lab.setScrubT(Number(e.target.value))}
            className="w-[170px] accent-emerald-active disabled:opacity-40"
          />
          <span className="font-mono text-[10px] text-vcl-dim">t₆₀</span>
          <span className="min-w-[3.5rem] text-right font-mono text-[11px] font-semibold text-emerald-active">
            {lab.scrubT.toFixed(0)} min
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === 'trajectory' ? (
          <div className="h-full p-1">
            <TrajectoryChart
              untreatedRun={lab.untreatedRun}
              treatedRun={lab.treatedRun}
              focus={focus}
              scrubT={lab.scrubT}
              loading={lab.busy}
              compact
            />
          </div>
        ) : null}
        {tab === 'compare' ? <CompareTab /> : null}
        {tab === 'organelle' ? <OrganelleTab /> : null}
        {tab === 'flux' ? <FluxTab /> : null}
      </div>
    </div>
  )
}
