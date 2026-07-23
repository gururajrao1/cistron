import type { CausalExplanation, CausalNarrativePayload } from "../api/types";
import { clsx, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

export type CausalNarrativePanelProps = {
  causal: CausalNarrativePayload | null;
  loading?: boolean;
};

function CascadeChain({ names }: { names: string[] }) {
  if (!names.length) return null;
  return (
    <div
      className="flex min-h-fit flex-wrap items-center gap-1.5 py-1"
      aria-label="Causal cascade"
    >
      {names.map((name, i) => (
        <span key={`${name}-${i}`} className="inline-flex items-center gap-1.5">
          <span
            className={clsx(
              "rounded-md border px-2 py-1 font-mono text-[12px] text-[#F8FAFC]",
              "border-[rgba(0,229,255,0.55)] bg-[rgba(0,229,255,0.14)]",
              "shadow-[0_0_12px_rgba(0,229,255,0.35)]",
            )}
          >
            {name}
          </span>
          {i < names.length - 1 && (
            <span className="inline-block font-mono text-[14px] text-[#00E5FF]" aria-hidden>
              →
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

function ExplanationBlock({
  title,
  items,
  tone,
}: {
  title: string;
  items: CausalExplanation[];
  tone: "rose" | "cyan";
}) {
  if (!items.length) return null;
  return (
    <div className="min-h-fit space-y-2">
      <p className={tw.label}>{title}</p>
      {items.map((ex) => (
        <div
          key={`${ex.kind}-${ex.node_id}`}
          className={clsx(
            "min-h-fit overflow-visible rounded-[8px] border p-3",
            tone === "rose"
              ? "border-[rgba(251,113,133,0.35)] bg-[rgba(251,113,133,0.08)]"
              : "border-[rgba(56,189,248,0.35)] bg-[rgba(56,189,248,0.08)]",
          )}
        >
          <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-mono text-[13px] text-[#F8FAFC]">{ex.node_name}</span>
            <span className={tw.mono}>
              {ex.percent_change >= 0 ? "+" : ""}
              {ex.percent_change.toFixed(0)}% · conf {(ex.confidence * 100).toFixed(0)}%
            </span>
          </div>
          <p className="whitespace-normal break-words text-[13px] leading-relaxed text-[#E2E8F0]">
            {ex.narrative}
          </p>
          {ex.chain.length > 0 && (
            <ul className="mt-2 space-y-1 border-t border-[rgba(148,163,184,0.12)] pt-2">
              {ex.chain.map((step, i) => (
                <li key={i} className="whitespace-normal break-words text-[11px] leading-relaxed text-[#94A3B8]">
                  <span className="font-mono text-[#00E5FF]">
                    {step.source_name} → {step.target_name}
                  </span>
                  <span className="text-[#64748B]"> ({step.interaction})</span>
                  {" — "}
                  {step.evidence}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * Causal narrative panel — auto-height cards with scroll, no mid-sentence clipping.
 */
export function CausalNarrativePanel({ causal, loading }: CausalNarrativePanelProps) {
  return (
    <GlassPanel
      title="Causal narrative"
      variant="active"
      className="min-h-fit shrink-0"
      bodyClassName="min-h-fit max-h-[min(70vh,720px)] space-y-3 overflow-y-auto p-3"
      actions={
        causal ? (
          <span className={clsx(tw.mono, "max-w-[320px] truncate")}>
            {causal.control_label} vs {causal.perturbed_label}
          </span>
        ) : (
          <span className={tw.mono}>idle</span>
        )
      }
    >
      {loading && <p className={tw.label}>Generating causal explanations…</p>}
      {!loading && !causal && (
        <p className="text-[13px] leading-relaxed text-[#94A3B8]">
          Run an ODE experiment to populate Why? narratives from CausalBioReasoner.
        </p>
      )}
      {causal && (
        <>
          <p className="whitespace-normal break-words text-[13px] leading-relaxed text-[#E2E8F0]">
            {causal.overview_narrative}
          </p>
          <CascadeChain names={causal.cascade ?? []} />
          <div className="grid min-h-fit gap-3 md:grid-cols-2">
            <ExplanationBlock title="Why activated" items={causal.activated ?? []} tone="rose" />
            <ExplanationBlock title="Why suppressed" items={causal.inactivated ?? []} tone="cyan" />
          </div>
        </>
      )}
    </GlassPanel>
  );
}
