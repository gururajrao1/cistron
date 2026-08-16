import { useCallback, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, GitBranch, Grid3x3, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { StudioCanvas } from '../components/StudioCanvas'
import { SpatialGridCanvas } from '../components/studio/SpatialGridCanvas'
import { PhenotypeSummaryCard } from '../components/studio/PhenotypeSummaryCard'
import { WetLabProtocolCard } from '../components/studio/WetLabProtocolCard'
import { useLab } from '../lab/LabContext'
import {
  buildPhenotypeSummary,
  buildWetLabProtocol,
} from '../engine/phenotypeSummary'

type StudioMeshMode = 'topology' | 'spatial'

export function StudioView() {
  const lab = useLab()
  const [meshMode, setMeshMode] = useState<StudioMeshMode>('topology')
  const [protocolOpen, setProtocolOpen] = useState(false)
  const mode = lab.viewMode

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

  const edgeCount = Array.isArray(lab.graph?.edges) ? lab.graph.edges.length : 0
  const nodeCount = lab.graph ? Object.keys(lab.graph.nodes ?? {}).length : 0
  const pertCount = Object.keys(lab.perturbations).length

  const meta = useMemo(() => {
    const bits = [
      `${nodeCount} nodes · ${edgeCount} edges`,
      `t = ${lab.scrubT.toFixed(0)} min`,
    ]
    if (pertCount > 0) bits.push(`${pertCount} perturbations`)
    return bits.join(' · ')
  }, [nodeCount, edgeCount, lab.scrubT, pertCount])

  const phenotype = useMemo(
    () =>
      buildPhenotypeSummary({
        active: lab.payload,
        untreated: lab.untreatedRun,
        scrubT: lab.scrubT,
        profileId: lab.profileId,
        topo: lab.topologicalAnalysis,
      }),
    [
      lab.payload,
      lab.untreatedRun,
      lab.scrubT,
      lab.profileId,
      lab.topologicalAnalysis,
    ],
  )

  const protocol = useMemo(
    () => buildWetLabProtocol(phenotype, lab.profileId),
    [phenotype, lab.profileId],
  )

  const showMeshTools = mode !== 'biologist'
  const showCanvas = mode !== 'biologist' || Boolean(lab.payload)
  const showSpatial = mode !== 'biologist' && meshMode === 'spatial'

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {showMeshTools ? (
        <div className="flex h-[34px] shrink-0 items-center gap-2 border-b border-vcl-border bg-obsidian-panel/90 px-3 backdrop-blur-sm">
          <div className="inline-flex h-7 items-center rounded-md border border-vcl-border bg-obsidian p-0.5">
            <button
              type="button"
              onClick={() => setMeshMode('topology')}
              className={clsx(
                'vcl-focus-ring inline-flex h-full items-center gap-1.5 rounded-[5px] px-2.5 font-mono text-[10.5px] font-semibold transition',
                meshMode === 'topology'
                  ? 'bg-vcl-raised text-vcl-text shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)]'
                  : 'text-vcl-muted hover:text-vcl-text',
              )}
            >
              <GitBranch className="h-3 w-3" />
              Network Graph Topology
            </button>
            <button
              type="button"
              onClick={() => setMeshMode('spatial')}
              className={clsx(
                'vcl-focus-ring inline-flex h-full items-center gap-1.5 rounded-[5px] px-2.5 font-mono text-[10.5px] font-semibold transition',
                meshMode === 'spatial'
                  ? 'bg-vcl-raised text-vcl-text shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)]'
                  : 'text-vcl-muted hover:text-vcl-text',
              )}
            >
              <Grid3x3 className="h-3 w-3" />
              Spatial Microenvironment Mesh
            </button>
          </div>

          <span className="hidden font-mono text-[10.5px] text-vcl-dim md:inline">{meta}</span>
          {pertCount > 0 ? (
            <span className="hidden font-mono text-[10px] text-amber-kinase lg:inline">
              {pertCount} KO/dose
            </span>
          ) : null}

          {mode === 'systems' ? (
            <span className="ml-auto hidden font-mono text-[10px] text-violet-300/80 xl:inline">
              Systems Math · raw graph + ODE canvas
            </span>
          ) : (
            <div className="ml-auto hidden items-center gap-3 font-mono text-[10px] text-vcl-dim xl:flex">
              <span className="inline-flex items-center gap-1">
                <span className="h-0.5 w-3 bg-emerald-active" /> activation
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-0.5 w-3 bg-coral-action" /> inhibition / KO
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="flex h-8 shrink-0 items-center gap-3 border-b border-vcl-border px-3 font-mono text-[10px] text-vcl-dim">
          <span>Biologist · protein map · zoom out for pathways</span>
          <span className="ml-auto text-vcl-dim/80">Click a node for details</span>
        </div>
      )}

      {/* Compact overview — map stays the hero */}
      <div
        className={clsx(
          'shrink-0 overflow-y-auto border-b border-vcl-border/80 bg-obsidian/25 px-3 py-2.5',
          mode === 'biologist' ? 'max-h-[min(168px,28vh)]' : 'max-h-[min(240px,34vh)] space-y-2.5',
        )}
      >
        <PhenotypeSummaryCard
          summary={phenotype}
          showGauges
          compact={mode === 'biologist'}
        />
        {mode !== 'biologist' || protocolOpen ? (
          <div
            className={clsx(
              'rounded-lg border border-amber-kinase/25 bg-[#1a1408]/60',
              mode === 'biologist' && 'mt-2',
            )}
          >
            <button
              type="button"
              onClick={() => setProtocolOpen((v) => !v)}
              className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-amber-kinase"
            >
              {protocolOpen ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              Wet-lab protocol
              <span className="ml-auto font-sans text-[10px] font-normal normal-case tracking-normal text-vcl-dim">
                {protocolOpen ? 'Hide' : 'Show'}
              </span>
            </button>
            {protocolOpen ? (
              <div className="border-t border-amber-kinase/20 px-1 pb-2">
                <WetLabProtocolCard protocol={protocol} className="!border-0 !bg-transparent" />
              </div>
            ) : null}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setProtocolOpen(true)}
            className="mt-1.5 font-mono text-[10px] text-amber-kinase/80 hover:text-amber-kinase"
          >
            + Wet-lab protocol
          </button>
        )}
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {showBootSpinner ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-vcl-muted">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-active" />
            {lab.statusStage ?? 'Bootstrapping simulation studio…'}
          </div>
        ) : !showCanvas ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-vcl-muted">
            Run a simulation to populate phenotype gauges and wet-lab timing.
          </div>
        ) : showSpatial ? (
          <SpatialGridCanvas
            graph={lab.graph}
            scrubT={lab.scrubT}
            scrubberPayload={lab.payload}
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
            stageOnly
          />
        )}
      </div>
    </div>
  )
}
