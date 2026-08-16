import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ChevronDown,
  ChevronRight,
  GitBranch,
  Grid3x3,
  Loader2,
} from 'lucide-react'
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
import {
  loadPhenotypeOpen,
  persistPhenotypeOpen,
} from '../layout/studioChrome'
import { useStudioChrome } from '../layout/StudioChromeContext'

type StudioMeshMode = 'topology' | 'spatial'

export function StudioView() {
  const lab = useLab()
  const navigate = useNavigate()
  const { bottomOpen } = useStudioChrome()
  const [meshMode, setMeshMode] = useState<StudioMeshMode>('topology')
  const [protocolOpen, setProtocolOpen] = useState(false)
  const [phenotypeOpen, setPhenotypeOpen] = useState(loadPhenotypeOpen)
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
  const headline = phenotype.sentences[0]?.text ?? 'Run a simulation to see phenotype.'

  const setPheno = (open: boolean) => {
    setPhenotypeOpen(open)
    persistPhenotypeOpen(open)
  }

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
          <button
            type="button"
            className="ml-auto rounded border border-vcl-border px-1.5 py-0.5 text-cyan-flux/90 hover:bg-vcl-surface"
            onClick={() => navigate('/pathways')}
          >
            PW · change disease
          </button>
        </div>
      )}

      {/* Compact phenotype: one line by default — expand for gauges */}
      <div className="shrink-0 border-b border-vcl-border/80 bg-obsidian/25">
        <button
          type="button"
          onClick={() => setPheno(!phenotypeOpen)}
          className="flex w-full items-start gap-2 px-3 py-2 text-left"
        >
          {phenotypeOpen ? (
            <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-flux" />
          ) : (
            <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-flux" />
          )}
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-cyan-flux">
              Phenotype
            </div>
            <p className="truncate text-[12px] leading-snug text-vcl-soft">{headline}</p>
          </div>
          <span className="shrink-0 font-mono text-[9px] text-vcl-dim">
            {phenotypeOpen ? 'Hide' : 'Details'}
          </span>
        </button>
        {phenotypeOpen ? (
          <div className="max-h-[min(220px,32vh)] space-y-2 overflow-y-auto border-t border-vcl-border/60 px-3 py-2.5">
            <PhenotypeSummaryCard summary={phenotype} showGauges />
            <div className="rounded-lg border border-amber-kinase/25 bg-[#1a1408]/60">
              <button
                type="button"
                onClick={() => setProtocolOpen((v) => !v)}
                className="flex w-full items-center gap-1.5 px-3 py-2 text-left font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-amber-kinase"
              >
                {protocolOpen ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                Wet-lab protocol
              </button>
              {protocolOpen ? (
                <div className="border-t border-amber-kinase/20 px-1 pb-2">
                  <WetLabProtocolCard protocol={protocol} className="!border-0 !bg-transparent" />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

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

        {/* Scrubber on the map when Analysis dock is closed */}
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
