import { useState, type ReactNode } from "react";
import { clsx, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

export type CollapsibleTelemetryProps = {
  title?: string;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
};

/**
 * Progressive-disclosure accordion for raw biophysical matrices / ODE params.
 */
export function CollapsibleTelemetry({
  title = "Advanced Omics & Raw Biophysical Telemetry",
  defaultOpen = false,
  children,
  className,
}: CollapsibleTelemetryProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <GlassPanel
      className={className}
      bodyClassName="p-0"
      title={undefined}
    >
      <button
        type="button"
        className={clsx(
          "flex w-full items-center justify-between gap-2 border-b border-[rgba(148,163,184,0.12)] px-3 py-2 text-left",
          tw.btnGhost,
          "rounded-none border-0 hover:bg-[#151C2C]",
        )}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-mono text-[12px] text-[#00F0FF]">
          {open ? "▲ Hide Advanced Omics & Telemetry" : `▼ ${title}`}
        </span>
        <span className={tw.label}>{open ? "collapse" : "expand"}</span>
      </button>
      {open && <div className="space-y-2 p-3">{children}</div>}
    </GlassPanel>
  );
}
