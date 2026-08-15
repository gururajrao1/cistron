/**
 * Deterministic wet-lab Insight Layer — translates scrubber numbers into
 * plain-English takeaways + Δ badges + lab next steps (not an LLM).
 */

import type { ScrubberPayload } from '../api/types'
import { FOCUS_SERIES, payloadNodeSeries, sampleCompartmentsAt } from '../api/types'
import type { MetabolicFluxPoint, MiniFbaResult } from './metabolicBridge'

export type InsightDirection = 'up' | 'down' | 'flat'

export type InsightDelta = {
  label: string
  /** Percent change vs baseline (can be negative). */
  pct: number
  direction: InsightDirection
  /** Optional absolute note, e.g. "peak at 18 min" */
  detail?: string
}

export type InsightBand = {
  /** Y-axis low (0–1 activity scale). */
  y0: number
  y1: number
  label: string
  kind: 'elevated' | 'caution' | 'neutral'
}

export type DockInsight = {
  tab: 'trajectory' | 'organelle' | 'flux' | 'compare'
  headline: string
  deltas: InsightDelta[]
  labHint: string
  bands?: InsightBand[]
}

function pctChange(now: number, base: number): number {
  if (Math.abs(base) < 1e-6) {
    if (Math.abs(now) < 1e-6) return 0
    return now > base ? 100 : -100
  }
  return ((now - base) / Math.abs(base)) * 100
}

function directionFromPct(pct: number, deadband = 5): InsightDirection {
  if (pct > deadband) return 'up'
  if (pct < -deadband) return 'down'
  return 'flat'
}

function valueAt(
  series: number[] | undefined,
  times: number[] | undefined,
  t: number,
): number {
  if (!series?.length || !times?.length) return 0
  let i = 0
  if (t <= times[0]!) i = 0
  else if (t >= times[times.length - 1]!) i = times.length - 1
  else {
    while (i < times.length - 1 && times[i + 1]! < t) i += 1
  }
  return series[i] ?? 0
}

function peakInfo(series: number[], times: number[]): { t: number; y: number; i: number } {
  let bestI = 0
  let bestY = series[0] ?? 0
  for (let i = 1; i < series.length; i++) {
    const y = series[i] ?? 0
    if (y > bestY) {
      bestY = y
      bestI = i
    }
  }
  return { t: times[bestI] ?? 0, y: bestY, i: bestI }
}

function isTransient(series: number[], peakI: number): boolean {
  if (!series.length || peakI >= series.length - 2) return false
  const peak = series[peakI] ?? 0
  const end = series[series.length - 1] ?? 0
  const start = series[0] ?? 0
  // Peak rose meaningfully and later fell most of the way back toward start
  const rise = peak - start
  if (rise < 0.08) return false
  return end < peak - 0.4 * rise
}

export type InsightContext = {
  active: ScrubberPayload | null
  untreated: ScrubberPayload | null
  treated: ScrubberPayload | null
  scrubT: number
  profileId: string
  focus?: string[]
  metabolic?: MetabolicFluxPoint | null
  metabolicBaseline?: MetabolicFluxPoint | null
  fba?: MiniFbaResult | null
}

function focusGenes(ctx: InsightContext): string[] {
  if (ctx.focus?.length) return ctx.focus
  const preset = FOCUS_SERIES[ctx.profileId] ?? FOCUS_SERIES.hypoxia ?? ['HIF1A', 'VEGFA']
  const nodes = payloadNodeSeries(ctx.active)
  const fromGraph = Object.keys(nodes).slice(0, 6)
  return Array.from(new Set([...preset, ...fromGraph])).slice(0, 6)
}

/** Trajectory tab: timing + transient vs sustained + treated Δ. */
export function buildTrajectoryInsight(ctx: InsightContext): DockInsight {
  const active = ctx.treated ?? ctx.active ?? ctx.untreated
  if (!active) {
    return {
      tab: 'trajectory',
      headline: 'Run a simulation to see when pathway signals peak and whether they hold.',
      deltas: [],
      labHint: 'Start with Hypoxia in Studio, then scrub time to plan Western / RNA sample points.',
    }
  }

  const nodes = payloadNodeSeries(active)
  const times = active.time_steps
  const focus = focusGenes(ctx).filter((s) => nodes[s]?.length)
  const primary =
    focus.find((s) => s === 'HIF1A' || s === 'VEGFA' || s === 'EPAS1') ?? focus[0] ?? 'HIF1A'
  const series = nodes[primary] ?? []
  const peak = peakInfo(series, times)
  const transient = isTransient(series, peak.i)
  const yNow = valueAt(series, times, ctx.scrubT)
  const y0 = series[0] ?? 0
  const vsStart = pctChange(yNow, y0)

  const deltas: InsightDelta[] = [
    {
      label: `${primary} vs t₀`,
      pct: vsStart,
      direction: directionFromPct(vsStart),
      detail: `now ${yNow.toFixed(2)}`,
    },
    {
      label: `${primary} peak`,
      pct: pctChange(peak.y, y0),
      direction: directionFromPct(pctChange(peak.y, y0)),
      detail: `at ~${peak.t.toFixed(0)} min`,
    },
  ]

  const basePayload = ctx.untreated
  const treatedPayload = ctx.treated
  if (basePayload && treatedPayload) {
    const u = valueAt(payloadNodeSeries(basePayload)[primary], basePayload.time_steps, ctx.scrubT)
    const t = valueAt(payloadNodeSeries(treatedPayload)[primary], treatedPayload.time_steps, ctx.scrubT)
    const p = pctChange(t, u)
    deltas.push({
      label: `${primary} treated vs baseline`,
      pct: p,
      direction: directionFromPct(p),
    })
  }

  const headline = transient
    ? `${primary} spikes near ${peak.t.toFixed(0)} min then falls back — response looks transient (possible adaptation / resistance window).`
    : `${primary} reaches ~${peak.y.toFixed(2)} by ${peak.t.toFixed(0)} min and stays elevated — sustained pathway drive through the horizon.`

  const labHint = transient
    ? `Sample around t≈${peak.t.toFixed(0)} min (peak) and again near t₆₀ to catch rebound; a single late timepoint may miss the drug effect.`
    : `Plan fractionation / Western near t≈${peak.t.toFixed(0)} min when ${primary} is highest; late samples still reflect the elevated state.`

  const bands: InsightBand[] = [
    {
      y0: 0.65,
      y1: 1.05,
      label: 'Elevated pathway activity (illustrative)',
      kind: 'elevated',
    },
  ]

  return { tab: 'trajectory', headline, deltas: deltas.slice(0, 4), labHint, bands }
}

/** Organelle tab: nuclear fraction / location = function. */
export function buildOrganelleInsight(ctx: InsightContext): DockInsight {
  const active = ctx.active ?? ctx.treated ?? ctx.untreated
  const at = sampleCompartmentsAt(active, ctx.scrubT)
  const at0 = sampleCompartmentsAt(active, 0)

  if (!at) {
    return {
      tab: 'organelle',
      headline: 'No server compartment trajectories yet — run Studio to load HIF1A cyto→nuc pools.',
      deltas: [],
      labHint: 'After simulate, check whether HIF1A reaches the nucleus (DNA) or stays cytoplasmic.',
    }
  }

  const frac = at.nucleus / Math.max(1e-6, at.cytoplasm + at.nucleus)
  const frac0 = at0
    ? at0.nucleus / Math.max(1e-6, at0.cytoplasm + at0.nucleus)
    : frac
  const vsT0 = pctChange(frac, frac0)

  const deltas: InsightDelta[] = [
    {
      label: 'Nuclear fraction',
      pct: frac * 100,
      direction: frac >= 0.45 ? 'up' : frac <= 0.25 ? 'down' : 'flat',
      detail: `${(frac * 100).toFixed(0)}% of pool in nucleus`,
    },
    {
      label: 'Nuc fraction vs t₀',
      pct: vsT0,
      direction: directionFromPct(vsT0),
    },
  ]

  let treatedNote = ''
  if (ctx.untreated && ctx.treated) {
    const u = sampleCompartmentsAt(ctx.untreated, ctx.scrubT)
    const t = sampleCompartmentsAt(ctx.treated, ctx.scrubT)
    if (u && t) {
      const uf = u.nucleus / Math.max(1e-6, u.cytoplasm + u.nucleus)
      const tf = t.nucleus / Math.max(1e-6, t.cytoplasm + t.nucleus)
      const p = pctChange(tf, uf)
      deltas.push({
        label: 'Nucleus treated vs baseline',
        pct: p,
        direction: directionFromPct(p),
      })
      if (p < -15) {
        treatedNote = ' Perturbation appears to keep more HIF1A out of the nucleus.'
      } else if (p > 15) {
        treatedNote = ' Perturbation increases nuclear HIF1A relative to baseline.'
      }
    }
  }

  const inNucleus = frac >= 0.4
  const headline = inNucleus
    ? `HIF1A is nucleus-enriched at t=${ctx.scrubT.toFixed(0)} min (~${(frac * 100).toFixed(0)}% nuclear) — transcription-competent localization.${treatedNote}`
    : `HIF1A is mostly cytoplasmic at t=${ctx.scrubT.toFixed(0)} min (~${(frac * 100).toFixed(0)}% nuclear) — high total protein would still be ineffective without nuclear entry.${treatedNote}`

  const labHint = inNucleus
    ? 'Validate with nuclear fractionation or immunofluorescence (HIF1A / DAPI co-localization) near this scrub time.'
    : 'If you expected HIF activity, check PHD/VHL or import blockade; total-lysate Western alone can miss a cytoplasmic trap.'

  return { tab: 'organelle', headline, deltas: deltas.slice(0, 4), labHint }
}

/** Flux tab: ATP / lactate phenotype language. */
export function buildFluxInsight(ctx: InsightContext): DockInsight {
  const point = ctx.metabolic
  if (!point) {
    return {
      tab: 'flux',
      headline: 'Run a simulation to estimate glycolytic vs oxidative metabolic phenotype.',
      deltas: [],
      labHint: 'After simulate, compare ATP yield and lactate export — Warburg-like cells spit lactate while ATP stays greedy.',
    }
  }

  const base = ctx.metabolicBaseline
  const atp = point.atpYield
  const lac = point.lactateExport
  const atp0 = base?.atpYield ?? atp
  const lac0 = base?.lactateExport ?? lac
  // Prefer untreated metabolic baseline when available; else vs early scrub proxy via baseline point
  const atpPct = pctChange(atp, atp0)
  const lacPct = pctChange(lac, lac0)

  const deltas: InsightDelta[] = [
    {
      label: 'ATP yield',
      pct: base ? atpPct : 0,
      direction: base ? directionFromPct(atpPct) : 'flat',
      detail: atp.toFixed(3),
    },
    {
      label: 'Lactate export',
      pct: base ? lacPct : 0,
      direction: base ? directionFromPct(lacPct) : 'flat',
      detail: `${lac.toFixed(2)} a.u.`,
    },
  ]

  if (ctx.fba) {
    deltas.push({
      label: 'FBA-lite objective',
      pct: 0,
      direction: 'flat',
      detail: `obj ${ctx.fba.objective.toFixed(2)} (illustrative)`,
    })
  }

  const warburgLean =
    (base ? lacPct > 12 && atpPct < 8 : lac > atp * 1.2) || (lac > 0.35 && atp < lac)

  let headline: string
  if (base && atpPct < -20) {
    headline = `ATP yield is down ${Math.abs(atpPct).toFixed(0)}% vs baseline — phenotype reads energy-starved at this scrub time.`
  } else if (warburgLean) {
    headline =
      'Lactate-forward / glycolytic lean (Warburg-like proxy): cells favor lactate export over clean oxidative ATP.'
  } else if (base && lacPct < -15 && atpPct >= -5) {
    headline =
      'Lactate down while ATP holds — metabolism looks less glycolytic / more oxidative than baseline.'
  } else {
    headline = `Metabolic bridge at t=${ctx.scrubT.toFixed(0)} min: ATP=${atp.toFixed(2)}, lactate=${lac.toFixed(2)} (illustrative, not COBRA FBA).`
  }

  const labHint = warburgLean
    ? 'In vitro: check media lactate / ECAR; if testing a drug, ask whether lactate falls without collapsing viability.'
    : 'Pair OCR / ECAR or media lactate with ATP assays at this timepoint to confirm the simulated phenotype.'

  return { tab: 'flux', headline, deltas: deltas.slice(0, 4), labHint }
}

/** Compare tab strip — already Δ-heavy; short summary. */
export function buildCompareInsight(ctx: InsightContext): DockInsight {
  if (!ctx.untreated || !ctx.treated) {
    return {
      tab: 'compare',
      headline: 'Apply a knockout or titration, then re-run to compare treated vs baseline.',
      deltas: [],
      labHint: 'Scenario A/B answers: did the perturbation move the readout enough to matter in culture?',
    }
  }

  const focus = focusGenes(ctx)
  const primary = focus[0] ?? 'HIF1A'
  const u = valueAt(
    payloadNodeSeries(ctx.untreated)[primary],
    ctx.untreated.time_steps,
    ctx.scrubT,
  )
  const t = valueAt(
    payloadNodeSeries(ctx.treated)[primary],
    ctx.treated.time_steps,
    ctx.scrubT,
  )
  const p = pctChange(t, u)
  const dir = directionFromPct(p)

  const headline =
    dir === 'flat'
      ? `At t=${ctx.scrubT.toFixed(0)} min, ${primary} is nearly unchanged vs baseline (${p >= 0 ? '+' : ''}${p.toFixed(0)}%).`
      : `At t=${ctx.scrubT.toFixed(0)} min, ${primary} is ${dir === 'down' ? 'down' : 'up'} ${Math.abs(p).toFixed(0)}% vs untreated baseline.`

  return {
    tab: 'compare',
    headline,
    deltas: [
      {
        label: `${primary} Δ%`,
        pct: p,
        direction: dir,
      },
    ],
    labHint:
      dir === 'flat'
        ? 'If you expected a big shift, increase dose / expand knockouts or check a later scrub time.'
        : `Follow up in culture with a ${primary} readout (qPCR / Western) at ~${ctx.scrubT.toFixed(0)} min post-stimulus.`,
  }
}
