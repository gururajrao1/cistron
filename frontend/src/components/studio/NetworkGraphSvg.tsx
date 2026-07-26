import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from 'react'
import type { PresetDetail } from '../../api/types'
import type { EdgeKind } from '../../engine/edgeClassification'

/**
 * Network topology stage — a direct port of the Cistron VCL design mockup's
 * SVG graph.
 *
 * The viewBox tracks the container so one user-space unit is one CSS pixel.
 * That keeps the mockup's authored geometry (25px rings, 11px values) at its
 * true size in any pane shape — a fixed viewBox would letterbox and shrink
 * every label on a short pane, and a canvas renderer scales label text with
 * zoom, which is why sparse graphs previously rendered oversized text.
 */

const FALLBACK_W = 920
const FALLBACK_H = 560

/** Node disc geometry (mockup values). */
const RING_R = 25
const RING_W = 3.5
const DISC_R = 19.5
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_R

/** Edges stop short of the disc, and bow by a fixed perpendicular offset. */
const EDGE_TRIM = 30
const EDGE_BOW = 18

const COLOR = {
  ringTrack: '#1B2836',
  ringBaseline: '#4E6479',
  ringCurrent: '#7C8DA3',
  disc: '#101A28',
  discStroke: '#233042',
  value: '#E6EDF5',
  symbol: '#A9B8C9',
  symbolActive: '#FFFFFF',
  subtitle: '#4E6479',
  grid: '#101C2A',
  activation: '#22C55E',
  inhibition: '#EF4444',
  phosphorylation: '#3B82F6',
  translocation: '#C084FC',
  knockout: '#EF4444',
  perturbed: '#FB7185',
  selected: '#FBBF24',
} as const

const FONT_MONO = '"IBM Plex Mono", ui-monospace, monospace'
const FONT_SANS = '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif'

type EdgeVisualKind = EdgeKind | 'translocation'

const EDGE_COLOR: Record<EdgeVisualKind, string> = {
  activation: COLOR.activation,
  inhibition: COLOR.inhibition,
  phosphorylation: COLOR.phosphorylation,
  translocation: COLOR.translocation,
}

const EDGE_MARKER: Record<EdgeVisualKind, string> = {
  activation: 'mk-act',
  inhibition: 'mk-inh',
  phosphorylation: 'mk-pho',
  translocation: 'mk-loc',
}

export type GraphEdgeView = {
  id: string
  source: string
  target: string
  kind: EdgeVisualKind
  flux: number
}

type Point = { x: number; y: number }

/**
 * Longest-path depth → left-to-right columns. Cycles are bounded by a visit
 * budget so feedback loops can never spin here.
 */
function buildLayout(
  nodeIds: string[],
  edges: Array<{ source: string; target: string }>,
  width: number,
  height: number,
) {
  const succ = new Map<string, string[]>()
  const indeg = new Map<string, number>()
  for (const id of nodeIds) {
    succ.set(id, [])
    indeg.set(id, 0)
  }
  for (const e of edges) {
    if (!succ.has(e.source) || !indeg.has(e.target)) continue
    succ.get(e.source)!.push(e.target)
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
  }

  const roots = nodeIds.filter((id) => (indeg.get(id) ?? 0) === 0)
  const depth = new Map<string, number>()
  const queue = roots.length ? [...roots] : [...nodeIds]
  for (const id of queue) depth.set(id, 0)

  const depthCap = Math.max(4, Math.min(nodeIds.length, 12))
  const budget = nodeIds.length * nodeIds.length + 16
  let steps = 0
  let qi = 0
  while (qi < queue.length && steps++ < budget) {
    const u = queue[qi++]!
    const d = depth.get(u) ?? 0
    if (d >= depthCap) continue
    for (const v of succ.get(u) ?? []) {
      const nd = d + 1
      if (!depth.has(v) || nd > (depth.get(v) ?? 0)) {
        depth.set(v, Math.min(nd, depthCap))
        queue.push(v)
      }
    }
  }

  const columns = new Map<number, string[]>()
  for (const id of nodeIds) {
    const d = depth.get(id) ?? 0
    if (!columns.has(d)) columns.set(d, [])
    columns.get(d)!.push(id)
  }

  const colKeys = [...columns.keys()].sort((a, b) => a - b)
  // Leave room for the widest labels and the subtitle that sits below a disc.
  const marginX = Math.min(110, Math.max(70, width * 0.1))
  const marginY = Math.min(90, Math.max(62, height * 0.16))
  const usableW = Math.max(1, width - marginX * 2)
  const usableH = Math.max(1, height - marginY * 2)

  const positions = new Map<string, Point>()
  colKeys.forEach((key, ci) => {
    const ids = columns.get(key)!.slice().sort()
    const x =
      colKeys.length > 1 ? marginX + (ci * usableW) / (colKeys.length - 1) : width / 2
    ids.forEach((id, ri) => {
      const y = ids.length > 1 ? marginY + (ri * usableH) / (ids.length - 1) : height / 2
      positions.set(id, { x, y })
    })
  })
  return positions
}

/** Trim both ends to the disc edge and bow by a fixed perpendicular offset. */
function edgeGeometry(a: Point, b: Point) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  const ux = dx / len
  const uy = dy / len
  const start = { x: a.x + ux * EDGE_TRIM, y: a.y + uy * EDGE_TRIM }
  const end = { x: b.x - ux * EDGE_TRIM, y: b.y - uy * EDGE_TRIM }
  const mid = { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 }
  // Left-hand normal, matching the mockup's bow direction.
  const ctrl = { x: mid.x + -uy * EDGE_BOW, y: mid.y + ux * EDGE_BOW }
  const label = {
    x: 0.25 * start.x + 0.5 * ctrl.x + 0.25 * end.x,
    y: 0.25 * start.y + 0.5 * ctrl.y + 0.25 * end.y,
  }
  return {
    d: `M${start.x.toFixed(1)},${start.y.toFixed(1)} Q${ctrl.x.toFixed(1)},${ctrl.y.toFixed(1)} ${end.x.toFixed(1)},${end.y.toFixed(1)}`,
    label,
  }
}

function ActivityRings({
  baseline,
  current,
  currentColor,
}: {
  baseline: number
  current: number
  currentColor: string
}) {
  const arc = (fraction: number) =>
    `${(RING_CIRCUMFERENCE * Math.max(0, Math.min(1, fraction))).toFixed(1)} ${RING_CIRCUMFERENCE.toFixed(1)}`
  return (
    <>
      <circle r={RING_R} fill="none" stroke={COLOR.ringTrack} strokeWidth={RING_W} />
      <circle
        r={RING_R}
        fill="none"
        stroke={COLOR.ringBaseline}
        strokeWidth={RING_W}
        strokeDasharray={arc(baseline)}
        strokeLinecap="butt"
        opacity={0.55}
        transform="rotate(-90)"
      />
      <circle
        r={RING_R}
        fill="none"
        stroke={currentColor}
        strokeWidth={RING_W}
        strokeDasharray={arc(current)}
        strokeLinecap="butt"
        transform="rotate(-90)"
      />
    </>
  )
}

export function NetworkGraphSvg({
  graph,
  edges,
  nodeValues,
  baselineValues,
  subtitleFor,
  omicsColorFor,
  perturbations = {},
  knockouts = [],
  selectedNode,
  onNodeSelect,
  onToggleKnockout,
}: {
  graph: PresetDetail
  edges: GraphEdgeView[]
  nodeValues: Record<string, number>
  baselineValues: Record<string, number>
  subtitleFor: (id: string) => string
  /** Omics overlay tint for a node, or null when no profile is active. */
  omicsColorFor?: (id: string) => string | null
  perturbations?: Record<string, number>
  knockouts?: string[]
  selectedNode?: string | null
  onNodeSelect?: (id: string) => void
  onToggleKnockout?: (id: string) => void
}) {
  const [hovered, setHovered] = useState<string | null>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: FALLBACK_W, h: FALLBACK_H })

  useLayoutEffect(() => {
    const el = hostRef.current
    if (!el) return
    const measure = () => {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.height > 0) {
        setSize((prev) => {
          const w = Math.round(r.width)
          const h = Math.round(r.height)
          return prev.w === w && prev.h === h ? prev : { w, h }
        })
      }
    }
    // Measure up front: ResizeObserver only reports on *change*, so a pane
    // that never resizes would otherwise be stuck on the fallback viewBox.
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const nodeIds = useMemo(() => Object.keys(graph.nodes ?? {}), [graph])
  const positions = useMemo(
    () => buildLayout(nodeIds, edges, size.w, size.h),
    [nodeIds, edges, size.w, size.h],
  )

  const koSet = useMemo(
    () => new Set(knockouts.map((k) => k.toUpperCase())),
    [knockouts],
  )
  const pertMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const [k, v] of Object.entries(perturbations)) m[k.toUpperCase()] = v
    return m
  }, [perturbations])

  /** Hovering a node dims everything outside its immediate neighbourhood. */
  const neighbourhood = useMemo(() => {
    if (!hovered) return null
    const ids = new Set<string>([hovered])
    const edgeIds = new Set<string>()
    for (const e of edges) {
      if (e.source === hovered || e.target === hovered) {
        ids.add(e.source)
        ids.add(e.target)
        edgeIds.add(e.id)
      }
    }
    return { ids, edgeIds }
  }, [hovered, edges])

  const handleNodeClick = useCallback(
    (id: string) => (event: ReactMouseEvent) => {
      if (event.shiftKey) {
        onToggleKnockout?.(id)
        return
      }
      onNodeSelect?.(id)
    },
    [onNodeSelect, onToggleKnockout],
  )

  const handleNodeContext = useCallback(
    (id: string) => (event: ReactMouseEvent) => {
      event.preventDefault()
      onToggleKnockout?.(id)
    },
    [onToggleKnockout],
  )

  const gridLines = useMemo(() => {
    const v: number[] = []
    for (let x = 40; x < size.w; x += 40) v.push(x)
    const h: number[] = []
    for (let y = 40; y < size.h; y += 40) h.push(y)
    return { v, h }
  }, [size.w, size.h])

  return (
    <div ref={hostRef} style={{ position: 'absolute', inset: 0 }}>
    <svg
      viewBox={`0 0 ${size.w} ${size.h}`}
      preserveAspectRatio="xMidYMid meet"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    >
      <defs>
        <marker
          id="mk-act"
          viewBox="0 0 10 10"
          refX={9}
          refY={5}
          markerWidth={9}
          markerHeight={9}
          markerUnits="userSpaceOnUse"
          orient="auto"
        >
          <path d="M0,1.5 L9,5 L0,8.5 z" fill={COLOR.activation} />
        </marker>
        <marker
          id="mk-inh"
          viewBox="0 0 10 10"
          refX={4}
          refY={5}
          markerWidth={12}
          markerHeight={12}
          markerUnits="userSpaceOnUse"
          orient="auto"
        >
          <path d="M4,0.5 L4,9.5" stroke={COLOR.inhibition} strokeWidth={2.4} />
        </marker>
        <marker
          id="mk-pho"
          viewBox="0 0 10 10"
          refX={9}
          refY={5}
          markerWidth={9}
          markerHeight={9}
          markerUnits="userSpaceOnUse"
          orient="auto"
        >
          <path d="M0,1.5 L9,5 L0,8.5 z" fill={COLOR.phosphorylation} />
        </marker>
        <marker
          id="mk-loc"
          viewBox="0 0 10 10"
          refX={9}
          refY={5}
          markerWidth={9}
          markerHeight={9}
          markerUnits="userSpaceOnUse"
          orient="auto"
        >
          <path d="M0,1.5 L9,5 L0,8.5 z" fill={COLOR.translocation} />
        </marker>
        <marker
          id="mk-loc-b"
          viewBox="0 0 10 10"
          refX={1}
          refY={5}
          markerWidth={9}
          markerHeight={9}
          markerUnits="userSpaceOnUse"
          orient="auto"
        >
          <path d="M10,1.5 L1,5 L10,8.5 z" fill={COLOR.translocation} />
        </marker>
      </defs>

      <g opacity={0.5}>
        {gridLines.v.map((x) => (
          <line key={`v${x}`} x1={x} y1={0} x2={x} y2={size.h} stroke={COLOR.grid} strokeWidth={1} />
        ))}
        {gridLines.h.map((y) => (
          <line key={`h${y}`} x1={0} y1={y} x2={size.w} y2={y} stroke={COLOR.grid} strokeWidth={1} />
        ))}
      </g>

      <g>
        {edges.map((e) => {
          const a = positions.get(e.source)
          const b = positions.get(e.target)
          if (!a || !b) return null
          const { d, label } = edgeGeometry(a, b)
          const color = EDGE_COLOR[e.kind]
          const dimmed = neighbourhood ? !neighbourhood.edgeIds.has(e.id) : false
          const flux = Math.max(0, Math.min(1, e.flux))
          return (
            <g key={e.id} opacity={dimmed ? 0.12 : 1}>
              <path
                d={d}
                fill="none"
                stroke={color}
                strokeWidth={1.1 + 4.6 * flux}
                strokeDasharray={e.kind === 'phosphorylation' ? '7 5' : 'none'}
                strokeLinecap="round"
                opacity={0.35 + 0.6 * flux}
                markerEnd={`url(#${EDGE_MARKER[e.kind]})`}
                markerStart={e.kind === 'translocation' ? 'url(#mk-loc-b)' : undefined}
              />
              {!dimmed ? (
                <text
                  x={label.x}
                  y={label.y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill={color}
                  fontFamily={FONT_MONO}
                  fontSize={9}
                  stroke="#07111D"
                  strokeWidth={3}
                  paintOrder="stroke"
                  style={{ pointerEvents: 'none' }}
                >
                  V {flux.toFixed(2)}
                </text>
              ) : null}
            </g>
          )
        })}
      </g>

      <g>
        {nodeIds.map((id) => {
          const p = positions.get(id)
          if (!p) return null
          const upper = id.toUpperCase()
          const pertVal = pertMap[upper]
          const isPert = pertVal != null
          const isKo = koSet.has(upper) || (isPert && pertVal <= 1e-6)
          const current = isKo ? 0 : (nodeValues[id] ?? nodeValues[upper] ?? 0)
          const baseline = baselineValues[id] ?? baselineValues[upper] ?? current
          const selected = selectedNode === id
          const dimmed = neighbourhood ? !neighbourhood.ids.has(id) : false
          const omicsTint = omicsColorFor?.(id) ?? null

          const currentColor = isKo
            ? COLOR.knockout
            : isPert
              ? COLOR.perturbed
              : COLOR.ringCurrent

          return (
            <g
              key={id}
              transform={`translate(${p.x},${p.y})`}
              opacity={dimmed ? 0.2 : 1}
              style={{ cursor: 'pointer' }}
              onClick={handleNodeClick(id)}
              onContextMenu={handleNodeContext(id)}
              onMouseEnter={() => setHovered(id)}
              onMouseLeave={() => setHovered(null)}
            >
              <circle
                r={RING_R}
                fill="none"
                stroke={selected ? COLOR.selected : COLOR.value}
                strokeWidth={selected ? 2 : 1}
                opacity={selected ? 1 : hovered === id ? 0.45 : 0}
              />
              <ActivityRings
                baseline={baseline}
                current={current}
                currentColor={currentColor}
              />
              <circle
                r={DISC_R}
                fill={omicsTint ?? COLOR.disc}
                stroke={isKo ? COLOR.knockout : isPert ? COLOR.perturbed : COLOR.discStroke}
                strokeWidth={1}
                strokeDasharray={isKo || isPert ? '3 2' : undefined}
              />
              {/* Hit target — keeps thin rings/labels comfortably clickable. */}
              <circle r={RING_R + 6} fill="transparent" />
              <text
                y={0}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={COLOR.value}
                fontFamily={FONT_MONO}
                fontSize={11}
                fontWeight={600}
                style={{ pointerEvents: 'none' }}
              >
                {isKo ? 'KO' : current.toFixed(2)}
              </text>
              <text
                y={36}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={selected || hovered === id ? COLOR.symbolActive : COLOR.symbol}
                fontFamily={FONT_SANS}
                fontSize={11.5}
                fontWeight={600}
                style={{ pointerEvents: 'none' }}
              >
                {id}
              </text>
              {subtitleFor(id) ? (
                <text
                  y={51}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill={COLOR.subtitle}
                  fontFamily={FONT_MONO}
                  fontSize={9}
                  style={{ pointerEvents: 'none' }}
                >
                  {subtitleFor(id)}
                </text>
              ) : null}
            </g>
          )
        })}
      </g>
    </svg>
    </div>
  )
}
