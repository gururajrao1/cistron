import { VISUAL_LEGEND } from "./visualEngine";
import { tw } from "../design_system";

export function VisualLegend({ showCrosstalkHubs = true }: { showCrosstalkHubs?: boolean }) {
  const items = [
    VISUAL_LEGEND.overactive,
    VISUAL_LEGEND.homeostatic,
    VISUAL_LEGEND.inhibited,
    VISUAL_LEGEND.flowing,
    VISUAL_LEGEND.blocked,
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[8px] border border-[rgba(148,163,184,0.12)] bg-[#151C2C] px-3 py-2">
      <span className={tw.label}>Visual states</span>
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5 text-[11px] text-[#E2E8F0]">
          <i
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: item.color, boxShadow: `0 0 8px ${item.color}` }}
            aria-hidden
          />
          <span aria-hidden>{item.emoji}</span>
          {item.label}
        </span>
      ))}
      {showCrosstalkHubs && (
        <span className="inline-flex items-center gap-1.5 text-[11px] text-[#E2E8F0]">
          <i
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: "#FBBF24", boxShadow: "0 0 10px #FBBF24" }}
            aria-hidden
          />
          Crosstalk hub (MAPK ∩ PI3K-AKT ∩ JAK-STAT)
        </span>
      )}
    </div>
  );
}
