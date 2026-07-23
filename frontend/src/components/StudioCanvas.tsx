import { useEffect, useMemo, useRef, useState } from 'react'
import cytoscape, { type Core, type EventObject } from 'cytoscape'
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
import { GlassCard } from './GlassCard'
import type { PresetDetail, ScrubberPayload } from '../api/types'
import { FOCUS_SERIES } from '../api/types'
import { lerpAtTime } from '../api/client'

/**
 * Hard cap — never hand Cytoscape a huge graph.
 * Dagre / network-simplex is intentionally NOT used: it can lock the Chrome
 * main thread (page "isn't responding") on even modest cascade graphs.
 */
const MAX_CANVAS_NODES = 40

const NODE_COLORS: Record<string, string> = {
  O2: '#06B6D4',
  EGLN1: '#A855F7',
  HIF1A: '#EF4444',
  VEGFA: '#10B981',
  GLUT1: '#F59E0B',
  MTOR: '#F43F5E',
  EGF: '#06B6D4',
  EGFR: '#A855F7',
  KRAS: '#EF4444',
  BRAF: '#F59E0B',
  MAP2K1: '#34D399',
  MAPK1: '#10B981',
  ROS: '#F97316',
  MYC: '#A855F7',
  BAX: '#F43F5E',
}

/** Cell-surface receptors & environmental triggers — top of cascade. */
const SURFACE = new Set([
  'EGF', 'EGFR', 'O2', 'ROS', 'TNF', 'TNFR', 'IL6', 'INS',
  'INSULIN', 'WNT', 'FGF', 'PDGF', 'HGF', 'IGF1', 'TGFB', 'LPS', 'NOTCH', 'VEGFR', 'KDR',
])

/** Intracellular kinases / adapters — middle cascade. */
const KINASE = new Set([
  'KRAS', 'HRAS', 'NRAS', 'BRAF', 'RAF1', 'ARAF', 'MAP2K1', 'MAP2K2',
  'MAPK1', 'MAPK3', 'PIK3CA', 'AKT1', 'AKT2', 'MTOR', 'SRC', 'ABL1',
  'SOS1', 'GRB2', 'PTEN', 'RHEB', 'PRKAA1', 'JAK1', 'JAK2', 'MEK', 'ERK',
  'RAF', 'PI3K', 'AKT', 'EGLN1', 'VHL', 'PHD',
])

/** Nuclear TFs & effectors — bottom of cascade. */
const NUCLEAR = new Set([
  'HIF1A', 'ARNT', 'EPAS1', 'MYC', 'TP53', 'NFKB1', 'RELA', 'FOS',
  'JUN', 'STAT3', 'STAT1', 'FOXO1', 'CREB1', 'SP1', 'VEGFA', 'BAX',
  'BCL2', 'GLUT1', 'SLC2A1', 'CASP3', 'CASP9', 'CCND1', 'CDKN1A',
  'LDHA', 'BNIP3', 'MMP9', 'ANGPT2',
])

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

function activityHue(base: string, y: number): string {
  const quiescent = '#334155'
  const hot = '#FF5252'
  if (y < 0.4) return mixHex(quiescent, base, y / 0.4)
  return mixHex(base, hot, (y - 0.4) / 0.6)
}

function semanticLayer(id: string): number | null {
  const u = id.toUpperCase()
  if (SURFACE.has(u) || SURFACE.has(id)) return 0
  if (NUCLEAR.has(u) || NUCLEAR.has(id)) return 2
  if (KINASE.has(u) || KINASE.has(id)) return 1
  if (/^(MAP|RAF|RAS|AKT|PIK|JAK|SRC|SOS|MEK|ERK)/i.test(id)) return 1
  if (/^(HIF|MYC|STAT|FOS|JUN|TP53|NFK|VEG|BAX|CASP|GLUT)/i.test(id)) return 2
  if (/^(EGF|O2|ROS|TNF|IL|WNT|FGF|PDGF)/i.test(id)) return 0
  return null
}

function assignLayers(
  nodeIds: string[],
  edges: Array<{ source: string; target: string }>,
): Map<string, number> {
  const succ = new Map<string, string[]>()
  const pred = new Map<string, string[]>()
  for (const id of nodeIds) {
    succ.set(id, [])
    pred.set(id, [])
  }
  for (const e of edges) {
    if (!succ.has(e.source) || !pred.has(e.target)) continue
    succ.get(e.source)!.push(e.target)
    pred.get(e.target)!.push(e.source)
  }

  // Longest-path BFS with hard visit budget — feedback cycles must NOT
  // re-enqueue forever (that froze Chrome on hypoxia cascades).
  const sources = nodeIds.filter((n) => (pred.get(n)?.length ?? 0) === 0)
  const depth = new Map<string, number>()
  const queue = sources.length ? [...sources] : [...nodeIds]
  for (const s of queue) depth.set(s, 0)
  const maxDepthCap = Math.max(8, nodeIds.length)
  const budget = nodeIds.length * nodeIds.length + 16
  let steps = 0
  let qi = 0
  while (qi < queue.length && steps++ < budget) {
    const u = queue[qi++]!
    const d = depth.get(u) ?? 0
    if (d >= maxDepthCap) continue
    for (const v of succ.get(u) ?? []) {
      const nd = d + 1
      if (!depth.has(v) || nd > (depth.get(v) ?? 0)) {
        depth.set(v, Math.min(nd, maxDepthCap))
        queue.push(v)
      }
    }
  }

  const maxD = Math.max(1, ...Array.from(depth.values(), (v) => v || 0))
  const layers = new Map<string, number>()
  for (const id of nodeIds) {
    const sem = semanticLayer(id)
    if (sem != null) {
      layers.set(id, sem)
      continue
    }
    const d = depth.get(id) ?? Math.floor(maxD / 2)
    if (d <= 0) layers.set(id, 0)
    else if (d >= maxD) layers.set(id, 2)
    else layers.set(id, 1)
  }
  return layers
}

/** Synchronous TB grid — O(n). Never calls dagre / network-simplex. */
function applyLayeredPositions(
  cy: Core,
  nodeIds: string[],
  layers: Map<string, number>,
  nodeSep: number,
  rankSep: number,
): void {
  const byLayer = new Map<number, string[]>()
  for (const id of nodeIds) {
    const L = layers.get(id) ?? 1
    if (!byLayer.has(L)) byLayer.set(L, [])
    byLayer.get(L)!.push(id)
  }
  for (const [L, ids] of byLayer) {
    ids.sort()
    const totalW = (ids.length - 1) * nodeSep
    ids.forEach((id, i) => {
      const n = cy.getElementById(id)
      if (n.empty()) return
      n.position({ x: i * nodeSep - totalW / 2, y: L * rankSep })
    })
  }
}

function spacingForN(n: number): { nodeSep: number; rankSep: number; padding: number } {
  const s = Math.sqrt(Math.max(n, 1))
  return {
    nodeSep: Math.max(48, Math.min(120, Math.round(720 / s))),
    rankSep: Math.max(72, Math.min(160, Math.round(980 / s))),
    padding: Math.max(28, Math.min(56, Math.round(420 / s))),
  }
}

function sliceGraphForCanvas(graph: PresetDetail, maxNodes = MAX_CANVAS_NODES): PresetDetail {
  const ids = Object.keys(graph.nodes)
  if (ids.length <= maxNodes) return graph

  const degree: Record<string, number> = {}
  for (const id of ids) degree[id] = 0
  for (const e of graph.edges) {
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
    const n = graph.nodes[id]
    if (n) nodes[id] = n
  }
  return {
    ...graph,
    nodes,
    edges: graph.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
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
  onToggleKnockout,
  loading = false,
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
  onToggleKnockout?: (nodeId: string) => void
  loading?: boolean
}) {
  const cyRef = useRef<HTMLDivElement>(null)
  const cyInstance = useRef<Core | null>(null)
  const styleRafRef = useRef<number | null>(null)
  const knockoutRef = useRef<Set<string>>(new Set())
  const onNodeSelectRef = useRef(onNodeSelect)
  const onToggleKnockoutRef = useRef(onToggleKnockout)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  const [layoutReady, setLayoutReady] = useState(false)
  onNodeSelectRef.current = onNodeSelect
  onToggleKnockoutRef.current = onToggleKnockout
  knockoutRef.current = new Set(knockouts)

  const displayGraph = useMemo(
    () => (graph ? sliceGraphForCanvas(graph, MAX_CANVAS_NODES) : null),
    [graph],
  )

  const graphSig = useMemo(() => {
    if (!displayGraph) return ''
    const n = Object.keys(displayGraph.nodes).length
    const e = displayGraph.edges.length
    const id = displayGraph.id || displayGraph.name || 'g'
    return `${id}|${n}|${e}`
  }, [displayGraph])

  const { nodes: nodeY, edges: edgeF } = useMemo(() => {
    if (!payload) return { nodes: {} as Record<string, number>, edges: {} as Record<string, number> }
    return lerpAtTime(payload, scrubT)
  }, [payload, scrubT])

  const focus = useMemo(() => {
    const series = FOCUS_SERIES[preset]
    if (series?.length) return series
    return Object.keys(payload?.nodes ?? {}).slice(0, 5)
  }, [preset, payload])

  const pathKey = useMemo(() => pathNodes.join('\0'), [pathNodes])
  const pathSet = useMemo(() => new Set(pathNodes), [pathKey])
  const koSet = useMemo(() => new Set(knockouts), [knockouts])

  const chartData = useMemo(() => {
    if (!payload) return []
    return payload.time_steps.map((t, i) => {
      const row: Record<string, number> = { t }
      for (const sym of focus) {
        row[sym] = payload.nodes[sym]?.[i] ?? 0
      }
      return row
    })
  }, [payload, focus])

  const maxFlux = useMemo(
    () => (Object.values(edgeF).length ? Math.max(...Object.values(edgeF)) : 0),
    [edgeF],
  )
  const activeNodes = Object.values(nodeY).filter((v) => v >= 0.35).length

  useEffect(() => {
    if (!cyRef.current || !displayGraph?.nodes || !Object.keys(displayGraph.nodes).length) {
      setLayoutReady(false)
      return
    }

    let cancelled = false
    let ro: ResizeObserver | null = null
    let fitting = false
    let detachHandlers: (() => void) | null = null
    const container = cyRef.current
    setLayoutReady(false)

    const build = () => {
      if (cancelled || !cyRef.current || !displayGraph) return

      try {
        cyInstance.current?.destroy()
        cyInstance.current = null

        const nodeIds = Object.keys(displayGraph.nodes)
        if (!nodeIds.length) {
          setLayoutReady(true)
          return
        }
        const layers = assignLayers(nodeIds, displayGraph.edges)
        const { nodeSep, rankSep, padding } = spacingForN(nodeIds.length)

        const elements = [
          ...nodeIds.map((id) => ({
            data: { id, label: id, layer: layers.get(id) ?? 1 },
          })),
          ...displayGraph.edges.map((e, i) => ({
            data: {
              id: `e${i}-${e.source}-${e.target}`,
              source: e.source,
              target: e.target,
              sign: e.sign,
              key: `${e.source}->${e.target}`,
              inhibitory: e.sign < 0,
            },
            classes: e.sign < 0 ? 'inhibitory' : 'stimulatory',
          })),
        ]

        const cy = cytoscape({
          container: cyRef.current,
          elements,
          style: [
            {
              selector: 'node',
              style: {
                label: 'data(label)',
                color: '#F8FAFC',
                'font-size': 11,
                'font-weight': 600,
                'font-family': 'Plus Jakarta Sans, Inter, sans-serif',
                'text-valign': 'top',
                'text-margin-y': -8,
                'text-outline-width': 2,
                'text-outline-color': '#0F172A',
                'background-color': '#64748B',
                width: 28,
                height: 28,
                'border-width': 2,
                'border-color': '#1E293B',
                'underlay-color': '#10B981',
                'underlay-padding': 4,
                'underlay-opacity': 0,
                'underlay-shape': 'ellipse',
                'min-zoomed-font-size': 8,
                'transition-property': 'opacity, width, height, background-color',
                'transition-duration': 80,
              },
            },
            {
              selector: 'node:selected',
              style: { 'border-color': '#FBBF24', 'border-width': 4 },
            },
            {
              selector: 'node.knocked-out',
              style: {
                'border-style': 'dashed',
                'border-color': '#FF5252',
                'border-width': 3,
                'background-opacity': 0.35,
              },
            },
            {
              selector: 'edge.stimulatory',
              style: {
                width: 2,
                'line-color': '#06B6D4',
                'target-arrow-shape': 'triangle',
                'target-arrow-color': '#06B6D4',
                'curve-style': 'bezier',
                'line-style': 'solid',
                opacity: 0.75,
                'transition-property': 'opacity, width, line-color',
                'transition-duration': 80,
              },
            },
            {
              selector: 'edge.inhibitory',
              style: {
                width: 2,
                'line-color': '#EF4444',
                'target-arrow-shape': 'tee',
                'target-arrow-color': '#EF4444',
                'curve-style': 'bezier',
                'line-style': 'dashed',
                'line-dash-pattern': [4, 8],
                opacity: 0.75,
              },
            },
            { selector: '.faded', style: { opacity: 0.15 } },
            { selector: '.hover-focus', style: { opacity: 1 } },
          ],
          layout: { name: 'null' },
          userZoomingEnabled: true,
          userPanningEnabled: true,
          boxSelectionEnabled: false,
          pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        })
        cyInstance.current = cy

        // Instant layered positions — no dagre, no layoutstop wait.
        cy.batch(() => {
          applyLayeredPositions(cy, nodeIds, layers, nodeSep, rankSep)
          cy.nodes().forEach((n) => {
            if (knockoutRef.current.has(n.id())) n.addClass('knocked-out')
          })
        })
        cy.fit(undefined, padding)
        setLayoutReady(true)

        const clearHover = () => setHoveredNode(null)
        const onHover = (evt: EventObject) => {
          const n = evt.target
          if (!n.isNode?.()) return
          setHoveredNode(n.id())
        }
        const onTap = (evt: EventObject) => {
          const n = evt.target
          if (!n.isNode?.()) return
          const orig = evt.originalEvent as MouseEvent | undefined
          if (orig?.shiftKey) {
            onToggleKnockoutRef.current?.(n.id())
            return
          }
          onNodeSelectRef.current?.(n.id())
        }
        const onCtx = (evt: EventObject) => {
          const n = evt.target
          if (!n.isNode?.()) return
          const oe = evt.originalEvent as MouseEvent | undefined
          oe?.preventDefault?.()
          oe?.stopPropagation?.()
          onToggleKnockoutRef.current?.(n.id())
        }
        const blockMenu = (e: Event) => e.preventDefault()
        container.addEventListener('contextmenu', blockMenu)
        cy.on('mouseover', 'node', onHover)
        cy.on('mouseout', 'node', clearHover)
        cy.on('tap', 'node', onTap)
        cy.on('cxttap', 'node', onCtx)
        cy.on('tap', (evt) => {
          if (evt.target === cy) clearHover()
        })
        detachHandlers = () => {
          cy.off('mouseover', 'node', onHover)
          cy.off('mouseout', 'node', clearHover)
          cy.off('tap', 'node', onTap)
          cy.off('cxttap', 'node', onCtx)
          container.removeEventListener('contextmenu', blockMenu)
        }

        ro = new ResizeObserver(() => {
          const inst = cyInstance.current
          if (!inst || fitting) return
          fitting = true
          requestAnimationFrame(() => {
            try {
              inst.resize()
              inst.fit(undefined, padding)
            } finally {
              fitting = false
            }
          })
        })
        ro.observe(container)
        // No continuous edge-dash RAF — that + layout was locking the tab.
      } catch (err) {
        console.error('Cytoscape init failed', err)
        setLayoutReady(true)
      }
    }

    const startTimer = window.setTimeout(() => {
      requestAnimationFrame(build)
    }, 0)

    return () => {
      cancelled = true
      window.clearTimeout(startTimer)
      detachHandlers?.()
      ro?.disconnect()
      cyInstance.current?.destroy()
      cyInstance.current = null
    }
  }, [graphSig])

  useEffect(() => {
    if (styleRafRef.current != null) cancelAnimationFrame(styleRafRef.current)
    styleRafRef.current = requestAnimationFrame(() => {
      styleRafRef.current = null
      const cy = cyInstance.current
      if (!cy || !layoutReady) return
      const focusIds = new Set<string>()
      const focusEdgeIds = new Set<string>()
      if (hoveredNode) {
  const n = cy.getElementById(hoveredNode)
  if (n.nonempty() && n.isNode()) {
    const nbhd = n.closedNeighborhood()
    nbhd.nodes().toArray().forEach((el) => focusIds.add(el.id()))
    nbhd.edges().toArray().forEach((el) => focusEdgeIds.add(el.id()))
  }
}
      cy.batch(() => {
        cy.nodes().forEach((n) => {
          const id = n.id()
          const y = koSet.has(id) ? 0 : (nodeY[id] ?? 0)
          const onPath = pathSet.has(id)
          const selected = selectedNode === id
          const base = NODE_COLORS[id] ?? '#94A3B8'
          const glow = 2 + y * 14
          const inHover = !hoveredNode || focusIds.has(id)
          const fade = inHover ? 1 : 0.15
          n.toggleClass('knocked-out', koSet.has(id))
          n.style({
            'background-color': activityHue(base, y),
            width: 18 + 30 * Math.max(y, koSet.has(id) ? 0.15 : 0),
            height: 18 + 30 * Math.max(y, koSet.has(id) ? 0.15 : 0),
            opacity: (0.35 + 0.65 * Math.max(y, 0.2)) * fade,
            'border-color': selected
              ? '#FBBF24'
              : koSet.has(id)
                ? '#FF5252'
                : onPath
                  ? '#10B981'
                  : mixHex('#1E293B', base, y * 0.5),
            'border-width': selected ? 4 : koSet.has(id) ? 3 : onPath ? 3.5 : 1.5 + y,
            'border-style': koSet.has(id) ? 'dashed' : 'solid',
            'underlay-color': base,
            'underlay-padding': glow,
            'underlay-opacity': inHover ? 0.12 + 0.55 * y : 0.04,
            'font-size': onPath || selected ? 12 : 10,
            label: koSet.has(id) ? `${id} ⊖` : id,
          })
        })
        cy.edges().forEach((e) => {
          const key = String(e.data('key'))
          const flux = edgeF[key] ?? 0
          const inhibitory = Boolean(e.data('inhibitory'))
          const src = e.source().id()
          const tgt = e.target().id()
          const onPath = pathSet.has(src) && pathSet.has(tgt)
          const edgeInFocus = !hoveredNode || focusEdgeIds.has(e.id())
          const fade = edgeInFocus ? 1 : 0.15
          const color = onPath ? '#10B981' : inhibitory ? '#EF4444' : '#06B6D4'
          e.style({
            width: 1.0 + 8.5 * flux,
            'line-color': color,
            'target-arrow-color': color,
            'target-arrow-shape': inhibitory ? 'tee' : 'triangle',
            'line-style': flux > 0.12 ? 'dashed' : inhibitory ? 'dashed' : 'solid',
            opacity: (0.18 + 0.82 * flux) * fade,
            'line-dash-pattern': inhibitory
              ? [3, 7]
              : [5, Math.max(3, 10 - Math.min(7, flux * 8))],
            'overlay-opacity': flux > 0.35 && fade > 0.5 ? 0.08 + flux * 0.12 : 0,
            'overlay-color': color,
            'overlay-padding': 2 + flux * 4,
          })
        })
      })
    })
    return () => {
      if (styleRafRef.current != null) {
        cancelAnimationFrame(styleRafRef.current)
        styleRafRef.current = null
      }
    }
  }, [nodeY, edgeF, pathKey, pathSet, selectedNode, koSet, hoveredNode, layoutReady])

  useEffect(() => {
    const cy = cyInstance.current
    if (!cy || !layoutReady) return
    cy.batch(() => {
      cy.nodes().forEach((n:any) => n.toggleClass('knocked-out', koSet.has(n.id())))
    })
  }, [koSet, layoutReady])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
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
            {pathNodes.length ? `Cascade: ${pathNodes.join(' → ')}` : 'Hover to trace Nᵢₙ / Nₒᵤₜ'}
          </span>
        </div>
      </GlassCard>

      <GlassCard
        title="Signaling topology"
        hint="Hierarchical TB · hover path · flux glow ∝ Fⱼ→ᵢ(t) · → stim · ⊣ inhib"
        className="flex min-h-0 flex-1 flex-col overflow-hidden !pb-3"
      >
        <div className="relative min-h-[260px] w-full flex-1 overflow-hidden rounded-xl border border-slate-800/80 lab-grid-panel">
          <div
            ref={cyRef}
            className="absolute inset-0 h-full w-full"
            style={{ touchAction: 'none' }}
          />
          {loading && !displayGraph ? (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center gap-2 rounded-xl bg-obsidian/60 text-sm text-slate-300">
              <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
              Loading pathway map…
            </div>
          ) : displayGraph && !layoutReady ? (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center gap-2 rounded-xl bg-obsidian/40 text-sm text-slate-300">
              <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
              Laying out cascade…
            </div>
          ) : null}
          <div className="pointer-events-none absolute bottom-2 left-2 right-2 z-10 flex flex-wrap gap-2 text-[10px] uppercase tracking-wider text-slate-500">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-800/80 bg-obsidian/80 px-1.5 py-0.5">
              <span className="h-0.5 w-3.5 bg-cyan-flux" /> Stim →
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-800/80 bg-obsidian/80 px-1.5 py-0.5">
              <span className="h-0.5 w-3.5 border-t border-dashed border-coral-action" /> Inhib ⊣
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-800/80 bg-obsidian/80 px-1.5 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-hub" /> Hub / cascade
            </span>
          </div>
        </div>
      </GlassCard>

      <GlassCard
        title="Activation trajectories"
        hint="Multi-protein yᵢ(t) · playhead locked to scrubber"
        className="h-[200px] shrink-0 overflow-hidden"
      >
        {payload ? (
          <div className="h-[135px] w-full">
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
                <Tooltip
                  contentStyle={{
                    background: '#0F172A',
                    border: '1px solid #1E293B',
                    borderRadius: 10,
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine
                  x={scrubT}
                  stroke="#10B981"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  label={`t=${scrubT}`}
                />
                {focus.map((sym) => (
                  <Line
                    key={sym}
                    type="monotone"
                    dataKey={sym}
                    stroke={NODE_COLORS[sym] ?? '#94A3B8'}
                    dot={false}
                    strokeWidth={2.3}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-[120px] items-center justify-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin text-emerald-active" />
            Computing activation curves…
          </div>
        )}
      </GlassCard>
    </div>
  )
}