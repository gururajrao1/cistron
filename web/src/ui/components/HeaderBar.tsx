import type { MetricSnapshot, PatientBadge, SystemHealth } from "../api/types";
import { clsx, colors, tw } from "../design_system";
import { MetricGauge } from "./MetricGauge";

export type HeaderBarProps = {
  health: SystemHealth | null;
  patient: PatientBadge | null;
  metrics: MetricSnapshot | null;
  onLaunchAgent: () => void;
  agentBusy?: boolean;
  aiOpen?: boolean;
  onToggleAi?: () => void;
  onRunExperiment?: () => void;
  runBusy?: boolean;
};

export function HeaderBar({
  health,
  patient,
  metrics,
  onLaunchAgent: _onLaunchAgent,
  agentBusy,
  aiOpen,
  onToggleAi,
  onRunExperiment,
  runBusy,
}: HeaderBarProps) {
  void _onLaunchAgent;
  const status = health?.status ?? "offline";
  const statusColor =
    status === "online"
      ? colors.accent.lime
      : status === "degraded"
        ? colors.accent.amber
        : colors.accent.rose;

  return (
    <header className="shrink-0 border-b border-[rgba(0,229,255,0.2)] bg-[rgba(17,24,39,0.92)] backdrop-blur-[16px]">
      {/* Identity + actions row — no metric collision */}
      <div className="flex h-12 items-center gap-3 px-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border border-[#00E5FF] bg-[#0B0F17] font-mono text-[11px] font-semibold text-[#00E5FF]">
            VS
          </div>
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold tracking-tight text-[#F8FAFC]">
              VOIDSIGNAL
            </div>
            <div className={clsx(tw.label, "leading-none")}>Virtual Cellular Laboratory</div>
          </div>
        </div>

        <div className="mx-1 hidden h-7 w-px bg-[rgba(148,163,184,0.16)] sm:block" />

        <div className="hidden min-w-0 items-center gap-2 md:flex">
          <span
            className="inline-block h-2 w-2 shrink-0 animate-pulse rounded-full"
            style={{ backgroundColor: statusColor }}
            aria-hidden
          />
          <div className="min-w-0 leading-tight">
            <div className={tw.label}>System</div>
            <div className={clsx(tw.mono, "truncate")}>
              {status}
              {health ? ` · v${health.version}` : ""}
            </div>
          </div>
        </div>

        {patient && (
          <div
            className="hidden min-w-0 max-w-[200px] truncate rounded-[8px] border border-[rgba(0,229,255,0.35)] bg-[#151C2C] px-2.5 py-1 lg:block"
            title={patient.variants.map((v) => `${v.gene} ${v.hgvs}`).join(", ")}
          >
            <div className={tw.label}>Patient</div>
            <div className={clsx(tw.mono, "truncate")}>{patient.patientId}</div>
          </div>
        )}

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {onRunExperiment && (
            <button
              type="button"
              className={tw.btnGhost}
              onClick={onRunExperiment}
              disabled={runBusy}
            >
              {runBusy ? "Integrating…" : "Run experiment"}
            </button>
          )}
          <button
            type="button"
            className={clsx(aiOpen ? tw.btnPrimary : tw.btnGhost)}
            onClick={() => onToggleAi?.()}
            disabled={agentBusy}
            aria-pressed={!!aiOpen}
            title="Toggle AI Scientist drawer"
          >
            {agentBusy ? "AI Scientist…" : aiOpen ? "Close AI" : "AI Assistant"}
          </button>
        </div>
      </div>

      {/* Dedicated metrics strip — never overlaps action buttons */}
      {metrics && (
        <div className="flex items-center gap-4 overflow-x-auto border-t border-[rgba(148,163,184,0.1)] px-4 py-2">
          <MetricGauge metricKey="HSI" value={metrics.hsi} />
          <MetricGauge metricKey="PDS" value={metrics.pds} />
          <MetricGauge metricKey="LAS" value={metrics.las} />
          <MetricGauge
            metricKey={metrics.readout === "ERK" ? "ERK" : metrics.readout}
            value={metrics.readoutValue}
            max={2}
          />
        </div>
      )}
    </header>
  );
}
