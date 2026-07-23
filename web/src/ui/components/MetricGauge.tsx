import { clsx, colors, tw } from "../design_system";
import { getHumanContext, translateMetric, toneColor } from "../translator";
import { MetricTooltip } from "./MetricTooltip";

type MetricGaugeProps = {
  metricKey: string;
  value: number;
  max?: number;
  format?: (v: number) => string;
  /** Prefer human short label; set false to show abbreviation only */
  humanLabel?: boolean;
};

export function MetricGauge({
  metricKey,
  value,
  max = 1,
  format,
  humanLabel = true,
}: MetricGaugeProps) {
  const translated = translateMetric(metricKey, value);
  const ctx = getHumanContext(metricKey);
  const pct = Math.max(0, Math.min(1, value / max));
  const tone = toneColor[translated.badgeTone] ?? colors.accent.cyan;
  const label = humanLabel ? translated.shortLabel : translated.key;
  const display = format ? format(value) : translated.displayValue;

  return (
    <div className="flex min-w-[128px] max-w-[180px] flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <MetricTooltip metric={metricKey}>
          <span className={tw.label} title={ctx.tooltip}>
            {label}
          </span>
        </MetricTooltip>
        <span className={clsx(tw.mono)} style={{ color: tone }}>
          {translated.badgeEmoji} {display}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[#1E293B]">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${pct * 100}%`, backgroundColor: tone }}
        />
      </div>
      <span className="truncate text-[10px]" style={{ color: tone }}>
        {translated.badgeLabel}
      </span>
    </div>
  );
}
