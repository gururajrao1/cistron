import { useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { StudioCanvas } from '../components/StudioCanvas'
import { ScientistPanel } from '../components/ScientistPanel'
import { useLab } from '../lab/LabContext'

export function StudioView() {
  const lab = useLab()

  const toggleKnockout = useCallback(
    (nodeId: string) => {
      if (lab.busy) return
      const on = lab.controls.knockouts.includes(nodeId)
      const knockouts = on
        ? lab.controls.knockouts.filter((k) => k !== nodeId)
        : [...lab.controls.knockouts, nodeId]
      lab.patchControls({ knockouts })
      lab.runSimulation({ knockouts })
    },
    [lab],
  )

  const showBootSpinner = lab.busy && !lab.graph && !lab.payload

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-4 lg:flex-row">
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        {showBootSpinner ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-active" />
            {lab.statusStage ?? 'Bootstrapping simulation studio…'}
          </div>
        ) : (
          <StudioCanvas
            preset={lab.profileId}
            graph={lab.graph}
            payload={lab.payload}
            scrubT={lab.scrubT}
            onScrub={lab.setScrubT}
            pathNodes={lab.pathNodes}
            topRegulator={lab.topRegulator}
            selectedNode={lab.selectedNode}
            onNodeSelect={lab.setSelectedNode}
            knockouts={lab.controls.knockouts}
            onToggleKnockout={toggleKnockout}
            loading={lab.busy}
          />
        )}
      </div>
      <aside className="max-h-full w-full shrink-0 space-y-3 overflow-y-auto lg:w-[320px]">
        <ScientistPanel scientist={lab.scientist} loading={lab.busy && !lab.scientist} />
        {lab.statusStage && lab.busy ? (
          <p className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-3 py-2 text-[0.7rem] leading-relaxed text-slate-500">
            {lab.statusStage}
          </p>
        ) : null}
        <p className="px-1 text-[0.68rem] leading-relaxed text-slate-600">
          Click a node for the Biophysics Inspector. Shift-click or right-click to toggle knockout
          (wᵢ=0) and re-simulate. Hover to trace upstream / downstream. Scrub the timeline for{' '}
          <span className="font-mono text-slate-500">yᵢ(t)</span> without re-solving ODEs.
        </p>
      </aside>
    </div>
  )
}
