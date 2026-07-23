import { useMemo, useState } from "react";
import type { DoseParams, EncyclopediaCard, MetricSnapshot } from "../api/types";
import { clsx, tw } from "../design_system";
import { GlassPanel } from "../components/GlassPanel";
import { DosingController } from "../components/DosingController";
import { EncyclopediaBody } from "../components/ProteinEncyclopediaDrawer";
import { ExecutiveSummaryCard } from "../components/ExecutiveSummary";

const EXPERIMENT_PRESETS = [
  {
    id: "crispr_ko",
    title: "CRISPR Knockout",
    detail: "Remove EGFR from the membrane receptor pool",
    pathwayId: "hsa04010",
  },
  {
    id: "point_mut",
    title: "Point Mutation (KRAS G12D)",
    detail: "Lock KRAS in a GTP-bound oncogenic state",
    pathwayId: "hsa04010",
  },
  {
    id: "drug_combo",
    title: "Dual Drug Combo",
    detail: "MEK + PI3K dual blockade with Bliss synergy readout",
    pathwayId: "crosstalk_multi",
  },
  {
    id: "hypoxia",
    title: "Simulate Hypoxia",
    detail: "Low-O2 metabolic rewiring on mTOR / HIF axes",
    pathwayId: "hsa04151",
  },
] as const;

export type ExperimentStudioProps = {
  doses: DoseParams[];
  onChangeDoses: (next: DoseParams[]) => void;
  pathwayId: string;
  onPathwayChange: (id: string) => void;
  tHorizon: number;
  onTHorizonChange: (v: number) => void;
  dt: number;
  onDtChange: (v: number) => void;
  metrics: MetricSnapshot | null;
  onRun: () => void;
  running: boolean;
  onApplyPreset: (pathwayId: string, presetId: string) => void;
};

export function ExperimentStudioStage({
  doses,
  onChangeDoses,
  pathwayId,
  onPathwayChange,
  tHorizon,
  onTHorizonChange,
  dt,
  onDtChange,
  metrics,
  onRun,
  running,
  onApplyPreset,
}: ExperimentStudioProps) {
  const [preset, setPreset] = useState<string>("drug_combo");

  const delta = useMemo(() => {
    if (!metrics) return null;
    // Synthetic healthy baseline vs cancer metrics for V1 delta panel
    const healthyHsi = Math.max(0.05, metrics.hsi * 0.35);
    const healthyLas = Math.min(0.95, metrics.las + 0.25);
    return {
      hsiShift: ((metrics.hsi - healthyHsi) / Math.max(healthyHsi, 1e-6)) * 100,
      lasShift: ((metrics.las - healthyLas) / Math.max(Math.abs(healthyLas), 1e-6)) * 100,
      healthyHsi,
      cancerHsi: metrics.hsi,
      healthyLas,
      cancerLas: metrics.las,
      pds: metrics.pds,
    };
  }, [metrics]);

  return (
    <div className="grid min-h-full grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex flex-col gap-3">
        <GlassPanel
          title="Hypothesis setup"
          className="min-h-fit"
          bodyClassName="min-h-fit space-y-3 overflow-visible p-3"
        >
          <p className="text-[12px] leading-relaxed text-[#94A3B8]">
            Single-click biological experiments inside the virtual cell — CRISPR, mutations, drug
            combos, hypoxia.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {EXPERIMENT_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                className={clsx(
                  "rounded-lg border px-3 py-2.5 text-left transition-colors",
                  preset === p.id
                    ? "border-[rgba(0,240,255,0.5)] bg-[rgba(0,240,255,0.08)]"
                    : "border-[rgba(148,163,184,0.14)] hover:border-[rgba(0,240,255,0.3)]",
                )}
                onClick={() => {
                  setPreset(p.id);
                  onApplyPreset(p.pathwayId, p.id);
                }}
              >
                <span className="block text-[12.5px] font-medium text-[#F8FAFC]">{p.title}</span>
                <span className="mt-1 block text-[11px] leading-snug text-[#64748B]">{p.detail}</span>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button type="button" className={tw.btnPrimary} onClick={onRun} disabled={running}>
              {running ? "Running experiment…" : "Launch experiment"}
            </button>
          </div>
        </GlassPanel>

        <div className="min-h-[88px] shrink-0">
          {metrics ? (
            <ExecutiveSummaryCard
              hsi={metrics.hsi}
              las={metrics.las}
              pds={metrics.pds}
              readout={metrics.readout}
              readoutValue={metrics.readoutValue}
            />
          ) : (
            <div className="flex h-[88px] items-center rounded-[10px] border border-[rgba(148,163,184,0.12)] px-3">
              <p className={tw.label}>No experiment metrics yet — pick a preset and launch.</p>
            </div>
          )}
        </div>

        <GlassPanel
          title="Healthy vs Cancer delta"
          className="min-h-fit"
          bodyClassName="min-h-fit space-y-3 p-3"
        >
          {!delta ? (
            <p className={tw.label}>Run an experiment to unlock comparative dysregulation shifts.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-[rgba(0,230,118,0.35)] bg-[rgba(0,230,118,0.06)] p-3">
                <p className={tw.label}>Healthy baseline</p>
                <p className="mt-1 font-mono text-[18px] text-[#00E676]">
                  HSI {delta.healthyHsi.toFixed(2)}
                </p>
                <p className={tw.mono}>LAS {delta.healthyLas.toFixed(2)}</p>
              </div>
              <div className="rounded-lg border border-[rgba(255,184,0,0.4)] bg-[rgba(255,184,0,0.08)] p-3">
                <p className={tw.label}>Cancer / treated</p>
                <p className="mt-1 font-mono text-[18px] text-[#FFB800]">
                  HSI {delta.cancerHsi.toFixed(2)}
                </p>
                <p className={tw.mono}>LAS {delta.cancerLas.toFixed(2)}</p>
              </div>
              <div className="sm:col-span-2 rounded-lg border border-[rgba(148,163,184,0.14)] bg-[#182338] p-3">
                <p className={tw.label}>Dysregulation shift</p>
                <p className="mt-1 text-[13px] leading-relaxed text-[#E2E8F0]">
                  Health/Sickness Index shifted{" "}
                  <span className="font-mono text-[#FFB800]">
                    {delta.hsiShift >= 0 ? "+" : ""}
                    {delta.hsiShift.toFixed(0)}%
                  </span>{" "}
                  vs healthy · Pathway Disruption Index{" "}
                  <span className="font-mono text-[#00F0FF]">{delta.pds.toFixed(2)}</span>
                </p>
              </div>
            </div>
          )}
        </GlassPanel>
      </div>

      <div className="min-h-fit">
        <DosingController
          doses={doses}
          onChange={onChangeDoses}
          pathwayId={pathwayId}
          onPathwayChange={onPathwayChange}
          tHorizon={tHorizon}
          onTHorizonChange={onTHorizonChange}
          dt={dt}
          onDtChange={onDtChange}
        />
      </div>
    </div>
  );
}

function cardKey(c: EncyclopediaCard): string {
  return c.entity_id ?? c.state?.entity_id ?? c.identity?.gene_symbol ?? c.title;
}

/** Curated V1 encyclopedia — MAPK core only (not an endless UniProt dump). */
export const CORE_PROTEIN_IDS = ["EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1", "TP53"] as const;

export type ProteinExplorerProps = {
  cards: EncyclopediaCard[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpenDocking?: (pdbId: string, geneSymbol: string) => void;
};

export function ProteinExplorerStage({
  cards,
  selectedId,
  onSelect,
  onOpenDocking,
}: ProteinExplorerProps) {
  const [q, setQ] = useState("");
  const coreCards = useMemo(() => {
    const allow = new Set(CORE_PROTEIN_IDS.map((s) => s.toUpperCase()));
    return cards.filter((c) => allow.has((c.identity?.gene_symbol ?? c.title).toUpperCase()));
  }, [cards]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return coreCards;
    return coreCards.filter((c) => {
      const hay = `${c.title} ${c.subtitle ?? ""} ${c.identity?.gene_symbol ?? ""} ${c.identity?.uniprot_id ?? ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [coreCards, q]);
  const selected =
    filtered.find((c) => cardKey(c) === selectedId) ?? filtered[0] ?? null;

  return (
    <div className="grid min-h-full grid-cols-1 gap-3 md:grid-cols-[260px_minmax(0,1fr)]">
      <GlassPanel
        title="Core targets"
        className="min-h-fit"
        bodyClassName="min-h-fit space-y-2 overflow-y-auto p-3"
      >
        <input
          className={tw.input}
          placeholder="Filter EGFR, KRAS, MEK…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <p className={tw.label}>V1 catalog · 6 MAPK / p53 hubs (not the full proteome)</p>
        <ul className="space-y-1">
          {filtered.map((c) => {
            const key = cardKey(c);
            return (
              <li key={key}>
                <button
                  type="button"
                  className={clsx(
                    "w-full rounded-md px-2 py-2 text-left text-[12px]",
                    (selected ? cardKey(selected) : selectedId) === key
                      ? "bg-[rgba(0,240,255,0.12)] text-[#E0F7FA]"
                      : "text-[#CBD5E1] hover:bg-[rgba(148,163,184,0.08)]",
                  )}
                  onClick={() => onSelect(key)}
                >
                  <span className="font-medium">{c.title}</span>
                  <span className="mt-0.5 block truncate text-[10.5px] text-[#64748B]">
                    {c.subtitle}
                  </span>
                </button>
              </li>
            );
          })}
          {filtered.length === 0 && (
            <li className="px-2 py-4 text-[12px] text-[#64748B]">No match in the core catalog.</li>
          )}
        </ul>
      </GlassPanel>

      <GlassPanel
        title={selected ? `Encyclopedia · ${selected.title}` : "Encyclopedia card"}
        className="min-h-fit"
        bodyClassName="min-h-fit space-y-3 overflow-y-auto p-3"
      >
        {!selected ? (
          <p className={tw.label}>Pick a core target to inspect.</p>
        ) : (
          <EncyclopediaBody card={selected} onOpenDocking={onOpenDocking} />
        )}
      </GlassPanel>
    </div>
  );
}

