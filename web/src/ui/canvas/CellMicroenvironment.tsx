import { useMemo } from "react";
import { tw } from "../design_system";
import type { MicroenvironmentVisual } from "./types";

export type CellMicroenvironmentProps = {
  scene: MicroenvironmentVisual;
  width?: number;
  height?: number;
  onInspectCell?: (cellId: string, inspect: Record<string, unknown>) => void;
};

/**
 * Spatial TME grid: tumor / CTL / macrophages with cytokine diffusion heatmaps.
 */
export function CellMicroenvironment({
  scene,
  width = 780,
  height = 360,
  onInspectCell,
}: CellMicroenvironmentProps) {
  const field = scene.fields[0];
  const cells = scene.cells;

  const heatRects = useMemo(() => {
    if (!field) return [];
    const gw = field.grid_w;
    const gh = field.grid_h;
    const cw = width / gw;
    const ch = height / gh;
    const rects: Array<{ x: number; y: number; w: number; h: number; opacity: number; color: string }> = [];
    for (let gy = 0; gy < gh; gy++) {
      for (let gx = 0; gx < gw; gx++) {
        const v = field.values[gy]?.[gx] ?? 0;
        if (v < 0.05) continue;
        rects.push({
          x: gx * cw,
          y: gy * ch,
          w: cw,
          h: ch,
          opacity: Math.min(0.55, v * 0.65),
          color: field.color,
        });
      }
    }
    // Overlay second cytokine faintly
    const f2 = scene.fields[1];
    if (f2) {
      for (let gy = 0; gy < f2.grid_h; gy++) {
        for (let gx = 0; gx < f2.grid_w; gx++) {
          const v = f2.values[gy]?.[gx] ?? 0;
          if (v < 0.08) continue;
          rects.push({
            x: gx * (width / f2.grid_w),
            y: gy * (height / f2.grid_h),
            w: width / f2.grid_w,
            h: height / f2.grid_h,
            opacity: Math.min(0.4, v * 0.5),
            color: f2.color,
          });
        }
      }
    }
    return rects;
  }, [scene.fields, field, width, height]);

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full rounded-[8px] border border-[rgba(0,229,255,0.2)] bg-[#070A10]"
        role="img"
        aria-label="Tumor microenvironment spatial map"
      >
        {heatRects.map((r, i) => (
          <rect
            key={i}
            x={r.x}
            y={r.y}
            width={r.w}
            height={r.h}
            fill={r.color}
            opacity={r.opacity}
          />
        ))}

        {/* expanding ring hints */}
        {scene.fields.map((f) => {
          const peak = findPeak(f.values);
          return (
            <circle
              key={f.cytokine}
              cx={peak.x * width}
              cy={peak.y * height}
              r={40 + 25 * Math.sin(scene.t / 6)}
              fill="none"
              stroke={f.color}
              strokeOpacity={0.35}
              strokeWidth={1.5}
              strokeDasharray="4 3"
            />
          );
        })}

        {cells.map((c) => {
          const shape =
            c.kind === "tumor" ? "circle" : c.kind === "ctl" ? "diamond" : "square";
          const cx = c.x * width;
          const cy = c.y * height;
          return (
            <g
              key={c.cell_id}
              transform={`translate(${cx}, ${cy})`}
              style={{ cursor: "pointer" }}
              onClick={() => onInspectCell?.(c.cell_id, c.inspect)}
              onContextMenu={(e) => {
                e.preventDefault();
                onInspectCell?.(c.cell_id, c.inspect);
              }}
            >
              {shape === "circle" && <circle r={10} fill={c.color} opacity={0.9} />}
              {shape === "diamond" && (
                <polygon points="0,-10 10,0 0,10 -10,0" fill={c.color} opacity={0.9} />
              )}
              {shape === "square" && (
                <rect x={-8} y={-8} width={16} height={16} rx={2} fill={c.color} opacity={0.9} />
              )}
              <title>{`${c.kind} · right-click to inspect`}</title>
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-[#94A3B8]">
        <span>● tumor</span>
        <span>◆ CTL</span>
        <span>■ macrophage</span>
        <span className={tw.mono}>
          cytokines: {scene.fields.map((f) => f.cytokine).join(" · ")} diffusion heatmap
        </span>
      </div>
    </div>
  );
}

function findPeak(values: number[][]): { x: number; y: number } {
  let best = 0;
  let bx = 0.5;
  let by = 0.5;
  const gh = values.length;
  const gw = values[0]?.length ?? 1;
  for (let gy = 0; gy < gh; gy++) {
    for (let gx = 0; gx < gw; gx++) {
      const v = values[gy]?.[gx] ?? 0;
      if (v > best) {
        best = v;
        bx = (gx + 0.5) / gw;
        by = (gy + 0.5) / gh;
      }
    }
  }
  return { x: bx, y: by };
}
