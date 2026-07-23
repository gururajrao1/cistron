import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_DOSES,
  MOCK_PATIENT,
  useAgentPlanner,
  usePatientNetwork,
  useSimulationRun,
  useSystemBootstrap,
} from "./ui/api/client";
import { ENCYCLOPEDIA, MOCK_DOCKING } from "./ui/api/mockData";
import type { DockingPose, EncyclopediaCard, MetricSnapshot } from "./ui/api/types";
import { CanvasView } from "./ui/canvas";
import {
  AIScientistPanel,
  CausalNarrativePanel,
  CollapsibleTelemetry,
  HeaderBar,
  TrajectoryChart,
} from "./ui/components";
import { clsx, tw } from "./ui/design_system";
import { LabSidebar, type LabStageId } from "./ui/lab/LabSidebar";
import { ExperimentStudioStage, ProteinExplorerStage } from "./ui/lab/LabStages";
import { debounce } from "./ui/stability";

const DockingViewport = lazy(() =>
  import("./ui/components/DockingViewport").then((m) => ({ default: m.DockingViewport })),
);

const DEFAULT_GOAL =
  "Find a two-drug combination that halts ERK over-activation in a mutated EGFR background without exceeding the toxicity threshold";

const LIGAND_FOR_TARGET: Record<string, string> = {
  EGFR: "Erlotinib",
  KRAS: "GDP",
  BRAF: "Vemurafenib",
  MAP2K1: "Trametinib",
  MAPK1: "SCH772984",
  TP53: "PRIMA-1",
};

export default function App() {
  const { health, patient, doses, setDoses, docking: bootDocking } = useSystemBootstrap();
  const [pathwayId, setPathwayId] = useState("hsa04010");
  const [tHorizon, setTHorizon] = useState(20);
  const [dt, setDt] = useState(0.5);
  const [stage, setStage] = useState<LabStageId>("experiment");
  const [scrub, setScrub] = useState(0);
  const [rightOpen, setRightOpen] = useState(false);
  const [goal, setGoal] = useState(DEFAULT_GOAL);
  const [metrics, setMetrics] = useState<MetricSnapshot | null>(null);
  const [explorerId, setExplorerId] = useState<string | null>("EGFR");
  const [dockingPose, setDockingPose] = useState<DockingPose | null>(null);

  const { data: simData, error: simError, loading: simLoading, run: runSimulation } =
    useSimulationRun();
  const network = usePatientNetwork(patient?.patientId ?? MOCK_PATIENT.patientId, pathwayId);
  const agent = useAgentPlanner();
  const highlightHubs = pathwayId === "crosstalk_multi" || pathwayId === "hsa04151";

  const encyclopediaCards: EncyclopediaCard[] = useMemo(
    () => Object.values(ENCYCLOPEDIA),
    [],
  );

  const activeDocking = dockingPose ?? bootDocking;

  const runSim = useCallback(async () => {
    try {
      const run = await runSimulation({
        patientId: patient?.patientId ?? MOCK_PATIENT.patientId,
        pathwayId,
        doses,
        tHorizon,
        dt,
        readout: "ERK",
      });
      setMetrics(run.metrics ?? null);
      const t0 = run.series?.[0]?.t?.[0];
      if (typeof t0 === "number") setScrub(t0);
    } catch {
      /* surfaced via hook */
    }
  }, [runSimulation, patient, pathwayId, doses, tHorizon, dt]);

  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void (async () => {
      try {
        const run = await runSimulation({
          patientId: MOCK_PATIENT.patientId,
          pathwayId: "hsa04010",
          doses: DEFAULT_DOSES,
          tHorizon: 20,
          dt: 0.5,
          readout: "ERK",
        });
        setMetrics(run.metrics ?? null);
        const t0 = run.series?.[0]?.t?.[0];
        if (typeof t0 === "number") setScrub(t0);
      } catch {
        /* ignore */
      }
    })();
  }, [runSimulation]);

  const debouncedRun = useMemo(() => debounce(() => void runSim(), 280), [runSim]);
  const pathwayBoot = useRef(true);
  useEffect(() => {
    if (pathwayBoot.current) {
      pathwayBoot.current = false;
      return;
    }
    debouncedRun();
    return () => debouncedRun.cancel();
  }, [pathwayId, debouncedRun]);

  const launchAgent = async () => {
    setRightOpen(true);
    try {
      const result = await agent.launch({
        patientId: patient?.patientId ?? MOCK_PATIENT.patientId,
        goal,
        readout: "ERK",
        maxDrugs: 2,
      });
      if (result.selectedDoses?.length) setDoses(result.selectedDoses);
      if (result.metrics) setMetrics(result.metrics);
      await runSim();
    } catch {
      /* panel error */
    }
  };

  const applyPreset = (nextPathway: string, _presetId: string) => {
    setPathwayId(nextPathway);
  };

  const openDocking = (pdbId: string, geneSymbol: string) => {
    const ligand = LIGAND_FOR_TARGET[geneSymbol.toUpperCase()] ?? "Erlotinib";
    setDockingPose({
      ...MOCK_DOCKING,
      receptorId: pdbId === "pocket" ? geneSymbol : pdbId,
      ligandId: ligand,
      deltaG: -9.4,
      ki: 1.2e-9,
    });
    setStage("docking");
  };

  const stageTitle: Record<LabStageId, string> = {
    experiment: "Experiment Studio",
    pathway: "Visual Pathway Canvas",
    docking: "3D Structural Docking",
    explorer: "Protein Explorer",
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#0B0F17] text-[#F8FAFC]">
      <LabSidebar stage={stage} onStageChange={setStage} />

      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <HeaderBar
          health={health}
          patient={patient}
          metrics={metrics}
          onLaunchAgent={() => void launchAgent()}
          agentBusy={agent.loading}
          aiOpen={rightOpen}
          onToggleAi={() => setRightOpen((v) => !v)}
          onRunExperiment={() => void runSim()}
          runBusy={simLoading}
        />

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <div className="flex shrink-0 items-center gap-3 px-3 pt-3">
              <div className="min-w-0">
                <p className="font-mono text-[10px] tracking-[0.16em] text-[#64748B] uppercase">
                  Stage
                </p>
                <h2 className="truncate text-[15px] font-semibold tracking-tight">
                  {stageTitle[stage]}
                </h2>
              </div>
            </div>

            <div className="vs-stage min-h-0 flex-1 px-3 pb-2 pt-2">
              {stage === "experiment" && (
                <ExperimentStudioStage
                  doses={doses}
                  onChangeDoses={setDoses}
                  pathwayId={pathwayId}
                  onPathwayChange={setPathwayId}
                  tHorizon={tHorizon}
                  onTHorizonChange={setTHorizon}
                  dt={dt}
                  onDtChange={setDt}
                  metrics={metrics}
                  onRun={() => void runSim()}
                  running={simLoading}
                  onApplyPreset={applyPreset}
                />
              )}

              {stage === "pathway" && (
                <div className="flex min-h-full flex-col gap-4">
                  {/* Full-stage network — primary V1 surface */}
                  <div className="min-h-[480px]">
                    <CanvasView
                      network={network.data}
                      series={simData?.series ?? []}
                      causal={null}
                      loading={network.loading || simLoading}
                      highlightHubs={highlightHubs || network.data?.pathway_mode === "crosstalk"}
                    />
                  </div>
                  {/* Concise ODE readout — not competing with the map */}
                  <TrajectoryChart
                    series={simData?.series ?? []}
                    washout={simData?.washout}
                    scrubTime={scrub}
                    onScrub={setScrub}
                    height={260}
                    focusIds={["EGF", "EGFR", "RAS", "ERK"]}
                  />
                  <CausalNarrativePanel causal={simData?.causal ?? null} loading={simLoading} />
                </div>
              )}

              {stage === "docking" && (
                <Suspense
                  fallback={
                    <div className="flex min-h-[420px] items-center justify-center rounded-[8px] border border-[rgba(0,240,255,0.2)]">
                      <p className={tw.label}>Loading WebGL docking viewer…</p>
                    </div>
                  }
                >
                  <DockingViewport pose={activeDocking} />
                </Suspense>
              )}

              {stage === "explorer" && (
                <ProteinExplorerStage
                  cards={encyclopediaCards}
                  selectedId={explorerId}
                  onSelect={setExplorerId}
                  onOpenDocking={openDocking}
                />
              )}
            </div>

            <div className="shrink-0 px-3 pb-3">
              <CollapsibleTelemetry title="Advanced Omics & Raw Telemetry">
                <p className="mb-2 text-[12px] leading-relaxed text-[#94A3B8]">
                  Optional deep dive: FBA fluxes, splice PSI, neoantigen scores, and solver
                  matrices. Hidden by default so experiments stay readable.
                </p>
                <dl className="grid grid-cols-2 gap-2 text-[12px] text-[#94A3B8] sm:grid-cols-4">
                  <div>
                    <dt className={tw.label}>Pathway</dt>
                    <dd className={tw.mono}>{pathwayId}</dd>
                  </div>
                  <div>
                    <dt className={tw.label}>Duration</dt>
                    <dd className={tw.mono}>{tHorizon}s</dd>
                  </div>
                  <div>
                    <dt className={tw.label}>Step size</dt>
                    <dd className={tw.mono}>{dt}s</dd>
                  </div>
                  <div>
                    <dt className={tw.label}>Active doses</dt>
                    <dd className={tw.mono}>{doses.filter((d) => d.enabled).length}</dd>
                  </div>
                </dl>
                {metrics && (
                  <p className="mt-2 text-[12px] text-[#94A3B8]">
                    HSI {metrics.hsi.toFixed(3)} · PDS {metrics.pds.toFixed(3)} · LAS{" "}
                    {metrics.las.toFixed(3)} · {metrics.readout}={metrics.readoutValue.toFixed(3)}
                  </p>
                )}
              </CollapsibleTelemetry>
            </div>

            {(simError || network.error) && (
              <p className="shrink-0 px-3 pb-2 text-[12px] text-[#FB7185]">
                {simError || network.error}
              </p>
            )}
          </main>

          {rightOpen && (
            <aside
              className={clsx(
                "flex h-full w-[min(360px,40vw)] shrink-0 flex-col border-l border-[rgba(0,240,255,0.25)] bg-[#0A0E16]",
              )}
            >
              <AIScientistPanel
                collapsed={false}
                onToggle={() => setRightOpen(false)}
                result={agent.data}
                loading={agent.loading}
                error={agent.error}
                onLaunch={() => void launchAgent()}
                goal={goal}
                onGoalChange={setGoal}
              />
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
