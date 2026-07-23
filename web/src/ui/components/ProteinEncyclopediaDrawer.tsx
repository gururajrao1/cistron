import type { ReactNode } from "react";
import type { EncyclopediaCard } from "../api/types";
import { clsx, tw } from "../design_system";
import { GlassPanel } from "./GlassPanel";

export type ProteinEncyclopediaDrawerProps = {
  card: EncyclopediaCard | null;
  open: boolean;
  onClose: () => void;
  /** When true, show empty-state placeholder instead of unmounting. */
  showEmptyPlaceholder?: boolean;
};

function Badge({
  children,
  tone = "cyan",
}: {
  children: ReactNode;
  tone?: "cyan" | "amber" | "lime" | "rose" | "violet";
}) {
  const tones = {
    cyan: "border-[rgba(0,229,255,0.45)] bg-[rgba(0,229,255,0.12)] text-[#00E5FF]",
    amber: "border-[rgba(251,191,36,0.45)] bg-[rgba(251,191,36,0.12)] text-[#FBBF24]",
    lime: "border-[rgba(163,230,53,0.45)] bg-[rgba(163,230,53,0.12)] text-[#A3E635]",
    rose: "border-[rgba(251,113,133,0.45)] bg-[rgba(251,113,133,0.12)] text-[#FB7185]",
    violet: "border-[rgba(192,132,252,0.45)] bg-[rgba(192,132,252,0.12)] text-[#C084FC]",
  };
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px]",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

/**
 * Pinned encyclopedia drawer — fixed width + CSS transform (no layout thrash).
 */
export function ProteinEncyclopediaDrawer({
  card,
  open,
  onClose,
  showEmptyPlaceholder = true,
}: ProteinEncyclopediaDrawerProps) {
  const visible = open;
  const empty = !card;

  return (
    <>
      <div
        className={clsx(
          "fixed inset-0 z-40 bg-black/40 transition-opacity duration-200",
          visible ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        )}
        aria-hidden={!visible}
        onClick={onClose}
      />
      <aside
        className={clsx(
          "fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-[rgba(0,229,255,0.25)] bg-[#0B0F17] shadow-2xl",
          "transition-transform duration-200 ease-out will-change-transform",
          visible ? "translate-x-0" : "translate-x-full",
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Protein encyclopedia"
        aria-hidden={!visible}
      >
        <GlassPanel
          title="Protein encyclopedia"
          variant="active"
          className="flex h-full min-h-0 flex-1 flex-col rounded-none border-0"
          bodyClassName="min-h-0 flex-1 space-y-5 overflow-y-auto p-3"
          actions={
            <button type="button" className={tw.btnGhost} onClick={onClose}>
              Close
            </button>
          }
        >
          {empty && showEmptyPlaceholder && (
            <div className="flex min-h-[200px] flex-col items-center justify-center gap-2 text-center">
              <p className="text-[14px] text-[#F8FAFC]">Select a biological entity to inspect</p>
              <p className={tw.label}>
                Click a pathway node, or use Encyclopedia on the dose panel.
              </p>
            </div>
          )}

          {card && <EncyclopediaBody card={card} />}
        </GlassPanel>
      </aside>
    </>
  );
}

/** Shared UniProt-style card body — used by drawer and Protein Explorer stage. */
export function EncyclopediaBody({
  card,
  onOpenDocking,
}: {
  card: EncyclopediaCard;
  /** Open in-app 3D Docking Studio instead of leaving the platform. */
  onOpenDocking?: (pdbId: string, geneSymbol: string) => void;
}) {
  const loc = card.biology?.cellular_localization;
  const uniprot = card.identity?.uniprot_id;
  const plddt = card.structure?.alphafold_plddt_score;
  const pdb = card.structure?.pdb_id;
  const domains = card.biology?.domains ?? [];
  const ptms = card.biology?.ptm_sites ?? [];
  const diseases = card.clinical?.diseases ?? [];
  const drugs = card.drugs ?? [];
  const mutations = card.clinical?.somatic_mutations ?? [];
  const isStub =
    !uniprot &&
    domains.length === 0 &&
    ptms.length === 0 &&
    (card.subtitle === "Select a biological entity to inspect" ||
      (!card.identity?.full_name && diseases.length === 0 && drugs.length === 0));

  return (
    <>
      <header className="space-y-2 border-b border-[rgba(148,163,184,0.12)] pb-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-mono text-[22px] font-semibold tracking-tight text-[#F8FAFC]">
            {card.identity?.gene_symbol ?? card.title}
          </h2>
          {uniprot && <Badge tone="cyan">UniProt {uniprot}</Badge>}
          {loc && <Badge tone="lime">{loc}</Badge>}
          {card.clinical?.oncogene && <Badge tone="rose">oncogene</Badge>}
          {card.clinical?.tumor_suppressor && <Badge tone="violet">tumor suppressor</Badge>}
        </div>
        <p className="text-[13px] leading-relaxed text-[#94A3B8]">
          {card.identity?.full_name ?? card.subtitle}
        </p>
        {(card.identity?.aliases?.length ?? 0) > 0 && (
          <p className={tw.mono}>aliases: {(card.identity?.aliases ?? []).join(", ")}</p>
        )}
        {isStub && (
          <p className={tw.label}>
            No deep UniProt annotations for this node yet — kinetics remain solver-compatible.
          </p>
        )}
      </header>

      <section className="space-y-3">
        <h3 className={tw.label}>Biological context</h3>
        <div className="min-h-fit space-y-2 rounded-[8px] border border-[rgba(148,163,184,0.12)] bg-[#111827] p-3">
          <p className={tw.label}>Active domains</p>
          {domains.length === 0 ? (
            <p className="text-[12px] text-[#64748B]">No domain annotations.</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {domains.map((d) => (
                <li key={`${d.name}-${d.start}`}>
                  <button
                    type="button"
                    className="rounded-md border border-[rgba(0,229,255,0.35)] bg-[rgba(0,229,255,0.1)] px-2 py-1 font-mono text-[11px] text-[#E0F7FA] hover:border-[rgba(0,229,255,0.65)]"
                    title={d.domain_type}
                  >
                    {d.name}
                    {d.start != null && d.end != null ? ` ${d.start}–${d.end}` : ""}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-h-[56px] space-y-2 rounded-[8px] border border-[rgba(148,163,184,0.12)] bg-[#111827] p-3">
          <p className={tw.label}>PTM sites</p>
          {ptms.length === 0 ? (
            <p className="text-[12px] text-[#64748B]">No PTM occupancy recorded.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {ptms.map((p) => (
                <li key={p.name}>
                  <Badge tone={p.active ? "amber" : "cyan"}>
                    {p.residue ?? p.name}
                    {p.occupancy > 0 ? ` · ${(p.occupancy * 100).toFixed(0)}%` : ""}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-h-fit space-y-2 rounded-[8px] border border-[rgba(148,163,184,0.12)] bg-[#111827] p-3">
          <p className={tw.label}>Associated diseases / mutations</p>
          <div className="flex flex-col gap-2">
            {mutations.map((m) => (
              <div
                key={m}
                className="rounded-md border border-[rgba(251,113,133,0.4)] bg-[rgba(251,113,133,0.1)] px-2.5 py-2 text-[12px] text-[#FECACA]"
                role="alert"
              >
                <span className="mr-1.5" aria-hidden>
                  ●
                </span>
                {m}
              </div>
            ))}
            <div className="flex flex-wrap gap-1.5">
              {diseases.map((d) => (
                <Badge key={d} tone="rose">
                  {d}
                </Badge>
              ))}
            </div>
            {diseases.length === 0 && mutations.length === 0 && (
              <p className="text-[12px] text-[#64748B]">No clinical annotations.</p>
            )}
          </div>
          {(card.biology?.pathway_membership?.length ?? 0) > 0 && (
            <p className={clsx(tw.mono, "pt-1")}>
              pathways: {(card.biology?.pathway_membership ?? []).join(" · ")}
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className={tw.label}>3D structure & drugs</h3>
        <div className="flex min-h-[28px] flex-wrap gap-2">
          {plddt != null && (
            <Badge tone={plddt >= 90 ? "lime" : plddt >= 70 ? "amber" : "rose"}>
              AlphaFold pLDDT {plddt.toFixed(1)}
            </Badge>
          )}
          {pdb && (
            <button
              type="button"
              className={clsx(tw.btnPrimary, "inline-flex items-center gap-2 text-[12px]")}
              onClick={() =>
                onOpenDocking?.(pdb, card.identity?.gene_symbol ?? card.title)
              }
            >
              Open in Docking Studio ({pdb})
            </button>
          )}
          {!pdb && uniprot && (
            <button
              type="button"
              className={clsx(tw.btnGhost, "inline-flex items-center gap-2 text-[12px]")}
              onClick={() =>
                onOpenDocking?.("pocket", card.identity?.gene_symbol ?? card.title)
              }
            >
              Open pocket in Docking Studio
            </button>
          )}
          {!plddt && !pdb && !uniprot && (
            <p className="text-[12px] text-[#64748B]">No structure metadata.</p>
          )}
        </div>

        <div className="min-h-[72px] space-y-2 rounded-[8px] border border-[rgba(148,163,184,0.12)] bg-[#111827] p-3">
          <p className={tw.label}>Targetable inhibitors</p>
          {drugs.length === 0 ? (
            <p className="text-[12px] text-[#64748B]">No annotated small-molecule inhibitors.</p>
          ) : (
            <ul className="space-y-2">
              {drugs.map((d) => (
                <li
                  key={d.name}
                  className="flex items-baseline justify-between gap-2 border-b border-[rgba(148,163,184,0.08)] pb-2 last:border-0 last:pb-0"
                >
                  <div>
                    <p className="text-[13px] text-[#F8FAFC]">{d.name}</p>
                    <p className={tw.mono}>
                      {d.mechanism} · {d.approval_status}
                    </p>
                  </div>
                  <span className={tw.mono}>
                    {d.ic50_nM != null ? `IC50 ${d.ic50_nM} nM` : "IC50 —"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </>
  );
}
