import { tw } from "../design_system";
import type { NodePerturbationMode } from "./types";

export type NodePerturbationPanelProps = {
  nodeId: string | null;
  nodeLabel?: string;
  mode: NodePerturbationMode;
  onChange: (mode: NodePerturbationMode) => void;
  onClose: () => void;
  onOpenEncyclopedia?: () => void;
};

/**
 * Inline click-to-dose / knockout controller for a selected pathway node.
 */
export function NodePerturbationPanel({
  nodeId,
  nodeLabel,
  mode,
  onChange,
  onClose,
  onOpenEncyclopedia,
}: NodePerturbationPanelProps) {
  if (!nodeId) return null;
  return (
    <div className="rounded-[10px] border border-[#00E5FF] bg-[rgba(17,24,39,0.92)] p-3 shadow-[0_0_18px_rgba(0,229,255,0.12)]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <div className={tw.title}>Click-to-dose · {nodeLabel ?? nodeId}</div>
          <p className={tw.label}>Watch downstream fade (KO) or edge severance (drug)</p>
        </div>
        <div className="flex gap-2">
          {onOpenEncyclopedia && (
            <button type="button" className={tw.btnPrimary} onClick={onOpenEncyclopedia}>
              Encyclopedia
            </button>
          )}
          <button type="button" className={tw.btnGhost} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <ModeButton
          active={mode === "none"}
          label="Restore"
          onClick={() => onChange("none")}
        />
        <ModeButton
          active={mode === "knockout"}
          label="CRISPR knockout"
          hint="Downstream fades blue"
          onClick={() => onChange("knockout")}
        />
        <ModeButton
          active={mode === "drug"}
          label="Small-molecule drug"
          hint="Outgoing edges sever"
          onClick={() => onChange("drug")}
        />
      </div>
    </div>
  );
}

function ModeButton({
  active,
  label,
  hint,
  onClick,
}: {
  active: boolean;
  label: string;
  hint?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? tw.btnPrimary
          : tw.btnGhost + " flex-col items-start gap-0.5 py-2"
      }
    >
      <span>{label}</span>
      {hint && <span className="text-[10px] opacity-80">{hint}</span>}
    </button>
  );
}
