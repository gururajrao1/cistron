import { buildExecutiveSentence, translateMetric, toneColor } from "../translator";
import { tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";
import { MetricTooltip } from "./MetricTooltip";

export type ExecutiveSummaryProps = {
  hsi?: number;
  las?: number;
  pds?: number;
  readout?: string;
  readoutValue?: number;
  sentenceOverride?: string;
};

export function ExecutiveSummaryCard({
  hsi,
  las,
  pds,
  readout,
  readoutValue,
  sentenceOverride,
}: ExecutiveSummaryProps) {
  const sentence =
    sentenceOverride ??
    buildExecutiveSentence({ hsi, las, pds, readout, readoutValue });

  const badges = [
    hsi != null ? translateMetric("HSI", hsi) : null,
    pds != null ? translateMetric("PDS", pds) : null,
    las != null ? translateMetric("LAS", las) : null,
  ].filter(Boolean);

  return (
    <GlassPanel title="Executive summary" variant="active" bodyClassName="space-y-3">
      <p className="text-[14px] leading-relaxed text-[#E2E8F0]">{sentence}</p>
      {badges.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {badges.map((b) =>
            b ? (
              <MetricTooltip key={b.key} metric={b.key}>
                <span
                  className="inline-flex items-center gap-1.5 rounded-[6px] border px-2 py-1 text-[11px]"
                  style={{
                    borderColor: toneColor[b.badgeTone],
                    color: toneColor[b.badgeTone],
                    background: "rgba(15,23,42,0.6)",
                  }}
                >
                  <span aria-hidden>{b.badgeEmoji}</span>
                  <span className={tw.mono}>{b.key}</span>
                  <span className="text-[#F8FAFC]">{b.badgeLabel}</span>
                  <span className={tw.mono}>({b.displayValue})</span>
                </span>
              </MetricTooltip>
            ) : null,
          )}
        </div>
      )}
      <p className={tw.label}>
        Plain-language status · hover badges for glossary definitions · raw floats unchanged for solvers
      </p>
    </GlassPanel>
  );
}
