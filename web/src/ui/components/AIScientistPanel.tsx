import { useMemo } from "react";
import type { AgentLogEvent, AgentPlanResult } from "../api/types";
import { clsx, colors, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

export type AIScientistPanelProps = {
  collapsed?: boolean;
  onToggle?: () => void;
  result: AgentPlanResult | null;
  loading?: boolean;
  error?: string | null;
  onLaunch?: () => void;
  goal: string;
  onGoalChange?: (g: string) => void;
};

const levelColor: Record<AgentLogEvent["level"], string> = {
  info: colors.text.secondary,
  hypothesis: colors.accent.cyan,
  experiment: colors.accent.amber,
  result: colors.accent.lime,
  warn: colors.accent.rose,
};

function renderBrief(md: string): string {
  return md
    .replace(/^### (.*)$/gm, '<h3 class="text-[13px] font-semibold text-[#F8FAFC] mt-3 mb-1">$1</h3>')
    .replace(/^## (.*)$/gm, '<h2 class="text-[14px] font-semibold text-[#00E5FF] mt-4 mb-1">$1</h2>')
    .replace(/^# (.*)$/gm, '<h1 class="text-[16px] font-semibold text-[#F8FAFC] mb-2">$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="font-mono text-[11px] text-[#2DD4BF]">$1</code>')
    .replace(/^- (.*)$/gm, '<li class="ml-4 list-disc text-[12px] text-[#94A3B8]">$1</li>')
    .replace(
      /\| (.+) \|/g,
      '<div class="font-mono text-[11px] text-[#CBD5E1] border-b border-[rgba(148,163,184,0.12)] py-0.5">$1</div>',
    )
    .replace(/\n\n/g, "<br/><br/>");
}

export function AIScientistPanel({
  collapsed,
  onToggle,
  result,
  loading,
  error,
  onLaunch,
  goal,
  onGoalChange,
}: AIScientistPanelProps) {
  const html = useMemo(
    () => (result?.briefMarkdown ? renderBrief(result.briefMarkdown) : ""),
    [result?.briefMarkdown],
  );

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className={clsx(tw.btnGhost, "h-full w-12 px-0")}
        style={{ writingMode: "vertical-rl" }}
        aria-label="Expand AI Scientist panel"
      >
        AI Scientist
      </button>
    );
  }

  return (
    <GlassPanel
      title="AI Scientist"
      className="h-full"
      bodyClassName="flex flex-col gap-3 overflow-hidden"
      actions={
        <button type="button" className={tw.btnGhost} onClick={onToggle} aria-label="Collapse panel">
          Collapse
        </button>
      }
    >
      <label className="block space-y-1">
        <span className={tw.label}>Research goal</span>
        <textarea
          className={clsx(tw.input, "min-h-[64px] resize-y font-sans text-[12px] leading-relaxed")}
          value={goal}
          onChange={(e) => onGoalChange?.(e.target.value)}
          placeholder="Find a two-drug combination that halts ERK over-activation…"
        />
      </label>

      <button
        type="button"
        className={tw.btnPrimary}
        disabled={loading}
        onClick={onLaunch}
      >
        {loading ? "Running planner…" : "Launch AI Scientist"}
      </button>

      {error && <p className="text-[12px] text-[#FB7185]">{error}</p>}

      {result && (
        <div className="grid grid-cols-3 gap-2">
          <LasCard label="LAS" value={result.las} />
          <LasCard label="HSI" value={result.metrics?.hsi ?? Number.NaN} />
          <LasCard label="status" valueLabel={result.status} />
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        <div>
          <h3 className={tw.label}>Execution stream</h3>
          <ul className="mt-1 space-y-1.5">
            {(result?.logs ?? []).map((ev) => (
              <li key={ev.id} className="rounded-[6px] border border-[rgba(148,163,184,0.12)] bg-[#151C2C] px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider"
                    style={{ color: levelColor[ev.level] }}
                  >
                    {ev.level}
                  </span>
                  <span className="font-mono text-[10px] text-[#64748B]">
                    {new Date(ev.t).toLocaleTimeString()}
                  </span>
                </div>
                <p className="mt-0.5 text-[12px] leading-snug text-[#E2E8F0]">{ev.message}</p>
              </li>
            ))}
            {!result?.logs?.length && (
              <li className={tw.label}>Awaiting planner launch…</li>
            )}
          </ul>
        </div>

        {html && (
          <div>
            <h3 className={tw.label}>Discovery brief</h3>
            <article
              className="mt-1 rounded-[8px] border border-[rgba(0,229,255,0.2)] bg-[#0B0F17]/80 p-3 text-[12px] leading-relaxed text-[#CBD5E1]"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          </div>
        )}
      </div>
    </GlassPanel>
  );
}

function LasCard({
  label,
  value,
  valueLabel,
}: {
  label: string;
  value?: number;
  valueLabel?: string;
}) {
  return (
    <div className="rounded-[8px] border border-[rgba(0,229,255,0.25)] bg-[#151C2C] px-2 py-1.5">
      <div className={tw.label}>{label}</div>
      <div className={tw.mono} style={{ color: colors.accent.cyan }}>
        {valueLabel ?? (Number.isFinite(value) ? value!.toFixed(3) : "—")}
      </div>
    </div>
  );
}
