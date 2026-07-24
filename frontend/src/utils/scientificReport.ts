import { jsPDF } from 'jspdf'
import html2canvas from 'html2canvas'
import type { LabContextValue } from '../lab/LabContext'
import { resolveOmicsProvenance } from '../api/types'
import { rankInhibitionEfficacy } from '../components/studio/EfficacyCard'

export type ReportSection = {
  heading: string
  body: string
  /** Render topology PNG under this heading when available */
  embedTopology?: boolean
  twoColumn?: boolean
}

export type ReportBundle = {
  title: string
  filenameBase: string
  markdown: string
  sections: ReportSection[]
  topologyPng?: string | null
}

function terminalY(
  payload: NonNullable<LabContextValue['payload']>,
  sym: string,
): number {
  const series = payload.nodes[sym]
  if (!series?.length) return 0
  return series[series.length - 1] ?? 0
}

function initialY(
  payload: NonNullable<LabContextValue['payload']>,
  sym: string,
): number {
  const series = payload.nodes[sym]
  if (!series?.length) return 0
  return series[0] ?? 0
}

function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function downloadDataUrl(filename: string, dataUrl: string) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}

/** Capture Cytoscape host (or nearest topology panel) as PNG data URL. */
export async function captureTopologyCanvas(): Promise<string | null> {
  const el =
    document.querySelector<HTMLElement>('[data-cistron-export="topology"]') ??
    document.querySelector<HTMLElement>('.lab-grid-panel')
  if (!el) return null
  try {
    const canvas = await html2canvas(el, {
      backgroundColor: '#0b1220',
      scale: Math.min(2, window.devicePixelRatio || 1.5),
      logging: false,
      useCORS: true,
    })
    return canvas.toDataURL('image/png')
  } catch (err) {
    console.warn('Topology capture failed', err)
    return null
  }
}

/** Assemble manuscript sections from live LabContext. */
export function buildScientificReport(
  lab: LabContextValue,
  opts?: { topologyPng?: string | null },
): ReportBundle {
  const scenario = lab.controls.conditionQuery || 'Untitled scenario'
  const provenance = lab.profileId || 'cistron-unresolved'
  const simId = lab.payload?.simulation_id ?? '-'
  const nNodes = lab.graph ? Object.keys(lab.graph.nodes).length : 0
  const nEdges = lab.graph?.edges.length ?? 0
  const graphProv = (lab.graph?.provenance ?? {}) as Record<string, unknown>
  const pathwayId =
    typeof graphProv.pathway_id === 'string' ? graphProv.pathway_id : null
  const pathwayName =
    typeof graphProv.pathway_name === 'string' ? graphProv.pathway_name : null

  const omics = lab.activeOmicsProfile
  const omicsProv = omics ? resolveOmicsProvenance(omics) : null
  const fit =
    lab.omicsAlignmentScore != null ? `${lab.omicsAlignmentScore.toFixed(1)}%` : '-'

  const regs = lab.prioritization?.master_regulators ?? []
  const focusSyms = regs.slice(0, 8).map(([g]) => g)
  if (!focusSyms.length && lab.payload) {
    focusSyms.push(...Object.keys(lab.payload.nodes).slice(0, 8))
  }

  const trajRows =
    lab.payload && focusSyms.length
      ? focusSyms.map((sym) => {
          const y0 = initialY(lab.payload!, sym)
          const y60 = terminalY(lab.payload!, sym)
          return { sym, y0, y60, dy: y60 - y0 }
        })
      : []

  const exclude = new Set(Object.keys(lab.perturbations).map((s) => s.toUpperCase()))
  const efficacy =
    lab.untreatedRun && lab.treatedRun
      ? rankInhibitionEfficacy(lab.untreatedRun, lab.treatedRun, exclude, 8)
      : []

  const slPairs = lab.topologicalAnalysis?.synthetic_lethal_pairs ?? []
  const bottlenecks = lab.topologicalAnalysis?.bottlenecks ?? []
  const pertEntries = Object.entries(lab.perturbations).sort(([a], [b]) =>
    a.localeCompare(b),
  )
  const selected = lab.selectedNode
  const scientist = lab.scientist?.brief ?? ''
  const causal = lab.reason?.brief ?? ''
  const paths = lab.reason?.context?.extracted_paths ?? []

  const abstractParts = [
    `We analysed the disease scenario "${scenario}" (provenance ${provenance})`,
    `on a causal activity network of ${nNodes} nodes and ${nEdges} edges.`,
    lab.payload
      ? `Hill-cube ODEs were integrated from t0 to t60 (${simId}).`
      : 'No ODE trajectory was available at export time.',
    omics
      ? `Omics profile ${omics.sample_name} (${omics.condition}; ${omicsProv}) yielded an R2/fit score of ${fit}.`
      : null,
    regs[0]
      ? `Graph-attention prioritisation nominated ${regs[0][0]} as the top master regulator (Si=${regs[0][1].toFixed(3)}).`
      : null,
    pertEntries.length
      ? `${pertEntries.length} interactive perturbation(s) were applied prior to export.`
      : null,
  ]
    .filter(Boolean)
    .join(' ')

  const topologyBody = [
    `The active Cytoscape topology comprises ${nNodes} proteins and ${nEdges} signed activity-flow edges.`,
    opts?.topologyPng
      ? 'Figure: live canvas snapshot captured at export.'
      : 'Topology image unavailable - open Simulation Studio before export to capture the canvas.',
    '',
    'Topological bottlenecks:',
    bottlenecks.length
      ? bottlenecks
          .slice(0, 8)
          .map(
            (b) =>
              `- ${b.node} - betweenness ${Number(b.betweenness).toFixed(3)}, degree ${Number(
                b.hub_degree,
              ).toFixed(2)}, PageRank ${Number(b.pagerank).toFixed(3)} (${b.role})`,
          )
          .join('\n')
      : '- None available in the current run.',
    '',
    'Causal paths:',
    paths.length
      ? paths
          .slice(0, 3)
          .map((p, i) => `${i + 1}. ${(p.nodes ?? []).join(' -> ')}`)
          .join('\n')
      : '- No extracted causal paths.',
  ].join('\n')

  const trajBody = [
    'Hill-cube integration over t0 -> t60 (minutes). Terminal dy relative to basal y0:',
    '',
    trajRows.length
      ? trajRows
          .map(
            (r) =>
              `- ${r.sym}: y0=${r.y0.toFixed(3)}, y60=${r.y60.toFixed(3)}, dy60=${
                r.dy >= 0 ? '+' : ''
              }${r.dy.toFixed(3)}`,
          )
          .join('\n')
      : '- No trajectory series available.',
    '',
    'Inhibition efficacy (untreated vs treated):',
    efficacy.length
      ? efficacy
          .map(
            (h) =>
              `- ${h.symbol}: yU=${h.yU.toFixed(3)}, yT=${h.yT.toFixed(3)}, d%=${
                h.pct >= 0 ? '+' : ''
              }${h.pct.toFixed(1)}%`,
          )
          .join('\n')
      : '- Apply a knockout/titration to populate untreated vs treated dy60.',
  ].join('\n')

  const targetBody = [
    'Master regulators (GAT):',
    regs.length
      ? regs
          .slice(0, 10)
          .map(([g, s], i) => `${i + 1}. ${g} - Si = ${s.toFixed(4)}`)
          .join('\n')
      : '- No prioritisation scores yet.',
    '',
    'Active perturbations:',
    pertEntries.length
      ? pertEntries
          .map(([sym, v]) => `- ${sym} - y=${v.toFixed(2)}${v <= 1e-6 ? ' (KO)' : ''}`)
          .join('\n')
      : '- None.',
    '',
    'Synthetic lethality / dual-target screen:',
    slPairs.length
      ? slPairs
          .slice(0, 8)
          .map(
            (p) =>
              `- ${(p.pair ?? []).join(' + ')} - synergy ${Number(p.synergy_score ?? 0).toFixed(3)} - ${
                p.explanation || ''
              }`,
          )
          .join('\n')
      : '- Run Dual Screen from Studio to populate SL rankings.',
    '',
    'Inspected 3D structural target:',
    selected
      ? [
          `- Selected node: ${selected}`,
          `- UniProt: https://www.uniprot.org/uniprotkb?query=gene:${encodeURIComponent(selected)}+AND+organism_id:9606`,
          `- 3D Structure workspace: /biophysics?symbol=${encodeURIComponent(selected)}`,
          `- AlphaFold search: https://alphafold.ebi.ac.uk/search/text/${encodeURIComponent(selected)}`,
        ].join('\n')
      : '- No node selected - open 3D Structure after choosing a target for PDB / UniProt accession.',
  ].join('\n')

  const provenanceBody = [
    `Engine: Cistron Virtual Cellular Lab (Hill-cube ODE / GAT / XAI / BioReasoner).`,
    `Scenario provenance ID: ${provenance}.`,
    omicsProv ? `Omics provenance: ${omicsProv} / fit ${fit}.` : null,
    pathwayId
      ? `Reactome pathway: ${pathwayId}${pathwayName ? ` (${pathwayName})` : ''}.`
      : null,
    `Graph source: ${String(graphProv.source ?? graphProv.profile_id ?? 'lab')}.`,
    `Simulation latency: ${lab.latencyMs != null ? `${lab.latencyMs.toFixed(1)} ms` : '-'}.`,
    scientist ? `\nAI Scientist:\n${scientist}` : null,
    causal ? `\nCausal BioReasoner:\n${causal}` : null,
  ]
    .filter(Boolean)
    .join('\n')

  const sections: ReportSection[] = [
    { heading: 'Abstract', body: abstractParts || 'Insufficient live lab state.', twoColumn: true },
    {
      heading: 'Network Topology',
      body: topologyBody,
      embedTopology: true,
    },
    { heading: 'Biophysical Trajectory Analysis', body: trajBody },
    { heading: 'Target Identification', body: targetBody },
    { heading: 'Provenance', body: provenanceBody, twoColumn: true },
  ]

  const md = [
    `# Cistron Automated Scientific Report`,
    ``,
    `**Title.** Dynamic interactome analysis of ${scenario}`,
    ``,
    `| Field | Value |`,
    `| --- | --- |`,
    `| Scenario | ${scenario} |`,
    `| Provenance | \`${provenance}\` |`,
    `| Simulation | \`${simId}\` |`,
    `| Network | ${nNodes} nodes / ${nEdges} edges |`,
    `| Exported | ${new Date().toISOString()} |`,
    pathwayId ? `| Reactome | ${pathwayId}${pathwayName ? ` (${pathwayName})` : ''} |` : null,
    omics ? `| Omics | ${omics.sample_name} / ${omics.condition} / ${omicsProv} / fit ${fit} |` : null,
    ``,
    ...sections.flatMap((s) => [`## ${s.heading}`, ``, s.body, ``]),
    `---`,
    ``,
    `*Generated automatically by Cistron Report Export. Not a peer-reviewed manuscript.*`,
    ``,
  ]
    .filter((line) => line != null)
    .join('\n')

  const slug = provenance.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase()
  return {
    title: `Dynamic interactome analysis of ${scenario}`,
    filenameBase: `cistron_report_${slug}_${Date.now()}`,
    markdown: md,
    sections,
    topologyPng: opts?.topologyPng ?? null,
  }
}

function toPdfText(raw: string): string {
  return String(raw ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/[₀]/g, '0')
    .replace(/[₁]/g, '1')
    .replace(/[₂]/g, '2')
    .replace(/[₃]/g, '3')
    .replace(/[₄]/g, '4')
    .replace(/[₅]/g, '5')
    .replace(/[₆]/g, '6')
    .replace(/[₇]/g, '7')
    .replace(/[₈]/g, '8')
    .replace(/[₉]/g, '9')
    .replace(/[ᵢ]/g, 'i')
    .replace(/[ⱼ]/g, 'j')
    .replace(/Δ/g, 'd')
    .replace(/δ/g, 'd')
    .replace(/Σ/g, 'Sum')
    .replace(/→/g, '->')
    .replace(/←/g, '<-')
    .replace(/↔/g, '<->')
    .replace(/×/g, 'x')
    .replace(/·/g, '-')
    .replace(/•/g, '-')
    .replace(/[—–−]/g, '-')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/…/g, '...')
    .replace(/≤/g, '<=')
    .replace(/≥/g, '>=')
    .replace(/[^\x09\x0A\x0D\x20-\x7E]/g, '')
}

function wrapText(
  doc: jsPDF,
  text: string,
  x: number,
  y: number,
  maxW: number,
  lineH: number,
): number {
  const safe = toPdfText(text)
  if (!safe.trim()) return y
  // Always coerce to string[]; never pass a raw string that jsPDF may iterate as chars.
  const wrapped = doc.splitTextToSize(safe, maxW)
  const lines: string[] = Array.isArray(wrapped)
    ? wrapped.map((l) => String(l))
    : [String(wrapped)]
  for (const line of lines) {
    if (!line) continue
    if (y > 282) {
      doc.addPage()
      y = 18
    }
    // Third arg as options object avoids the array-of-chars overload footgun.
    doc.text(line, x, y, { baseline: 'top' })
    y += lineH
  }
  return y
}

/** Render manuscript PDF via jsPDF (ASCII-safe; built-in fonts lack Unicode). */
export async function exportReportPdf(bundle: ReportBundle): Promise<void> {
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const margin = 14
  const colGap = 6
  const colW = (pageW - margin * 2 - colGap) / 2
  let y = 18

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  y = wrapText(doc, bundle.title, margin, y, pageW - margin * 2, 6)
  y += 2
  doc.setFont('helvetica', 'italic')
  doc.setFontSize(9)
  doc.setTextColor(70)
  y = wrapText(
    doc,
    'Cistron Virtual Cellular Laboratory - Automated Scientific Report',
    margin,
    y,
    pageW - margin * 2,
    4.5,
  )
  doc.setTextColor(0)
  y += 6

  for (const section of bundle.sections) {
    if (y > 255) {
      doc.addPage()
      y = 18
    }
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.text(toPdfText(section.heading), margin, y, { baseline: 'top' })
    y += 6

    if (section.embedTopology && bundle.topologyPng) {
      try {
        const imgW = pageW - margin * 2
        const imgH = 68
        if (y + imgH > 280) {
          doc.addPage()
          y = 18
        }
        doc.addImage(bundle.topologyPng, 'PNG', margin, y, imgW, imgH)
        y += imgH + 5
      } catch (err) {
        console.warn('PDF topology image embed failed', err)
      }
    }

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    const body = toPdfText(section.body)

    if (section.twoColumn && body.length > 280) {
      const mid = Math.ceil(body.length / 2)
      let splitAt = body.indexOf('. ', mid)
      if (splitAt < 0) splitAt = body.indexOf('\n', mid)
      if (splitAt < 0) splitAt = mid
      else splitAt += 1
      const left = body.slice(0, splitAt).trim()
      const right = body.slice(splitAt).trim()
      const y0 = y
      const yL = wrapText(doc, left, margin, y0, colW, 4.2)
      const yR = wrapText(doc, right, margin + colW + colGap, y0, colW, 4.2)
      y = Math.max(yL, yR) + 5
    } else {
      // Prefer line-oriented layout for lists / tables of metrics
      for (const para of body.split('\n')) {
        y = wrapText(doc, para.length ? para : ' ', margin, y, pageW - margin * 2, 4.2)
      }
      y += 4
    }
  }

  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8)
  doc.setTextColor(100)
  wrapText(
    doc,
    'Generated automatically by Cistron Report Export. Not a peer-reviewed manuscript.',
    margin,
    Math.min(y + 2, 285),
    pageW - margin * 2,
    3.8,
  )

  doc.save(`${bundle.filenameBase}.pdf`)
}

export function exportReportMarkdown(bundle: ReportBundle): void {
  downloadText(`${bundle.filenameBase}.md`, bundle.markdown, 'text/markdown;charset=utf-8')
}

export function exportTopologyPng(bundle: ReportBundle): void {
  if (!bundle.topologyPng) return
  downloadDataUrl(`${bundle.filenameBase}_topology.png`, bundle.topologyPng)
}
