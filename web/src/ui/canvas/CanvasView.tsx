import { useEffect, useMemo, useRef, useState } from "react";
import type {
  CausalNarrativePayload,
  EncyclopediaCard,
  PatientNetwork,
  TrajectorySeries,
} from "../api/types";
import { lookupEncyclopedia } from "../api/mockData";
import { CausalNarrativePanel } from "../components/CausalNarrativePanel";
import { GlassPanel } from "../components/GlassPanel";
import { CollapsibleTelemetry } from "../components/CollapsibleTelemetry";
import { ProteinEncyclopediaDrawer } from "../components/ProteinEncyclopediaDrawer";
import { tw } from "../design_system";
import { emptyEncyclopediaCard } from "../stability";
import { CellMicroenvironment } from "./CellMicroenvironment";
import { NetworkGraph } from "./NetworkGraph";
import { NodePerturbationPanel } from "./NodePerturbationPanel";
import { SimulationControlBar } from "./SimulationControlBar";
import { VisualLegend } from "./VisualLegend";
import type { NodePerturbationMode } from "./types";
import { buildTmeVisual, buildVisualTimeline, frameAtTime } from "./visualEngine";

export type CanvasViewProps = {
  network: PatientNetwork | null;
  series: TrajectorySeries[];
  causal?: CausalNarrativePayload | null;
  loading?: boolean;
  highlightHubs?: boolean;
};

/**
 * Stabilized visual workspace — fixed canvas height, pinned drawers,
 * graceful empty-entity fallbacks, no scrub reset thrash.
 */
export function CanvasView({
  network,
  series,
  causal = null,
  loading,
  highlightHubs = true,
}: CanvasViewProps) {
  const [perturbations, setPerturbations] = useState<Record<string, NodePerturbationMode>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [encyclopedia, setEncyclopedia] = useState<EncyclopediaCard | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [t, setT] = useState(0);
  const [inspect, setInspect] = useState<{
    kind: string;
    id: string;
    inspect: Record<string, unknown>;
  } | null>(null);
  const [layer, setLayer] = useState<"pathway" | "tme">("pathway");
  const boundKeyRef = useRef<string>("");

  const timeline = useMemo(() => {
    if (!network || !series.length) return null;
    return buildVisualTimeline(network, series, perturbations);
  }, [network, series, perturbations]);

  // Only reset scrub when the time axis actually changes (pathway/series swap)
  useEffect(() => {
    if (!timeline) return;
    const key = `${timeline.t_start}:${timeline.t_end}:${timeline.frames.length}`;
    if (boundKeyRef.current !== key) {
      boundKeyRef.current = key;
      setT(timeline.t_start);
    }
  }, [timeline]);

  useEffect(() => {
    if (!playing || !timeline) return;
    const id = window.setInterval(() => {
      setT((cur) => {
        const next = cur + Math.max(0.05, (timeline.t_end - timeline.t_start) / 80);
        return next >= timeline.t_end ? timeline.t_start : next;
      });
    }, 80);
    return () => window.clearInterval(id);
  }, [playing, timeline]);

  // Clear selection when pathway topology identity changes
  useEffect(() => {
    setSelectedId(null);
    setDrawerOpen(false);
    setEncyclopedia(null);
    setPerturbations({});
    setInspect(null);
  }, [network?.pathwayId, network?.patientId]);

  const frame = useMemo(
    () => (timeline ? frameAtTime(timeline, t) : null),
    [timeline, t],
  );
  const tme = useMemo(() => buildTmeVisual(t), [t]);
  const selectedNode = frame?.nodes.find((n) => n.node_id === selectedId);

  const openEncyclopedia = (nodeId: string) => {
    setSelectedId(nodeId);
    const netNode = network?.nodes.find((n) => n.id === nodeId || n.label === nodeId);
    const label = netNode?.label ?? nodeId;
    const card =
      netNode?.encyclopedia ?? lookupEncyclopedia(nodeId) ?? lookupEncyclopedia(label);
    setEncyclopedia(card ?? emptyEncyclopediaCard(nodeId, label));
    setDrawerOpen(true);
    setInspect(null);
  };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      {causal != null && (
        <CausalNarrativePanel causal={causal} loading={!!loading && !causal} />
      )}

      <GlassPanel
        title="Visual signaling canvas"
        variant="active"
        className="min-h-0 shrink-0"
        bodyClassName="space-y-3 p-3"
      >
        <VisualLegend showCrosstalkHubs={highlightHubs} />

        <div className="min-h-[18px]">
          {network?.pathway_mode === "crosstalk" && (network.crosstalk_hubs?.length ?? 0) > 0 ? (
            <p className={tw.mono}>
              Crosstalk hubs:{" "}
              {(network.crosstalk_hubs ?? [])
                .map((h) => `${h.name} (${(h.pathways ?? []).join("+")})`)
                .join(" · ")}
            </p>
          ) : (
            <p className={tw.label}>Single-pathway viewport</p>
          )}
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            className={layer === "pathway" ? tw.btnPrimary : tw.btnGhost}
            onClick={() => setLayer("pathway")}
          >
            Pathway cascade
          </button>
          <button
            type="button"
            className={layer === "tme" ? tw.btnPrimary : tw.btnGhost}
            onClick={() => setLayer("tme")}
          >
            Cell microenvironment
          </button>
        </div>

        <div className="relative min-h-[420px]">
          {loading && (
            <p className={tw.label + " absolute inset-0 z-10 flex items-center justify-center bg-[#070A10]/70"}>
              Loading network…
            </p>
          )}
          {!loading && !network && (
            <p className={tw.label + " flex h-[420px] items-center justify-center rounded-[8px] border border-[rgba(148,163,184,0.12)]"}>
              No pathway loaded.
            </p>
          )}

          {layer === "pathway" && frame && (
            <NetworkGraph
              frame={frame}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onEncyclopedia={openEncyclopedia}
              highlightHubs={highlightHubs}
              onInspect={(payload) => {
                if (payload.kind === "node") {
                  openEncyclopedia(payload.id);
                  return;
                }
                setInspect(payload);
              }}
            />
          )}
          {layer === "pathway" && !frame && network && !loading && (
            <p className={tw.label + " flex h-[420px] items-center justify-center"}>
              Waiting for ODE series to animate the cascade…
            </p>
          )}
          {layer === "tme" && (
            <div className="h-[420px] overflow-hidden rounded-[8px] border border-[rgba(0,229,255,0.2)]">
              <CellMicroenvironment
                scene={tme}
                onInspectCell={(id, payload) =>
                  setInspect({ kind: "cell", id, inspect: payload })
                }
              />
            </div>
          )}
        </div>

        <div className="min-h-[52px]">
          {timeline ? (
            <SimulationControlBar
              t={t}
              tStart={timeline.t_start}
              tEnd={timeline.t_end}
              playing={playing}
              onTogglePlay={() => setPlaying((p) => !p)}
              onSeek={(nt) => {
                setPlaying(false);
                setT(nt);
              }}
              onReset={() => {
                setT(timeline.t_start);
                setPlaying(true);
              }}
            />
          ) : (
            <p className={tw.label}>Scrubber idle — run ODE to unlock playback.</p>
          )}
        </div>

        <div className="min-h-[88px]">
          {selectedId ? (
            <NodePerturbationPanel
              nodeId={selectedId}
              nodeLabel={selectedNode?.label}
              mode={perturbations[selectedId] ?? "none"}
              onChange={(mode) => {
                setPerturbations((prev) => ({ ...prev, [selectedId]: mode }));
              }}
              onClose={() => setSelectedId(null)}
              onOpenEncyclopedia={() => openEncyclopedia(selectedId)}
            />
          ) : (
            <p className={tw.label + " rounded-[10px] border border-[rgba(148,163,184,0.12)] px-3 py-4"}>
              Select a biological entity to inspect — click a node on the canvas.
            </p>
          )}
        </div>
      </GlassPanel>

      <ProteinEncyclopediaDrawer
        card={encyclopedia}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />

      <div className="min-h-0">
        {inspect && (
          <CollapsibleTelemetry title="Inspect Edge Telemetry" defaultOpen>
            <div className="space-y-1">
              <p className={tw.mono}>
                {inspect.kind}: {inspect.id}
              </p>
              <pre className="max-h-40 overflow-auto font-mono text-[11px] text-[#94A3B8]">
                {JSON.stringify(inspect.inspect, null, 2)}
              </pre>
              <button type="button" className={tw.btnGhost} onClick={() => setInspect(null)}>
                Dismiss inspect
              </button>
            </div>
          </CollapsibleTelemetry>
        )}
      </div>
    </div>
  );
}
