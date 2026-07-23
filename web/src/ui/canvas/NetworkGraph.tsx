/**
 * Force-directed physics graph (d3-force) — stabilized against layout thrash.
 * Positions live in refs; React re-renders are rAF-throttled while alpha cools.
 */

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { tw } from "../design_system";
import type { EdgeVisual, NodeVisual, VisualFrame } from "./types";

export type NetworkGraphProps = {
  frame: VisualFrame;
  selectedId?: string | null;
  onSelect?: (nodeId: string) => void;
  onEncyclopedia?: (nodeId: string) => void;
  onInspect?: (payload: {
    kind: "node" | "edge";
    id: string;
    inspect: Record<string, unknown>;
  }) => void;
  highlightHubs?: boolean;
  width?: number;
  height?: number;
};

type SimNode = SimulationNodeDatum & {
  id: string;
  visual: NodeVisual;
};

type SimLink = SimulationLinkDatum<SimNode> & {
  edge: EdgeVisual;
};

type RenderSnap = {
  nodes: Array<{ id: string; x: number; y: number; visual: NodeVisual }>;
  links: Array<{
    edge: EdgeVisual;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  }>;
};

export function NetworkGraph({
  frame,
  selectedId,
  onSelect,
  onEncyclopedia,
  onInspect,
  highlightHubs = true,
  width = 780,
  height = 420,
}: NetworkGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const linksRef = useRef<SimLink[]>([]);
  const [snap, setSnap] = useState<RenderSnap>({ nodes: [], links: [] });
  const [tickClock, setTickClock] = useState(0);
  const dragRef = useRef<{ id: string } | null>(null);
  const pendingPaint = useRef(false);

  const topologyKey = useMemo(
    () =>
      frame.nodes.map((n) => n.node_id).join("|") +
      "::" +
      frame.edges.map((e) => e.edge_id).join("|"),
    // Stable identity — ignore per-frame visual churn
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [frame.nodes.map((n) => n.node_id).join("|"), frame.edges.map((e) => e.edge_id).join("|")],
  );

  const activityKey = useMemo(
    () =>
      frame.nodes
        .map((n) => `${n.node_id}:${n.state}:${n.activity.toFixed(2)}:${n.mutated ? 1 : 0}`)
        .join("|") +
      "::" +
      frame.edges.map((e) => `${e.edge_id}:${e.state}:${e.flux.toFixed(2)}`).join("|"),
    [frame],
  );

  const paint = () => {
    const nodes = nodesRef.current;
    const links = linksRef.current;
    const pos = new Map(nodes.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]));
    setSnap({
      nodes: nodes.map((n) => ({
        id: n.id,
        x: n.x ?? 0,
        y: n.y ?? 0,
        visual: n.visual,
      })),
      links: links.map((l) => {
        const sId = typeof l.source === "object" ? (l.source as SimNode).id : String(l.source);
        const tId = typeof l.target === "object" ? (l.target as SimNode).id : String(l.target);
        const a = pos.get(sId) ?? { x: 0, y: 0 };
        const b = pos.get(tId) ?? { x: 0, y: 0 };
        return { edge: l.edge, x1: a.x, y1: a.y, x2: b.x, y2: b.y };
      }),
    });
  };

  const schedulePaint = () => {
    if (pendingPaint.current) return;
    pendingPaint.current = true;
    requestAnimationFrame(() => {
      pendingPaint.current = false;
      paint();
    });
  };

  // Rebuild simulation only when topology changes
  useEffect(() => {
    const prevPos = new Map(nodesRef.current.map((n) => [n.id, { x: n.x, y: n.y }]));
    const simNodes: SimNode[] = frame.nodes.map((n, i) => {
      const angle = (i / Math.max(1, frame.nodes.length)) * Math.PI * 2;
      const ring = Math.min(width, height) * 0.28;
      const kept = prevPos.get(n.node_id);
      return {
        id: n.node_id,
        visual: n,
        x: kept?.x ?? n.x ?? width / 2 + Math.cos(angle) * ring,
        y: kept?.y ?? n.y ?? height / 2 + Math.sin(angle) * ring,
        vx: 0,
        vy: 0,
      };
    });
    const byId = new Map(simNodes.map((n) => [n.id, n]));
    const simLinks: SimLink[] = frame.edges
      .filter((e) => byId.has(e.source_id) && byId.has(e.target_id))
      .map((e) => ({
        source: e.source_id,
        target: e.target_id,
        edge: e,
      }));

    simRef.current?.stop();
    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(90)
          .strength(0.5),
      )
      .force("charge", forceManyBody<SimNode>().strength(-380).distanceMax(400))
      .force("collide", forceCollide<SimNode>().radius(26).strength(0.85))
      .force("center", forceCenter(width / 2, height / 2).strength(0.06))
      .force("x", forceX(width / 2).strength(0.03))
      .force("y", forceY(height / 2).strength(0.03))
      .alpha(prevPos.size ? 0.35 : 1)
      .alphaDecay(0.028)
      .velocityDecay(0.4);

    sim.on("tick", () => {
      for (const n of simNodes) {
        n.x = Math.max(28, Math.min(width - 28, n.x ?? 0));
        n.y = Math.max(28, Math.min(height - 28, n.y ?? 0));
      }
      schedulePaint();
    });

    nodesRef.current = simNodes;
    linksRef.current = simLinks;
    simRef.current = sim;
    paint();

    return () => {
      sim.stop();
      simRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topologyKey, width, height]);

  // Sync visual appearance without restarting physics
  useEffect(() => {
    const map = new Map(frame.nodes.map((n) => [n.node_id, n]));
    for (const n of nodesRef.current) {
      const v = map.get(n.id);
      if (v) n.visual = v;
    }
    const edgeMap = new Map(frame.edges.map((e) => [e.edge_id, e]));
    for (const l of linksRef.current) {
      const e = edgeMap.get(l.edge.edge_id);
      if (e) l.edge = e;
    }
    schedulePaint();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activityKey]);

  // Pulse clock (~20fps) — avoids 60fps React thrash
  useEffect(() => {
    const id = window.setInterval(() => setTickClock((t) => t + 0.05), 50);
    return () => window.clearInterval(id);
  }, []);

  const clientToSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: clientX, y: clientY };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: clientX, y: clientY };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  };

  const onPointerDown = (e: ReactPointerEvent, nodeId: string) => {
    if (e.button === 2) return;
    e.preventDefault();
    dragRef.current = { id: nodeId };
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const node = nodesRef.current.find((n) => n.id === nodeId);
    if (node) {
      node.fx = node.x;
      node.fy = node.y;
    }
    simRef.current?.alphaTarget(0.25).restart();
    onSelect?.(nodeId);
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const node = nodesRef.current.find((n) => n.id === d.id);
    if (!node) return;
    const p = clientToSvg(e.clientX, e.clientY);
    node.fx = Math.max(28, Math.min(width - 28, p.x));
    node.fy = Math.max(28, Math.min(height - 28, p.y));
    schedulePaint();
  };

  const onPointerUp = () => {
    const d = dragRef.current;
    if (!d) return;
    const node = nodesRef.current.find((n) => n.id === d.id);
    if (node) {
      node.fx = null;
      node.fy = null;
    }
    simRef.current?.alphaTarget(0);
    dragRef.current = null;
  };

  return (
    <div className="relative h-[420px] w-full shrink-0 overflow-hidden">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="100%"
        className="h-full w-full touch-none rounded-[8px] border border-[rgba(0,229,255,0.2)] bg-[#070A10]"
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onContextMenu={(e) => e.preventDefault()}
        role="img"
        aria-label="Physics force-directed signaling pathway"
      >
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="hubGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <marker id="arrowFlow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
            <path d="M0,0 L7,3 L0,6 Z" fill="#94A3B8" />
          </marker>
        </defs>

        {snap.links.map((link) => (
          <EdgeLayer
            key={link.edge.edge_id}
            edge={link.edge}
            from={{ x: link.x1, y: link.y1 }}
            to={{ x: link.x2, y: link.y2 }}
            tick={tickClock}
            onInspect={() =>
              onInspect?.({
                kind: "edge",
                id: link.edge.edge_id,
                inspect: link.edge.inspect,
              })
            }
          />
        ))}

        {snap.nodes.map((node) => {
          const v = node.visual;
          const r = 12 + v.radius_scale * 10;
          const selected = selectedId === node.id;
          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              style={{ cursor: "grab" }}
              onPointerDown={(e) => onPointerDown(e, node.id)}
              onContextMenu={(e) => {
                e.preventDefault();
                onEncyclopedia?.(node.id);
              }}
              onDoubleClick={() => onEncyclopedia?.(node.id)}
            >
              {highlightHubs && v.crosstalk_hub && (
                <circle
                  r={r + 8}
                  fill="none"
                  stroke="#FBBF24"
                  strokeWidth={2.5}
                  opacity={0.95}
                  filter="url(#hubGlow)"
                />
              )}
              {v.mutated && (
                <circle r={r + 5} fill="none" stroke="#C084FC" strokeWidth={2} strokeDasharray="3 2" />
              )}
              <circle
                r={r}
                fill={v.fill}
                stroke={
                  selected ? "#00E5FF" : v.crosstalk_hub && highlightHubs ? "#FBBF24" : v.color
                }
                strokeWidth={selected || (v.crosstalk_hub && highlightHubs) ? 3 : 2}
                filter={
                  v.crosstalk_hub && highlightHubs
                    ? "url(#hubGlow)"
                    : v.state === "overactive"
                      ? "url(#glow)"
                      : undefined
                }
              />
              <text
                textAnchor="middle"
                y={4}
                fill="#F8FAFC"
                fontSize={11}
                fontFamily="JetBrains Mono, monospace"
                pointerEvents="none"
              >
                {v.label}
              </text>
            </g>
          );
        })}
      </svg>
      <p className={tw.label + " pointer-events-none absolute bottom-1 left-0 right-0 text-center"}>
        Physics graph · drag nodes · double-click encyclopedia · empty click = inspect placeholder
      </p>
    </div>
  );
}

function EdgeLayer({
  edge,
  from,
  to,
  tick,
  onInspect,
}: {
  edge: EdgeVisual;
  from: { x: number; y: number };
  to: { x: number; y: number };
  tick: number;
  onInspect: () => void;
}) {
  const blocked = edge.blocked || edge.state === "blocked";
  const particles: Array<{ x: number; y: number }> = [];
  if (!blocked && edge.pulse_speed > 0) {
    const n = Math.max(1, Math.round(1 + edge.pulse_speed));
    for (let i = 0; i < n; i++) {
      const phase = (tick * edge.pulse_speed * 0.35 + i / n) % 1;
      particles.push({
        x: from.x + (to.x - from.x) * phase,
        y: from.y + (to.y - from.y) * phase,
      });
    }
  }

  return (
    <g
      onContextMenu={(e) => {
        e.preventDefault();
        onInspect();
      }}
    >
      <line
        x1={from.x}
        y1={from.y}
        x2={to.x}
        y2={to.y}
        stroke={blocked ? "#64748B" : edge.color}
        strokeWidth={edge.thickness}
        strokeOpacity={blocked ? 0.45 : 0.9}
        strokeDasharray={blocked ? "6,5" : edge.dash === "none" ? undefined : edge.dash}
        markerEnd={blocked ? undefined : "url(#arrowFlow)"}
        filter={!blocked && edge.pulse_speed > 1.5 ? "url(#glow)" : undefined}
      />
      {particles.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={2.8} fill={edge.color} opacity={0.95} filter="url(#glow)" />
      ))}
    </g>
  );
}
