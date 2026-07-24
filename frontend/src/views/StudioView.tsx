import { useCallback, useState } from 'react'
import { GitBranch, Grid3x3, Loader2 } from 'lucide-react'
import { StudioCanvas } from '../components/StudioCanvas'
import { ScientistPanel } from '../components/ScientistPanel'
import { PerturbationPanel } from '../components/studio/PerturbationPanel'
import { EfficacyCard } from '../components/studio/EfficacyCard'
import { SpatialGridCanvas } from '../components/studio/SpatialGridCanvas'
import { MultiOmicsRail } from '../components/studio/MultiOmicsDrawer'
import { useLab } from '../lab/LabContext'

type StudioMeshMode = 'topology' | 'spatial'

export function StudioView() {
  const lab = useLab()
  const [meshMode, setMeshMode] = useState<StudioMeshMode>('topology')

  const toggleKnockout = useCallback(
    (nodeId: string) => {
      if (lab.busy) return
      const sym = nodeId.trim().toUpperCase()
      const current = lab.perturbations[sym]
      if (current != null && current <= 1e-6) {
        lab.clearPerturbation(sym)
        return
      }
      lab.setNodePerturbation(sym, 0)
    },
    [lab],
  )

  const showBootSpinner = lab.busy && !lab.graph && !lab.payload

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-4 lg:flex-row">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden">
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="text-[0.65rem] font-semibold uppercase tracking-[0.1em] text-slate-500">
            View
          </span>
          <div className="inline-flex rounded-xl border border-slate-700/80 bg-obsidian-panel/80 p-0.5">
            <button
              type="button"
              onClick={() => setMeshMode('topology')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold transition ${
                meshMode === 'topology'
                  ? 'bg-emerald-500/20 text-emerald-100 shadow-[0_0_12px_rgba(16,185,129,0.2)]'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <GitBranch className="h-3.5 w-3.5" />
              Graph Topology
            </button>
            <button
              type="button"
              onClick={() => setMeshMode('spatial')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold transition ${
                meshMode === 'spatial'
                  ? 'bg-cyan-500/20 text-cyan-100 shadow-[0_0_12px_rgba(6,182,212,0.2)]'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Grid3x3 className="h-3.5 w-3.5" />
              Spatial Microenvironment Mesh
            </button>
          </div>
        </div>

        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          {showBootSpinner ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin text-emerald-active" />
              {lab.statusStage ?? 'Bootstrapping simulation studio…'}
            </div>
          ) : meshMode === 'spatial' ? (
            <SpatialGridCanvas
              graph={lab.graph}
              scrubT={lab.scrubT}
              perturbations={lab.perturbations ?? {}}
              selectedNode={lab.selectedNode}
            />
          ) : (
            <StudioCanvas
              preset={lab.profileId || 'hypoxia'}
              graph={lab.graph}
              payload={lab.payload}
              scrubT={lab.scrubT}
              onScrub={lab.setScrubT}
              pathNodes={lab.pathNodes ?? []}
              topRegulator={lab.topRegulator}
              selectedNode={lab.selectedNode}
              onNodeSelect={lab.setSelectedNode}
              knockouts={lab.controls.knockouts ?? []}
              perturbations={lab.perturbations ?? {}}
              onToggleKnockout={toggleKnockout}
              loading={lab.busy}
            />
          )}
        </div>
      </div>
      <aside className="max-h-full w-full shrink-0 space-y-3 overflow-y-auto lg:w-[320px]">
        <PerturbationPanel />
        <EfficacyCard />
        <MultiOmicsRail />
        <ScientistPanel
          scientist={lab.scientist}
          loading={lab.busy && !lab.scientist}
          hypotheses={lab.causalHypotheses}
          hypothesesLoading={lab.busy && lab.causalHypotheses.length === 0}
        />
        {lab.statusStage && lab.busy ? (
          <p className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-3 py-2 text-[0.7rem] leading-relaxed text-slate-500">
            {lab.statusStage}
          </p>
        ) : null}
        <p className="px-1 text-[0.68rem] leading-relaxed text-slate-600">
          {meshMode === 'spatial'
            ? 'Spatial mesh: click to place ligand sources or drug sinks. Lower O₂ drives HIF1A cytoplasm→nucleus translocation in the coupled compartmental ODE.'
            : 'Use Target perturbations + Dual Screen for combinatorial KO. Shift-click canvas nodes to toggle KO. Scrub for yᵢ(t) without re-solving ODEs.'}
        </p>
      </aside>
    </div>
  )
}
