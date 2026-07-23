import type { ReactNode } from "react";
import { getHumanContext } from "../translator";
import { clsx } from "../design_system";

export type MetricTooltipProps = {
  metric: string;
  children: ReactNode;
  className?: string;
};

/**
 * Hover glossary tooltip for scientific abbreviations.
 * Uses native `title` plus an accessible described-by pattern.
 */
export function MetricTooltip({ metric, children, className }: MetricTooltipProps) {
  const ctx = getHumanContext(metric);
  const tip = `${ctx.shortLabel} — ${ctx.tooltip}`;
  return (
    <span
      className={clsx("relative inline-flex cursor-help border-b border-dotted border-[rgba(0,229,255,0.45)]", className)}
      title={tip}
      aria-label={tip}
    >
      {children}
    </span>
  );
}
