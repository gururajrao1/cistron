/**
 * Publication-ready report exporter — aggregates Lab + spatial + SL + omics
 * into PDF / Markdown via the scientificReport assembler.
 */

import type { LabContextValue } from '../lab/LabContext'
import {
  buildScientificReport,
  captureTopologyCanvas,
  exportReportMarkdown,
  exportReportPdf,
  exportTopologyPng,
  type ReportBundle,
} from '../utils/scientificReport'

export type PublicationReportOptions = {
  includeSpatial?: boolean
  includeMethodology?: boolean
}

/** Capture topology + optional spatial mesh canvases. */
export async function captureReportFigures(): Promise<{
  topologyPng: string | null
  spatialPng: string | null
}> {
  const topologyPng = await captureTopologyCanvas()
  let spatialPng: string | null = null
  const spatial = document.querySelector<HTMLElement>('[data-cistron-export="spatial-mesh"]')
  if (spatial) {
    try {
      const { default: html2canvas } = await import('html2canvas')
      const canvas = await html2canvas(spatial, {
        backgroundColor: '#0b1220',
        scale: Math.min(2, window.devicePixelRatio || 1.5),
        logging: false,
        useCORS: true,
      })
      spatialPng = canvas.toDataURL('image/png')
    } catch (err) {
      console.warn('Spatial mesh capture failed', err)
    }
  }
  return { topologyPng, spatialPng }
}

/** Assemble a publication bundle from live LabContext + optional figures. */
export async function assemblePublicationReport(
  lab: LabContextValue,
  opts?: PublicationReportOptions,
): Promise<ReportBundle> {
  const figures = await captureReportFigures()
  const base = buildScientificReport(lab, { topologyPng: figures.topologyPng })

  const extraSections = []
  if (opts?.includeMethodology !== false) {
    extraSections.push({
      heading: 'Methods (auto-generated)',
      body: [
        'Hill-cube ODEs integrated t0->t60 (Kraeutler logic) with optional omics-conditioned y0.',
        'Synthetic lethality scored via Bliss independence on dual-knockout viability.',
        'Spatial reaction-diffusion (5-point Laplacian) with optional Visium/H&E histology masks and BBB permeability (logP, MW, P-gp).',
        'XAI: GAT attention, SHAP-style node attributions, and client Sobol S_i / S_Ti sensitivity.',
        'Citations: Kraeutler et al. Hill cubes; Bliss (1939) independence; Saltelli et al. global sensitivity; PhysiCell-style continuum substrates.',
      ].join(' '),
      twoColumn: true,
    })
  }

  const sl = lab.topologicalAnalysis?.synthetic_lethal_pairs ?? []
  if (sl.length) {
    extraSections.push({
      heading: 'Synthetic Lethality Findings',
      body: sl
        .slice(0, 10)
        .map(
          (p, i) =>
            `${i + 1}. ${(p.pair ?? []).join(' + ')} - synergy ${Number(p.synergy_score ?? 0).toFixed(3)} - ${
              p.explanation || ''
            }`,
        )
        .join('\n'),
    })
  }

  if (lab.causalHypotheses?.length) {
    extraSections.push({
      heading: 'Causal Hypothesis Cards',
      body: lab.causalHypotheses
        .map(
          (h) =>
            `${h.title}\nPathway: ${h.pathwayCollapse}\nPhenotype: ${h.phenotypicImpact}\nAssay: ${h.suggestedAssay}`,
        )
        .join('\n\n'),
    })
  }

  if (figures.spatialPng) {
    // Attach as topology-adjacent figure note in markdown; PDF uses primary topology slot
    base.markdown += `\n\n## Spatial Microenvironment Mesh\n\n_Figure captured from Spatial Mesh view at export._\n`
  }

  const sections = [...base.sections, ...extraSections]
  const markdown = [
    base.markdown,
    ...extraSections.flatMap((s) => [`## ${s.heading}`, '', s.body, '']),
  ].join('\n')

  return {
    ...base,
    sections,
    markdown,
    topologyPng: figures.topologyPng ?? figures.spatialPng,
  }
}

export async function downloadPublicationPdf(
  lab: LabContextValue,
  opts?: PublicationReportOptions,
): Promise<ReportBundle> {
  const bundle = await assemblePublicationReport(lab, opts)
  await exportReportPdf(bundle)
  return bundle
}

export async function downloadPublicationMarkdown(
  lab: LabContextValue,
  opts?: PublicationReportOptions,
): Promise<ReportBundle> {
  const bundle = await assemblePublicationReport(lab, opts)
  exportReportMarkdown(bundle)
  if (bundle.topologyPng) exportTopologyPng(bundle)
  return bundle
}

export {
  buildScientificReport,
  captureTopologyCanvas,
  exportReportMarkdown,
  exportReportPdf,
  exportTopologyPng,
}
