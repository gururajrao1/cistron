import { useCallback, useMemo, useState } from 'react'
import { GitBranch, Grid3x3, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { StudioCanvas } from '../components/StudioCanvas'
import { SpatialGridCanvas } from '../components/studio/SpatialGridCanvas'
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

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex h-[34px] shrink-0 items-center gap-2 border-b border-vcl-border bg-obsidian-panel px-2.5">
        <div className="inline-flex h-7 items-center rounded-md border border-vcl-border bg-obsidian p-0.5">
          <button
            type="button"
            onClick={() => setMeshMode('topology')}
            className={clsx(
              'inline-flex h-full items-center gap-1.5 rounded-[5px] px-2.5 font-mono text-[10.5px] font-semibold transition',
              meshMode === 'topology'
                ? 'bg-[#1A2635] text-vcl-text'
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
              'inline-flex h-full items-center gap-1.5 rounded-[5px] px-2.5 font-mono text-[10.5px] font-semibold transition',
              meshMode === 'spatial'
                ? 'bg-[#1A2635] text-vcl-text'
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

        <div className="ml-auto hidden items-center gap-3 font-mono text-[10px] text-vcl-dim xl:flex">
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3 bg-emerald-active" /> activation
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3 bg-coral-action" /> inhibition / KO
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3 bg-cyan-flux" /> phosphorylation
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3 bg-violet-hub" /> translocation
          </span>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {showBootSpinner ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-vcl-muted">
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
            stageOnly
          />
        )}
      </div>
    </div>
  )
}
