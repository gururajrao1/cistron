import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { NetworkEdge, NetworkNode, PatientNetwork } from "../api/types";
import { colors, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

export type NetworkGraphCanvasProps = {
  network: PatientNetwork | null;
  loading?: boolean;
  selectedId?: string | null;
  onSelect?: (nodeId: string) => void;
};

type Pos = Record<string, { x: number; y: number }>;

function edgeColor(kind: NetworkEdge["kind"]): string {
  if (kind === "inhibition") return colors.accent.rose;
  if (kind === "phosphorylation") return colors.accent.cyan;
  return colors.accent.teal;
}

export function NetworkGraphCanvas({
  network,
  loading,
  selectedId,
  onSelect,
}: NetworkGraphCanvasProps) {
  const [positions, setPositions] = useState<Pos>({});
  const drag = useRef<{ id: string; lastX: number; lastY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = 760;
  const height = 380;

  const nodes = network?.nodes ?? [];
  const edges = network?.edges ?? [];

  const pos = useMemo(() => {
    const next: Pos = { ...positions };
    for (const n of nodes) {
      if (!next[n.id]) next[n.id] = { x: n.x, y: n.y };
    }
    return next;
  }, [nodes, positions]);

  const clientToSvgScale = () => {
    const svg = svgRef.current;
    if (!svg) return { sx: 1, sy: 1 };
    const rect = svg.getBoundingClientRect();
    return { sx: width / Math.max(1, rect.width), sy: height / Math.max(1, rect.height) };
  };

  const onPointerDown = (e: ReactPointerEvent, node: NetworkNode) => {
    drag.current = { id: node.id, lastX: e.clientX, lastY: e.clientY };
    (e.target as Element).setPointerCapture?.(e.pointerId);
    onSelect?.(node.id);
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const { sx, sy } = clientToSvgScale();
    const dx = (e.clientX - d.lastX) * sx;
    const dy = (e.clientY - d.lastY) * sy;
    d.lastX = e.clientX;
    d.lastY = e.clientY;
    setPositions((prev) => {
      const cur = prev[d.id] ?? pos[d.id];
      if (!cur) return prev;
      return {
        ...prev,
        [d.id]: {
          x: Math.max(24, Math.min(width - 24, cur.x + dx)),
          y: Math.max(24, Math.min(height - 24, cur.y + dy)),
        },
      };
    });
  };

  const onPointerUp = () => {
    drag.current = null;
  };

  return (
    <GlassPanel title="Signaling network topology" bodyClassName="space-y-2">
      {loading && <p className={tw.label}>Loading patient network…</p>}
      {!loading && !network && <p className={tw.label}>No network loaded.</p>}
      {network && (
        <>
          <svg
            ref={svgRef}
            viewBox={`0 0 ${width} ${height}`}
            className="h-auto w-full touch-none"
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            role="img"
            aria-label="Directed signaling graph"
          >
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                <path d="M0,0 L7,3 L0,6 Z" fill="#94A3B8" />
              </marker>
            </defs>

            {edges.map((e) => {
              const a = pos[e.source];
              const b = pos[e.target];
              if (!a || !b) return null;
              const stroke = edgeColor(e.kind);
              return (
                <line
                  key={e.id}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={stroke}
                  strokeWidth={1 + e.weight * 2.5}
                  strokeOpacity={0.85}
                  strokeDasharray={e.kind === "phosphorylation" ? "5 4" : undefined}
                  markerEnd="url(#arrow)"
                />
              );
            })}

            {nodes.map((n) => {
              const p = pos[n.id];
              if (!p) return null;
              const r = 14 + n.centrality * 10;
              const heat = Math.min(1, Math.abs(n.attribution));
              const fill = `rgba(0, 229, 255, ${0.15 + heat * 0.55})`;
              const selected = selectedId === n.id;
              return (
                <g
                  key={n.id}
                  transform={`translate(${p.x}, ${p.y})`}
                  onPointerDown={(ev) => onPointerDown(ev, n)}
                  style={{ cursor: "grab" }}
                >
                  <circle
                    r={r}
                    fill={fill}
                    stroke={
                      n.mutated
                        ? colors.accent.rose
                        : selected
                          ? colors.accent.cyan
                          : colors.border.cyanMuted
                    }
                    strokeWidth={selected || n.mutated ? 2.5 : 1.5}
                  />
                  <text
                    textAnchor="middle"
                    y={4}
                    fill={colors.text.primary}
                    fontSize={11}
                    fontFamily="JetBrains Mono, monospace"
                    pointerEvents="none"
                  >
                    {n.label}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="flex flex-wrap gap-3 text-[11px] text-[#94A3B8]">
            <span>
              <i className="mr-1 inline-block h-2 w-4 rounded-sm bg-[#2DD4BF]" /> activation
            </span>
            <span>
              <i className="mr-1 inline-block h-2 w-4 rounded-sm bg-[#FB7185]" /> inhibition
            </span>
            <span>
              <i className="mr-1 inline-block h-2 w-4 rounded-sm border border-dashed border-[#00E5FF]" />{" "}
              phospho
            </span>
            <span className={tw.mono}>IG heat → cyan · rose ring = mutated</span>
          </div>
        </>
      )}
    </GlassPanel>
  );
}
