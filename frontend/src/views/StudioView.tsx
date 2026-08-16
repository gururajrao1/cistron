import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GitBranch, Grid3x3, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { StudioCanvas } from '../components/StudioCanvas'
import { SpatialGridCanvas } from '../components/studio/SpatialGridCanvas'
import { useLab } from '../lab/LabContext'
import { useStudioChrome } from '../layout/StudioChromeContext'

type StudioMeshMode = 'topology' | 'spatial'

/**
 * Simulation Studio — pathway map only.
 * Phenotype / protocol live on /phenotype; heavy tools on sidebar routes.
 */
export function StudioView() {
  const lab = useLab()
  const navigate = useNavigate()
  const { bottomOpen } = useStudioChrome()
  const [meshMode, setMeshMode] = useState<StudioMeshMode>('topology')
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
              Network
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
              Spatial
            </button>
          </div>
          <span className="hidden font-mono text-[10.5px] text-vcl-dim md:inline">{meta}</span>
          {pertCount > 0 ? (
            <span className="hidden font-mono text-[10px] text-amber-kinase lg:inline">
              {pertCount} KO/dose
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-2 font-mono text-[10px] text-vcl-dim">
            <button
              type="button"
              className="rounded border border-cyan-flux/40 bg-cyan-950/30 px-1.5 py-0.5 text-cyan-flux hover:bg-cyan-950/50"
              onClick={() => navigate('/phenotype')}
            >
              PT · phenotype
            </button>
            <button
              type="button"
              className="rounded border border-vcl-border px-1.5 py-0.5 hover:text-cyan-flux"
              onClick={() => navigate('/pharmacology')}
            >
              PH · dose
            </button>
            <button
              type="button"
              className="rounded border border-vcl-border px-1.5 py-0.5 hover:text-cyan-flux"
              onClick={() => navigate('/xai')}
            >
              XA · drivers
            </button>
            <button
              type="button"
              className="rounded border border-vcl-border px-1.5 py-0.5 hover:text-cyan-flux"
              onClick={() => navigate('/combinations')}
            >
              CB · combos
            </button>
          </div>
        </div>
      ) : (
        <div className="flex h-8 shrink-0 items-center gap-2 border-b border-vcl-border px-3 font-mono text-[10px] text-vcl-dim">
          <span>Studio · map first</span>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="rounded border border-cyan-flux/40 bg-cyan-950/30 px-1.5 py-0.5 text-cyan-flux/90 hover:bg-cyan-950/50"
              onClick={() => navigate('/phenotype')}
            >
              PT · phenotype
            </button>
            <button
              type="button"
              className="rounded border border-vcl-border px-1.5 py-0.5 text-cyan-flux/90 hover:bg-vcl-surface"
              onClick={() => navigate('/pathways')}
            >
              PW · change disease
            </button>
          </div>
        </div>
      )}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {showBootSpinner ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-vcl-muted">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-active" />
            {lab.statusStage ?? 'Bootstrapping simulation studio…'}
          </div>
        ) : !showCanvas ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-vcl-muted">
            Run a simulation to populate the pathway map.
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

        {!bottomOpen ? (
          <div className="pointer-events-auto absolute bottom-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full border border-vcl-border bg-obsidian/92 px-3 py-1.5 shadow-lg backdrop-blur-md">
            <span className="font-mono text-[9px] text-vcl-dim">t₀</span>
            <input
              type="range"
              min={0}
              max={60}
              step={1}
              value={lab.scrubT}
              disabled={!lab.payload}
              onChange={(e) => lab.setScrubT(Number(e.target.value))}
              className="w-[160px] accent-emerald-active disabled:opacity-40 sm:w-[220px]"
            />
            <span className="font-mono text-[9px] text-vcl-dim">t₆₀</span>
            <span className="min-w-[2.75rem] text-right font-mono text-[11px] font-semibold text-emerald-active">
              {lab.scrubT.toFixed(0)}m
            </span>
          </div>
        ) : null}
      </div>
    </div>
  )
}
