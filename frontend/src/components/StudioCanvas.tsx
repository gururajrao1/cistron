import { useMemo } from 'react'
import { Loader2 } from 'lucide-react'
import { GlassCard } from './GlassCard'
import type { PresetDetail, ScrubberPayload } from '../api/types'
import { FOCUS_SERIES } from '../api/types'
import { lerpAtTime } from '../api/client'
import { useLab } from '../lab/LabContext'
import { resolveOmicsProvenance } from '../api/types'
import { TrajectoryChart } from './studio/TrajectoryChart'
import { NetworkGraphSvg, type GraphEdgeView } from './studio/NetworkGraphSvg'
import { classifyEdgeKind } from '../engine/edgeClassification'
import { stepHif1aTranslocation } from './studio/OrganelleCompartments'

/** Hard cap — never hand the stage a huge graph. */
const MAX_CANVAS_NODES = 40

/** Cell-surface receptors & environmental triggers. */
const SURFACE = new Set([
  'EGF', 'EGFR', 'O2', 'ROS', 'TNF', 'TNFR', 'IL6', 'INS',
  'INSULIN', 'WNT', 'FGF', 'PDGF', 'HGF', 'IGF1', 'TGFB', 'LPS', 'NOTCH', 'VEGFR', 'KDR',
])

/** Intracellular kinases / adapters. */
const KINASE = new Set([
  'KRAS', 'HRAS', 'NRAS', 'BRAF', 'RAF1', 'ARAF', 'MAP2K1', 'MAP2K2',
  'MAPK1', 'MAPK3', 'PIK3CA', 'AKT1', 'AKT2', 'MTOR', 'SRC', 'ABL1',
  'SOS1', 'GRB2', 'PTEN', 'RHEB', 'PRKAA1', 'JAK1', 'JAK2', 'MEK', 'ERK',
  'RAF', 'PI3K', 'AKT', 'EGLN1', 'VHL', 'PHD',
])

/** Nuclear TFs & effectors. */
const NUCLEAR = new Set([
  'HIF1A', 'ARNT', 'EPAS1', 'MYC', 'TP53', 'NFKB1', 'RELA', 'FOS',
  'JUN', 'STAT3', 'STAT1', 'FOXO1', 'CREB1', 'SP1', 'VEGFA', 'BAX',
  'BCL2', 'GLUT1', 'SLC2A1', 'CASP3', 'CASP9', 'CCND1', 'CDKN1A',
  'LDHA', 'BNIP3', 'MMP9', 'ANGPT2',
])

/** Short role/identity subtitles rendered under well-known node symbols. */
const GENE_SUBTITLE: Record<string, string> = {
  O2: 'O₂ tension',
  HIF1A: 'TF · O₂-labile',
  EGLN1: 'PHD2',
  VHL: 'E3 ligase',
  ARNT: 'HIF1B · nuclear',
  VEGFA: 'secreted',
  GLUT1: 'SLC2A1',
  LDHA: 'EC 1.1.1.27',
  PDK1: 'PDHK',
  PDH: 'TCA entry',
  MTOR: 'kinase',
  EGF: 'ligand',
  EGFR: 'receptor',
  KRAS: 'GTPase',
  BRAF: 'kinase',
  MAP2K1: 'MEK1',
  MAPK1: 'ERK2',
  ROS: 'oxidant',
  MYC: 'TF',
  BAX: 'apoptosis',
  TP53: 'TF · guardian',
  AKT1: 'kinase',
}

function subtitleFor(id: string): string {
  const u = id.toUpperCase()
  if (GENE_SUBTITLE[u]) return GENE_SUBTITLE[u]
  if (KINASE.has(u)) return 'kinase'
  if (NUCLEAR.has(u)) return 'TF · effector'
  if (SURFACE.has(u)) return 'receptor · ligand'
  return ''
}

function mixHex(a: string, b: string, t: number): string {
  const parse = (h: string) => [
    parseInt(h.slice(1, 3), 16),
    parseInt(h.slice(3, 5), 16),
    parseInt(h.slice(5, 7), 16),
  ]
  const ca = parse(a.startsWith('#') ? a : '#64748B')
  const cb = parse(b.startsWith('#') ? b : '#10B981')
  const m = (i: number) => Math.round(ca[i]! + (cb[i]! - ca[i]!) * t)
  return `#${[0, 1, 2].map((i) => m(i).toString(16).padStart(2, '0')).join('')}`
}

/** Diverging DE scale for omics overlay (−3 … +3 log2FC). */
const OMICS_UP = '#ef4444'
const OMICS_DOWN = '#3b82f6'
const OMICS_NEUTRAL = '#64748b'
const OMICS_LFC_ABS_MAX = 3

/** Map log2 fold-change → red (up) / blue (down) / slate (unmapped). */
function omicsHeatColor(log2Fc: number | null | undefined): string {
  if (log2Fc == null || !Number.isFinite(log2Fc)) return OMICS_NEUTRAL
  const t = Math.max(-1, Math.min(1, log2Fc / OMICS_LFC_ABS_MAX))
  if (Math.abs(t) < 1e-6) return OMICS_NEUTRAL
  if (t > 0) return mixHex(OMICS_NEUTRAL, OMICS_UP, t)
  return mixHex(OMICS_NEUTRAL, OMICS_DOWN, -t)
}

/** Floating top-left legend for the omics heatmap overlay. */
function OmicsHeatmapLegend({
  profileName,
  provenance,
}: {
  profileName: string
  provenance: string
}) {
  return (
    <div className="pointer-events-none absolute left-2 top-2 z-20 w-[188px] rounded-lg border border-orange-500/35 bg-obsidian/95 px-2.5 py-2 shadow-[0_4px_18px_rgba(0,0,0,0.45)] backdrop-blur-md">
      <div className="mb-1.5 flex min-w-0 flex-col gap-1">
        <span className="inline-flex max-w-full items-center truncate rounded-md border border-orange-500/45 bg-orange-950/55 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-orange-100">
          {provenance}
        </span>
        <span className="truncate text-[9px] font-medium text-slate-500" title={profileName}>
          {profileName}
        </span>
      </div>
      <div className="mb-1 text-[8px] font-bold uppercase tracking-[0.12em] text-slate-500">
        log2FC
      </div>
      <div
        className="h-2 w-full rounded-full"
        style={{
          background: `linear-gradient(90deg, ${OMICS_DOWN} 0%, ${OMICS_NEUTRAL} 50%, ${OMICS_UP} 100%)`,
        }}
      />
      <div className="mt-1 flex justify-between font-mono text-[9px] leading-none text-slate-400">
        <span>−3</span>
        <span>0</span>
        <span>+3</span>
      </div>
    </div>
  )
}

function sliceGraphForCanvas(graph: PresetDetail, maxNodes = MAX_CANVAS_NODES): PresetDetail {
  const nodesIn = graph.nodes && typeof graph.nodes === 'object' ? graph.nodes : {}
  const edgesIn = Array.isArray(graph.edges) ? graph.edges : []
  const ids = Object.keys(nodesIn)
  if (ids.length <= maxNodes) {
    return { ...graph, nodes: nodesIn, edges: edgesIn }
  }

  const degree: Record<string, number> = {}
  for (const id of ids) degree[id] = 0
  for (const e of edgesIn) {
    if (!e?.source || !e?.target) continue
    degree[e.source] = (degree[e.source] ?? 0) + 1
    degree[e.target] = (degree[e.target] ?? 0) + 1
  }
  const keep = new Set(
    [...ids]
      .sort((a, b) => (degree[b] ?? 0) - (degree[a] ?? 0) || a.localeCompare(b))
      .slice(0, maxNodes),
  )
  const nodes: PresetDetail['nodes'] = {}
  for (const id of keep) {
    const n = nodesIn[id]
    if (n) nodes[id] = n
  }
  return {
    ...graph,
    nodes,
    edges: edgesIn.filter(
      (e) => e?.source && e?.target && keep.has(e.source) && keep.has(e.target),
    ),
  }
}

export function StudioCanvas({
  preset,
  graph,
  payload,
  scrubT,
  onScrub,
  pathNodes,
  topRegulator,
  selectedNode,
  onNodeSelect,
  knockouts = [],
  perturbations = {},
  onToggleKnockout,
  loading = false,
  stageOnly = false,
}: {
  preset: string
  graph: PresetDetail | null
  payload: ScrubberPayload | null
  scrubT: number
  onScrub: (t: number) => void
  pathNodes: string[]
  topRegulator?: string | null
  selectedNode?: string | null
  onNodeSelect?: (nodeId: string) => void
  knockouts?: string[]
  /** Interactive clamps / titrations; keys present → visual KO/dose marker. */
  perturbations?: Record<string, number>
  onToggleKnockout?: (nodeId: string) => void
  loading?: boolean
  /** VCL IDE: graph viewport only (KPIs / scrub / trajectory live in docks). */
  stageOnly?: boolean
}) {
  const { activeOmicsProfile, untreatedRun, treatedRun } = useLab()

  const omicsLfcByNode = useMemo(() => {
    const map: Record<string, number> = {}
    if (!activeOmicsProfile?.features) return map
    for (const [sym, feat] of Object.entries(activeOmicsProfile.features)) {
      map[sym.toUpperCase()] = feat.log2_fc
      map[sym] = feat.log2_fc
    }
    return map
  }, [activeOmicsProfile])

  const omicsActive = Boolean(activeOmicsProfile && Object.keys(omicsLfcByNode).length)

  const displayGraph = useMemo(
    () => (graph ? sliceGraphForCanvas(graph, MAX_CANVAS_NODES) : null),
    [graph],
  )

  const { nodes: nodeY, edges: edgeF } = useMemo(() => {
    if (!payload?.nodes || !payload?.time_steps?.length) {
      return { nodes: {} as Record<string, number>, edges: {} as Record<string, number> }
    }
    try {
      return lerpAtTime(payload, scrubT)
    } catch (err) {
      console.warn('lerpAtTime failed', err)
      return { nodes: {} as Record<string, number>, edges: {} as Record<string, number> }
    }
  }, [payload, scrubT])

  /** Pre-perturbation baseline activities — drives the dim arc of each ring. */
  const baselineNodeY = useMemo(() => {
    const source = untreatedRun ?? payload
    if (!source?.nodes || !source?.time_steps?.length) return {} as Record<string, number>
    try {
      return lerpAtTime(source, scrubT).nodes
    } catch (err) {
      console.warn('lerpAtTime (baseline) failed', err)
      return {} as Record<string, number>
    }
  }, [untreatedRun, payload, scrubT])

  /**
   * HIF1A nuclear-import fraction for the one synthesized translocation edge —
   * a real value from the same compartment step the Organelle dock tab uses.
   */
  const translocationFraction = useMemo(() => {
    const hif1aY = nodeY['HIF1A']
    if (hif1aY == null) return null
    const o2 = nodeY['O2'] ?? 0.35
    const state = { cytoplasm: hif1aY * 0.55, nucleus: hif1aY * 0.35, mitochondria: hif1aY * 0.1 }
    const { next } = stepHif1aTranslocation(state, o2, Math.max(1, scrubT))
    return next.nucleus
  }, [nodeY, scrubT])

  const edgeViews = useMemo<GraphEdgeView[]>(() => {
    if (!displayGraph) return []
    const nodeIds = new Set(Object.keys(displayGraph.nodes ?? {}))
    const safeEdges = (Array.isArray(displayGraph.edges) ? displayGraph.edges : []).filter(
      (e) => e?.source && e?.target && nodeIds.has(e.source) && nodeIds.has(e.target),
    )
    const views: GraphEdgeView[] = safeEdges.map((e, i) => ({
      id: `e${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      kind: classifyEdgeKind(e, KINASE),
      flux: edgeF[`${e.source}->${e.target}`] ?? 0,
    }))

    // Only drawn when both dimer partners are on canvas and no real fetched
    // edge already connects them.
    const hasHifArnt = safeEdges.some(
      (e) =>
        (e.source === 'HIF1A' && e.target === 'ARNT') ||
        (e.source === 'ARNT' && e.target === 'HIF1A'),
    )
    if (nodeIds.has('HIF1A') && nodeIds.has('ARNT') && !hasHifArnt) {
      views.push({
        id: 'e-translocation-HIF1A-ARNT',
        source: 'HIF1A',
        target: 'ARNT',
        kind: 'translocation',
        flux: translocationFraction ?? 0,
      })
    }
    return views
  }, [displayGraph, edgeF, translocationFraction])

  const omicsColorFor = useMemo(() => {
    if (!omicsActive) return undefined
    return (id: string): string | null => {
      const lfc = omicsLfcByNode[id] ?? omicsLfcByNode[id.toUpperCase()]
      if (lfc == null) return OMICS_NEUTRAL
      return mixHex('#101A28', omicsHeatColor(lfc), 0.75)
    }
  }, [omicsActive, omicsLfcByNode])

  const maxFlux = useMemo(
    () => (Object.values(edgeF).length ? Math.max(...Object.values(edgeF)) : 0),
    [edgeF],
  )
  const activeNodes = Object.values(nodeY).filter((v) => v >= 0.35).length

  const stage = (
    <>
      {displayGraph ? (
        <NetworkGraphSvg
          graph={displayGraph}
          edges={edgeViews}
          nodeValues={nodeY}
          baselineValues={baselineNodeY}
          subtitleFor={subtitleFor}
          omicsColorFor={omicsColorFor}
          perturbations={perturbations}
          knockouts={knockouts}
          selectedNode={selectedNode}
          onNodeSelect={onNodeSelect}
          onToggleKnockout={onToggleKnockout}
        />
      ) : null}
      {loading && !displayGraph ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center gap-2 bg-obsidian/60 text-sm text-vcl-muted">
          <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
          Loading pathway map…
        </div>
      ) : null}
      {omicsActive && activeOmicsProfile ? (
        <OmicsHeatmapLegend
          profileName={
            activeOmicsProfile.condition ||
            activeOmicsProfile.sample_name ||
            activeOmicsProfile.profile_id
          }
          provenance={resolveOmicsProvenance(activeOmicsProfile)}
        />
      ) : null}
    </>
  )

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      {!stageOnly ? (
        <>
          <div className="grid shrink-0 grid-cols-3 gap-3">
            <GlassCard>
              <div className="text-[0.68rem] uppercase tracking-[0.08em] text-slate-500">
                Active proteins
              </div>
              <div className="mt-1 text-2xl font-bold text-emerald-300">
                {payload ? activeNodes : loading ? '…' : '—'}
                <span className="text-sm font-medium text-slate-500">
                  {' '}
                  / {payload ? Object.keys(nodeY).length : '—'}
                </span>
              </div>
            </GlassCard>
            <GlassCard>
              <div className="text-[0.68rem] uppercase tracking-[0.08em] text-slate-500">
                Peak edge flux F
              </div>
              <div className="mt-1 text-2xl font-bold text-slate-100">
                {payload ? maxFlux.toFixed(3) : loading ? '…' : '—'}
              </div>
            </GlassCard>
            <GlassCard>
              <div className="text-[0.68rem] uppercase tracking-[0.08em] text-slate-500">
                Master regulator
              </div>
              <div className="mt-1 truncate text-2xl font-bold text-coral-action">
                {topRegulator ?? (loading ? '…' : '—')}
              </div>
            </GlassCard>
          </div>

          <GlassCard className="!py-3 shrink-0">
            <div className="mb-2 flex justify-between text-[0.7rem] tracking-wide text-slate-500">
              <span>t₀ · basal</span>
              <span className="font-semibold text-emerald-300/90">
                Timeline · {scrubT.toFixed(0)} min
              </span>
              <span>t₆₀ · steady</span>
            </div>
            <input
              type="range"
              min={0}
              max={60}
              step={1}
              value={scrubT}
              disabled={!payload}
              onChange={(e) => onScrub(Number(e.target.value))}
              className="w-full accent-emerald-active disabled:opacity-40"
            />
            <div className="mt-1.5 flex justify-between gap-2 text-[0.65rem] text-slate-600">
              <span>Click · inspect · Shift/Right-click · knockout wᵢ=0</span>
              <span>
                {pathNodes.length
                  ? `Cascade: ${(Array.isArray(pathNodes) ? pathNodes : []).join(' → ')}`
                  : 'Hover to trace Nᵢₙ / Nₒᵤₜ'}
              </span>
            </div>
          </GlassCard>
        </>
      ) : null}

      {stageOnly ? (
        <div className="relative min-h-0 flex-1 overflow-hidden">
          <div
            data-cistron-export="topology"
            className="relative h-full min-h-0 w-full overflow-hidden"
          >
            {stage}
            <div className="pointer-events-none absolute bottom-2 left-2 z-10 rounded-md border border-vcl-border bg-obsidian/85 px-2 py-1 font-mono text-[10px] text-vcl-dim backdrop-blur-sm">
              edge width ∝ V_max · ring = perturbed vs baseline · Shift-click = KO
            </div>
          </div>
        </div>
      ) : (
        <GlassCard
          title="Signaling topology"
          hint={
            omicsActive
              ? 'Omics heat · red ↑log2FC · blue ↓log2FC · slate unmapped'
              : '→ activation · ⊣ inhibition · ┄ phosphorylation · ⇌ translocation'
          }
          className="flex min-h-0 flex-1 flex-col overflow-hidden !pb-3"
        >
          <div
            data-cistron-export="topology"
            className="relative min-h-[260px] w-full flex-1 overflow-hidden rounded-xl border border-slate-800/80"
          >
            {stage}
          </div>
        </GlassCard>
      )}

      {!stageOnly ? (
        <TrajectoryChart
          untreatedRun={untreatedRun}
          treatedRun={treatedRun}
          focus={FOCUS_SERIES[preset] ?? FOCUS_SERIES.hypoxia ?? ['HIF1A', 'VEGFA']}
          scrubT={scrubT}
          loading={loading}
        />
      ) : null}
    </div>
  )
}
