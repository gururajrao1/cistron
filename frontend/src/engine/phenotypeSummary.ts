/**
 * Rule-based phenotype executive summary + wet-lab protocol from scrubber SoT.
 * Deterministic — not an LLM.
 */

import type { ScrubberPayload, TopologicalAnalysis } from '../api/types'
import { FOCUS_SERIES, payloadNodeSeries, sampleCompartmentsAt } from '../api/types'
import {
  metabolicAtTime,
  simulateMetabolicBridge,
  type MetabolicFluxPoint,
} from '../engine/metabolicBridge'
import { buildTrajectoryInsight } from '../engine/insightRules'

export type PhenotypeSentence = {
  tone: 'good' | 'warn' | 'bad' | 'neutral'
  text: string
}

export type PhenotypeSummary = {
  sentences: PhenotypeSentence[]
  /** 0–100 ATP fill for BatteryGauge */
  atpPercent: number
  /** 0–1 lactate acid meter */
  lactateLevel: number
  /** Bliss-like synergy score if available */
  blissScore: number | null
  cyto: number
  nuc: number
  peakTimeMin: number | null
  peakGene: string | null
}

function pctDrop(now: number, base: number): number {
  if (Math.abs(base) < 1e-9) return 0
  return ((base - now) / Math.abs(base)) * 100
}

function metabolicPoint(
  payload: ScrubberPayload | null,
  t: number,
): MetabolicFluxPoint | null {
  if (!payload) return null
  try {
    return metabolicAtTime(simulateMetabolicBridge(payload), t)
  } catch {
    return null
  }
}

export function buildPhenotypeSummary(input: {
  active: ScrubberPayload | null
  untreated: ScrubberPayload | null
  scrubT: number
  profileId: string
  topo?: TopologicalAnalysis | null
  focus?: string[]
}): PhenotypeSummary {
  const { active, untreated, scrubT, profileId, topo } = input
  const sentences: PhenotypeSentence[] = []

  const point = metabolicPoint(active, scrubT)
  const basePoint = metabolicPoint(untreated ?? active, scrubT)
  const atp = point?.atpYield ?? 0
  const lac = point?.lactateExport ?? 0
  const atp0 = basePoint?.atpYield ?? atp
  const lac0 = basePoint?.lactateExport ?? lac

  // Normalize ATP to 0–100 for gauge (soft cap)
  const atpPercent = Math.max(0, Math.min(100, (atp / Math.max(0.15, atp0 || 0.4)) * 55))
  const lactateLevel = Math.max(0, Math.min(1, lac / Math.max(0.8, lac0 * 1.5, 0.5)))

  const drop = pctDrop(atp, atp0)
  if (drop > 40) {
    sentences.push({
      tone: 'bad',
      text: 'Cell starvation risk: tumor energy (ATP proxy) is severely depleted versus baseline.',
    })
  } else if (drop > 15) {
    sentences.push({
      tone: 'warn',
      text: 'Energy economy is stressed — ATP yield is meaningfully lower than the untreated baseline.',
    })
  } else if (lac > lac0 * 1.2 && lac > 0.25) {
    sentences.push({
      tone: 'warn',
      text: 'Warburg-leaning metabolism: lactate export is elevated relative to baseline oxidative capacity.',
    })
  } else if (point) {
    sentences.push({
      tone: 'neutral',
      text: 'Metabolic bridge remains near baseline — no strong starvation or lactate surge at this scrub time.',
    })
  }

  const comp = sampleCompartmentsAt(active, scrubT)
  const cyto = comp?.cytoplasm ?? 0.45
  const nuc = comp?.nucleus ?? 0.1
  const nucFrac = nuc / Math.max(1e-6, cyto + nuc)
  if (comp) {
    if (nucFrac >= 0.4) {
      sentences.push({
        tone: 'warn',
        text: 'HIF1A is nucleus-enriched — transcription-competent localization that can drive hypoxic gene programs.',
      })
    } else {
      sentences.push({
        tone: 'good',
        text: 'HIF1A remains mostly cytoplasmic — high total protein would still be ineffective without nuclear entry.',
      })
    }
  }

  const sl = topo?.synthetic_lethal_pairs?.[0]
  const blissScore =
    sl && typeof sl.synergy_score === 'number' ? Number(sl.synergy_score) : null
  if (blissScore != null && blissScore > 0.1) {
    sentences.push({
      tone: 'good',
      text: `Strong synergistic inhibition signal (S≈${blissScore.toFixed(2)}) on ${sl!.pair?.join(' + ') ?? 'pair'} — partners enhance each other's efficacy.`,
    })
  } else if (blissScore != null && blissScore < -0.1) {
    sentences.push({
      tone: 'bad',
      text: `Antagonistic combo signal (S≈${blissScore.toFixed(2)}) — partners may cancel rather than cooperate.`,
    })
  }

  const traj = buildTrajectoryInsight({
    active,
    untreated,
    treated: null,
    scrubT,
    profileId,
    focus: input.focus ?? FOCUS_SERIES[profileId] ?? FOCUS_SERIES.hypoxia,
  })
  const peakDelta = traj.deltas.find((d) => d.label.includes('peak'))
  const peakGene =
    traj.deltas[0]?.label.split(' ')[0] ??
    (FOCUS_SERIES[profileId] ?? ['HIF1A'])[0] ??
    'HIF1A'
  let peakTimeMin: number | null = null
  if (peakDelta?.detail) {
    const m = /~?(\d+)\s*min/.exec(peakDelta.detail)
    if (m) peakTimeMin = Number(m[1])
  }
  if (peakTimeMin == null && active) {
    const nodes = payloadNodeSeries(active)
    const series = nodes[peakGene]
    if (series?.length && active.time_steps.length) {
      let bi = 0
      for (let i = 1; i < series.length; i++) {
        if ((series[i] ?? 0) > (series[bi] ?? 0)) bi = i
      }
      peakTimeMin = active.time_steps[bi] ?? null
    }
  }

  if (sentences.length < 3) {
    sentences.push({
      tone: 'neutral',
      text:
        peakTimeMin != null
          ? `${peakGene} activity peaks near t≈${peakTimeMin.toFixed(0)} min — use that window for pathway readouts.`
          : 'Run Studio to populate timing, localization, and metabolic phenotype summaries.',
    })
  }

  return {
    sentences: sentences.slice(0, 3),
    atpPercent,
    lactateLevel,
    blissScore,
    cyto,
    nuc,
    peakTimeMin,
    peakGene,
  }
}

export type WetLabProtocol = {
  assayTiming: string
  suggestedTargets: string
  localization: string
}

export function buildWetLabProtocol(summary: PhenotypeSummary, profileId: string): WetLabProtocol {
  const gene = summary.peakGene ?? (FOCUS_SERIES[profileId] ?? ['HIF1A'])[0] ?? 'HIF1A'
  const t = summary.peakTimeMin
  const hours = t != null ? (t / 60).toFixed(1) : '—'
  const assayTiming =
    t != null
      ? `Assay timing: take cell lysates at t≈${t.toFixed(0)} min (~${hours} h) when ${gene} peaks.`
      : 'Assay timing: run a simulation first to lock a peak sample time for lysates / RNA.'

  const suggestedTargets = `Suggested targets: probe phospho-${gene} and total ${gene}; add VEGFA / SLC2A1 if hypoxia-driven.`

  const nucFrac = summary.nuc / Math.max(1e-6, summary.cyto + summary.nuc)
  const localization =
    nucFrac >= 0.4
      ? 'Localization check: confirm nuclear HIF1A by fractionation or IF (DAPI co-localization) at the peak window.'
      : 'Localization check: if pathway activity is expected, verify HIF1A is not trapped in cytoplasm before trusting total-lysate Westerns.'

  return { assayTiming, suggestedTargets, localization }
}
