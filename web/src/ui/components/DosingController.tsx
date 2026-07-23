import { useId } from "react";
import type { DoseParams } from "../api/types";
import { clsx, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

const PATHWAY_TARGETS = ["EGFR", "RAS", "RAF", "MEK", "ERK", "PI3K", "AKT", "TP53"] as const;

export type DosingControllerProps = {
  doses: DoseParams[];
  onChange: (next: DoseParams[]) => void;
  pathwayId: string;
  onPathwayChange?: (id: string) => void;
  tHorizon: number;
  onTHorizonChange?: (v: number) => void;
  dt: number;
  onDtChange?: (v: number) => void;
};

function PrecisionSlider({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  const id = useId();
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <label className="block space-y-1" htmlFor={id}>
      <div className="flex items-baseline justify-between gap-2">
        <span className={tw.label}>{label}</span>
        <span className={tw.mono}>
          {value.toFixed(step < 0.1 ? 2 : step < 1 ? 2 : 1)}
          <span className="text-[#64748B]"> {unit}</span>
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="vs-slider w-full"
        style={{
          background: `linear-gradient(to right, #00E5FF 0%, #00E5FF ${pct}%, #1E293B ${pct}%, #1E293B 100%)`,
        }}
      />
    </label>
  );
}

export function DosingController({
  doses,
  onChange,
  pathwayId,
  onPathwayChange,
  tHorizon,
  onTHorizonChange,
  dt,
  onDtChange,
}: DosingControllerProps) {
  const update = (index: number, patch: Partial<DoseParams>) => {
    onChange(doses.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  };

  return (
    <GlassPanel title="Dosing & pathway" className="min-h-fit" bodyClassName="min-h-fit space-y-4 overflow-y-auto p-3">
      <div className="space-y-1.5">
        <span className={tw.label}>Pathway target</span>
        <select
          className={tw.input}
          value={pathwayId}
          onChange={(e) => onPathwayChange?.(e.target.value)}
        >
          <option value="hsa04010">hsa04010 · MAPK signaling</option>
          <option value="hsa04151">hsa04151 · PI3K-Akt</option>
          <option value="hsa04115">hsa04115 · p53 signaling</option>
          <option value="hsa04210">hsa04210 · Apoptosis</option>
          <option value="hsa04630">hsa04630 · JAK-STAT</option>
          <option value="hsa04150">hsa04150 · mTOR</option>
          <option value="hsa04310">hsa04310 · Wnt</option>
          <option value="hsa04350">hsa04350 · TGF-beta</option>
          <option value="crosstalk_multi">
            Multi-Pathway Crosstalk · MAPK + PI3K-AKT + JAK-STAT
          </option>
          <option value="demo_mapk">demo_mapk · clinical scaffold</option>
        </select>
        {pathwayId === "crosstalk_multi" && (
          <p className={tw.mono}>
            Hub glow highlights EGFR / RAS / TP53 bridging branches.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
            <PrecisionSlider
              label="Simulation Duration"
              value={tHorizon}
              min={5}
              max={60}
              step={1}
              unit="s"
              onChange={(v) => onTHorizonChange?.(v)}
            />
            <PrecisionSlider
              label="Integration Step"
              value={dt}
              min={0.1}
              max={2}
              step={0.1}
              unit="s"
              onChange={(v) => onDtChange?.(v)}
            />
          </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className={tw.label}>Multi-drug combo</span>
          <span className={tw.mono}>{doses.filter((d) => d.enabled).length} active</span>
        </div>

        {doses.map((dose, index) => (
          <div
            key={dose.agentId}
            className={clsx(
              "space-y-2 rounded-[8px] border p-2.5 transition-colors",
              dose.enabled
                ? "border-[rgba(0,229,255,0.35)] bg-[#151C2C]"
                : "border-[rgba(148,163,184,0.12)] bg-transparent opacity-70",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={dose.enabled}
                  onChange={(e) => update(index, { enabled: e.target.checked })}
                  className="accent-[#00E5FF]"
                />
                <span className={tw.mono}>{dose.agentId}</span>
              </label>
              <select
                className={clsx(tw.input, "w-auto")}
                value={dose.target}
                onChange={(e) => update(index, { target: e.target.value })}
                disabled={!dose.enabled}
              >
                {PATHWAY_TARGETS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <PrecisionSlider
              label="Initial Drug Concentration"
              value={dose.c0}
              min={0.1}
              max={10}
              step={0.125}
              unit="μM"
              onChange={(v) => update(index, { c0: v })}
            />
            <PrecisionSlider
              label="Dosing Window Start"
              value={dose.tStart}
              min={0}
              max={Math.max(1, dose.tEnd - 0.5)}
              step={0.5}
              unit="s"
              onChange={(v) => update(index, { tStart: v })}
            />
            <PrecisionSlider
              label="Dosing Window End"
              value={dose.tEnd}
              min={dose.tStart + 0.5}
              max={tHorizon}
              step={0.5}
              unit="s"
              onChange={(v) => update(index, { tEnd: v })}
            />
            {dose.ki != null && (
              <p className={clsx(tw.mono, "text-[#64748B]")}>
                Inhibition Constant (K<sub>i</sub>) = {dose.ki.toExponential(2)} M
              </p>
            )}
          </div>
        ))}
      </div>
    </GlassPanel>
  );
}
