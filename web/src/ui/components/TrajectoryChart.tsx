import { useEffect, useMemo, useRef, useState } from "react";
import type { TrajectorySeries } from "../api/types";
import { clsx, seriesPalette, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

export type TrajectoryChartProps = {
  series: TrajectorySeries[];
  washout?: { tStart: number; tEnd: number };
  scrubTime?: number;
  onScrub?: (t: number) => void;
  height?: number;
  /** Prefer these series on by default (others start off). */
  focusIds?: string[];
};

/** Default V1 focus: ligand → receptor → oncogene driver → readout */
const DEFAULT_FOCUS = ["EGF", "EGFR", "RAS", "ERK"];

export function TrajectoryChart({
  series,
  washout,
  scrubTime,
  onScrub,
  height = 280,
  focusIds = DEFAULT_FOCUS,
}: TrajectoryChartProps) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setEnabled((prev) => {
      const next = { ...prev };
      const focus = new Set(focusIds.map((s) => s.toUpperCase()));
      for (const s of series) {
        if (next[s.id] === undefined) {
          const key = (s.name || s.id).toUpperCase();
          next[s.id] = focus.size === 0 || focus.has(key) || focus.has(s.id.toUpperCase());
        }
      }
      return next;
    });
  }, [series, focusIds]);

  const svgRef = useRef<SVGSVGElement>(null);
  const pad = { top: 28, right: 20, bottom: 44, left: 52 };
  const width = 720;

  const { tMin, tMax, yMin, yMax } = useMemo(() => {
    const visible = series.filter((s) => enabled[s.id] !== false);
    const allT = visible.flatMap((s) => s.t);
    const allY = visible.flatMap((s) => s.y);
    return {
      tMin: allT.length ? Math.min(...allT) : 0,
      tMax: allT.length ? Math.max(...allT) : 1,
      yMin: 0,
      yMax: allY.length ? Math.max(0.2, Math.max(...allY) * 1.12) : 1,
    };
  }, [series, enabled]);

  const xScale = (t: number) =>
    pad.left + ((t - tMin) / Math.max(1e-9, tMax - tMin)) * (width - pad.left - pad.right);
  const yScale = (y: number) =>
    pad.top + (1 - (y - yMin) / Math.max(1e-9, yMax - yMin)) * (height - pad.top - pad.bottom);

  const scrub = scrubTime ?? tMin;
  const scrubPct = ((scrub - tMin) / Math.max(1e-9, tMax - tMin)) * 100;

  const onPointer = (clientX: number) => {
    const svg = svgRef.current;
    if (!svg || !onScrub) return;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * width;
    const frac = (x - pad.left) / Math.max(1e-9, width - pad.left - pad.right);
    const t = tMin + Math.max(0, Math.min(1, frac)) * (tMax - tMin);
    onScrub(t);
  };

  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => tMin + f * (tMax - tMin));
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => yMin + (1 - f) * (yMax - yMin));

  return (
    <GlassPanel
      title="Signal over time"
      bodyClassName="space-y-3 p-3"
      actions={
        <span className={tw.mono}>
          t = {scrub.toFixed(1)} s
        </span>
      }
    >
      <p className="text-[12px] text-[#94A3B8]">
        Toggle traces below. Drag the chart or use the playhead to scrub simulation time.
        {washout ? " Amber band = active dosing window." : ""}
      </p>

      <div className="flex flex-wrap gap-1.5">
        {series.map((s, i) => {
          const on = enabled[s.id] !== false;
          const color = s.color ?? seriesPalette[i % seriesPalette.length];
          return (
            <button
              key={s.id}
              type="button"
              className={clsx(
                "rounded-md border px-2 py-0.5 font-mono text-[11px]",
                on
                  ? "border-transparent text-[#0B0F17]"
                  : "border-[rgba(148,163,184,0.25)] text-[#64748B] line-through opacity-60",
              )}
              style={{ backgroundColor: on ? color : "transparent" }}
              onClick={() => setEnabled((e) => ({ ...e, [s.id]: !on }))}
            >
              {s.name}
            </button>
          );
        })}
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full touch-none select-none rounded-md border border-[rgba(148,163,184,0.12)] bg-[#0A0E16]"
        role="img"
        aria-label="Protein concentration vs time"
        onPointerDown={(e) => {
          (e.target as Element).setPointerCapture?.(e.pointerId);
          onPointer(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.buttons === 1) onPointer(e.clientX);
        }}
      >
        <rect x={0} y={0} width={width} height={height} fill="transparent" />

        {washout && (
          <g>
            <rect
              x={xScale(washout.tStart)}
              y={pad.top}
              width={Math.max(0, xScale(washout.tEnd) - xScale(washout.tStart))}
              height={height - pad.top - pad.bottom}
              fill="rgba(255, 184, 0, 0.14)"
            />
            <text
              x={xScale((washout.tStart + washout.tEnd) / 2)}
              y={pad.top + 14}
              textAnchor="middle"
              fill="#FFB800"
              fontSize={10}
              fontFamily="IBM Plex Mono, monospace"
            >
              dosing window
            </text>
          </g>
        )}

        {yTicks.map((val, i) => {
          const y = yScale(val);
          return (
            <g key={`y-${i}`}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y}
                y2={y}
                stroke="rgba(148,163,184,0.12)"
              />
              <text
                x={pad.left - 8}
                y={y + 3}
                textAnchor="end"
                fill="#94A3B8"
                fontSize={10}
                fontFamily="IBM Plex Mono, monospace"
              >
                {val.toFixed(2)}
              </text>
            </g>
          );
        })}

        {xTicks.map((val, i) => {
          const x = xScale(val);
          return (
            <g key={`x-${i}`}>
              <line
                x1={x}
                x2={x}
                y1={pad.top}
                y2={height - pad.bottom}
                stroke="rgba(148,163,184,0.08)"
              />
              <text
                x={x}
                y={height - 14}
                textAnchor="middle"
                fill="#94A3B8"
                fontSize={10}
                fontFamily="IBM Plex Mono, monospace"
              >
                {val.toFixed(0)}s
              </text>
            </g>
          );
        })}

        <text
          x={14}
          y={height / 2}
          fill="#64748B"
          fontSize={10}
          fontFamily="IBM Plex Sans, sans-serif"
          transform={`rotate(-90 14 ${height / 2})`}
        >
          concentration
        </text>
        <text
          x={width / 2}
          y={height - 2}
          textAnchor="middle"
          fill="#64748B"
          fontSize={10}
          fontFamily="IBM Plex Sans, sans-serif"
        >
          time (seconds)
        </text>

        {series.map((s, i) => {
          if (enabled[s.id] === false || s.t.length < 2) return null;
          const color = s.color ?? seriesPalette[i % seriesPalette.length];
          const d = s.t
            .map((t, j) => `${j === 0 ? "M" : "L"} ${xScale(t).toFixed(2)} ${yScale(s.y[j]!).toFixed(2)}`)
            .join(" ");
          return (
            <path key={s.id} d={d} fill="none" stroke={color} strokeWidth={2.25} strokeLinejoin="round" />
          );
        })}

        {/* Playhead with visible handle */}
        <line
          x1={xScale(scrub)}
          x2={xScale(scrub)}
          y1={pad.top}
          y2={height - pad.bottom}
          stroke="#00F0FF"
          strokeWidth={2}
        />
        <circle
          cx={xScale(scrub)}
          cy={pad.top + 8}
          r={6}
          fill="#0B0F17"
          stroke="#00F0FF"
          strokeWidth={2}
        />
      </svg>

      <label className="block space-y-1">
        <div className="flex items-baseline justify-between">
          <span className={tw.label}>Simulation playhead</span>
          <span className={tw.mono}>
            {scrub.toFixed(1)} / {tMax.toFixed(0)} s
          </span>
        </div>
        <input
          type="range"
          min={tMin}
          max={tMax}
          step={Math.max(0.05, (tMax - tMin) / 200)}
          value={scrub}
          onChange={(e) => onScrub?.(Number(e.target.value))}
          className="vs-slider w-full"
          aria-label="Simulation playhead"
          style={{
            background: `linear-gradient(to right, #00F0FF 0%, #00F0FF ${scrubPct}%, #1E293B ${scrubPct}%, #1E293B 100%)`,
          }}
        />
      </label>
    </GlassPanel>
  );
}
