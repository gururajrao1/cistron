import type { ReactNode } from "react";
import { clsx, tw } from "../design_system";

export type LabStageId = "experiment" | "pathway" | "docking" | "explorer";

export const LAB_STAGES: {
  id: LabStageId;
  label: string;
  hint: string;
  icon: string;
}[] = [
  {
    id: "experiment",
    label: "Experiment Studio",
    hint: "Presets · dosing · Healthy vs Cancer",
    icon: "EXP",
  },
  {
    id: "pathway",
    label: "Visual Pathway Canvas",
    hint: "KEGG maps · flux · scrubber",
    icon: "NET",
  },
  {
    id: "docking",
    label: "3D Structural Docking",
    hint: "Pocket · ligand · ΔG / Ki",
    icon: "3D",
  },
  {
    id: "explorer",
    label: "Protein Explorer",
    hint: "UniProt search · encyclopedia",
    icon: "PRO",
  },
];

export type LabSidebarProps = {
  stage: LabStageId;
  onStageChange: (id: LabStageId) => void;
  footer?: ReactNode;
};

export function LabSidebar({ stage, onStageChange, footer }: LabSidebarProps) {
  return (
    <nav
      className="flex h-full w-[220px] shrink-0 flex-col border-r border-[rgba(148,163,184,0.14)] bg-[#0A0E16]"
      aria-label="Virtual Cellular Laboratory stages"
    >
      <div className="border-b border-[rgba(148,163,184,0.12)] px-4 py-4">
        <p className="font-mono text-[10px] tracking-[0.18em] text-[#64748B] uppercase">
          CISTRON V1
        </p>
        <h1 className="mt-1 text-[15px] font-semibold tracking-tight text-[#F8FAFC]">
          Virtual Cell Lab
        </h1>
        <p className="mt-1 text-[11px] leading-snug text-[#94A3B8]">
          Life-sciences enterprise workspace — experiments, not floats.
        </p>
      </div>

      <ul className="flex-1 space-y-1 overflow-y-auto p-2">
        {LAB_STAGES.map((s) => {
          const active = stage === s.id;
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onStageChange(s.id)}
                className={clsx(
                  "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2.5 text-left transition-colors",
                  active
                    ? "bg-[rgba(0,240,255,0.12)] text-[#E0F7FA] ring-1 ring-[rgba(0,240,255,0.4)]"
                    : "text-[#CBD5E1] hover:bg-[rgba(148,163,184,0.08)]",
                )}
                aria-current={active ? "page" : undefined}
              >
                <span
                  className={clsx(
                    "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-mono text-[9px] font-bold",
                    active
                      ? "bg-[#00F0FF] text-[#0B0F17]"
                      : "bg-[#182338] text-[#94A3B8]",
                  )}
                >
                  {s.icon}
                </span>
                <span className="min-w-0">
                  <span className="block text-[12.5px] font-medium leading-tight">{s.label}</span>
                  <span className="mt-0.5 block text-[10.5px] leading-snug text-[#64748B]">
                    {s.hint}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {footer ? (
        <div className="border-t border-[rgba(148,163,184,0.12)] p-3">{footer}</div>
      ) : (
        <div className="border-t border-[rgba(148,163,184,0.12)] p-3">
          <p className={tw.mono}>v0.21 · Core Cellular Lab</p>
        </div>
      )}
    </nav>
  );
}
