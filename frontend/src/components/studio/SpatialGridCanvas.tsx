import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Crosshair,
  Droplets,
  Eraser,
  FolderOpen,
  Pause,
  Play,
  RefreshCw,
  Syringe,
} from 'lucide-react'
import { GlassCard } from '../GlassCard'
import { MetaLabel } from '../ui'
import {
  createDiffusionGrid,
  fieldToImageData,
  meanField,
  placeOnGrid,
  stepDiffusion,
  type DiffusionGridState,
  type GridSpecies,
  type PlaceMode,
} from '../../engine/diffusionGrid'
import {
  compartmentAtTime,
  simulateCompartmentOde,
  specsFromGraph,
  type CompartmentState,
  type CompartmentTrajectory,
} from '../../engine/compartmentOde'
import { loadHistologyMesh } from '../../engine/spatialHistologyLoader'
import {
  applyBarrierExchange,
  calculateBBBPermeability,
  type TissueBarrierMode,
} from '../../engine/barrierKinetics'
import type { PresetDetail } from '../../api/types'
import { OrganelleCompartments, stepHif1aTranslocation, BASE_IMPORT_RATE } from './OrganelleCompartments'

type Props = {
  graph: PresetDetail | null
  /** Lab scrubber — unused for organelle clock (mesh time owns it). */
  scrubT: number
  perturbations?: Record<string, number>
  selectedNode?: string | null
}

const SPECIES_OPTS: GridSpecies[] = ['O2', 'VEGFA', 'TNF', 'DRUG']

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

function initialHifState(traj: CompartmentTrajectory | null, sym: string): CompartmentState {
  const at0 =
    (traj && compartmentAtTime(traj, sym, 0)) ||
    (traj && compartmentAtTime(traj, 'HIF1A', 0))
  return (
    at0 ?? {
      cytoplasm: 0.35,
      nucleus: 0.05,
      mitochondria: 0.05,
    }
  )
}

export function SpatialGridCanvas({
  graph,
  scrubT: _scrubT,
  perturbations = {},
  selectedNode,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number | null>(null)
  const gridRef = useRef<DiffusionGridState>(createDiffusionGrid({ n: 56 }))
  const liveCompRef = useRef<CompartmentState>({
    cytoplasm: 0.35,
    nucleus: 0.05,
    mitochondria: 0.05,
  })
  const importRateRef = useRef(0)

  const [grid, setGrid] = useState<DiffusionGridState>(() => gridRef.current)
  const [species, setSpecies] = useState<GridSpecies>('O2')
  const [placeMode, setPlaceMode] = useState<PlaceMode>('sink')
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(2)
  const [oxygenBias, setOxygenBias] = useState(0.25)
  /** Live compartment pools driven by the mesh RAF clock. */
  const [liveCompartment, setLiveCompartment] = useState<CompartmentState>(liveCompRef.current)
  const [liveImportRate, setLiveImportRate] = useState(0)
  const [histologyLabel, setHistologyLabel] = useState<string | null>(null)
  const [bbbEnabled, setBbbEnabled] = useState(false)
  const [drugLogP, setDrugLogP] = useState(2.2)
  const [drugMw, setDrugMw] = useState(380)
  const histologyInputRef = useRef<HTMLInputElement>(null)

  const meshTime = grid.time

  const barrier = useMemo(
    () =>
      calculateBBBPermeability(
        { logP: drugLogP, mwDa: drugMw, pgpEfflux: bbbEnabled ? 2.2 : 1 },
        bbbEnabled ? 'bbb' : 'peripheral',
      ),
    [bbbEnabled, drugLogP, drugMw],
  )
  const barrierMode: TissueBarrierMode = bbbEnabled ? 'bbb' : 'peripheral'

  const compartmentTraj = useMemo<CompartmentTrajectory | null>(() => {
    if (!graph) return null
    try {
      const { nodes, edges } = specsFromGraph(graph, {
        perturbations,
        maxNodes: 28,
      })
      if (!nodes.length) return null
      return simulateCompartmentOde(nodes, edges, {
        oxygen: oxygenBias,
        tEnd: 60,
        dt: 0.5,
      })
    } catch (err) {
      console.warn('compartment ODE failed', err)
      return null
    }
  }, [graph, perturbations, oxygenBias])

  const focusSym = (selectedNode || 'HIF1A').toUpperCase()
  const focusIsHif = focusSym === 'HIF1A' || focusSym === 'EPAS1'

  // Reset live pools when graph / KO set / oxygen bias changes
  useEffect(() => {
    const init = initialHifState(compartmentTraj, focusSym)
    liveCompRef.current = init
    setLiveCompartment(init)
  }, [compartmentTraj, focusSym, perturbations])

  const localO2 = useMemo(() => {
    const meshO2 = grid.fields.O2 ? meanField(grid.fields.O2) : oxygenBias
    // Blend slider bias with live mesh mean so dosing / tumor core still matter
    return clamp01(0.55 * meshO2 + 0.45 * oxygenBias)
  }, [grid, oxygenBias])

  /** Trajectory sample at mesh time (for non-HIF focus genes). */
  const trajCompartment = useMemo(() => {
    if (!compartmentTraj) return null
    const tMax = compartmentTraj.time[compartmentTraj.time.length - 1] ?? 60
    const t = Math.min(Math.max(0, meshTime), tMax)
    return (
      compartmentAtTime(compartmentTraj, focusSym, t) ??
      compartmentAtTime(compartmentTraj, 'HIF1A', t)
    )
  }, [compartmentTraj, focusSym, meshTime])

  const displayCompartment = focusIsHif ? liveCompartment : trajCompartment

  const paint = useCallback((state: DiffusionGridState, sp: GridSpecies) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const field = state.fields[sp]
    if (!field) return
    const spec = state.species.find((s) => s.id === sp)
    const colors = spec?.colors ?? (['#0f172a', '#06b6d4', '#ecfeff'] as [string, string, string])
    const img = fieldToImageData(field, state.n, colors, state.meta)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    if (canvas.width !== state.n) canvas.width = state.n
    if (canvas.height !== state.n) canvas.height = state.n
    ctx.putImageData(img, 0, 0)
  }, [])

  useEffect(() => {
    paint(grid, species)
  }, [grid, species, paint])

  useEffect(() => {
    if (!playing) {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
      return
    }
    let last = performance.now()
    const tick = (now: number) => {
      const elapsed = now - last
      if (elapsed > 32) {
        last = now
        const dt = 0.05 * speed
        const next = stepDiffusion(gridRef.current, {
          dt: 0.05,
          steps: speed,
        })
        // BBB / peripheral barrier exchange on DRUG field after RD step
        if (next.fields.DRUG) {
          next.fields.DRUG = applyBarrierExchange(
            next.fields.DRUG,
            next.meta,
            next.n,
            barrier.meshCoupling,
            0.05 * speed,
          )
        }
        gridRef.current = next

        const meshO2 = next.fields.O2 ? meanField(next.fields.O2) : oxygenBias
        const local = clamp01(0.55 * meshO2 + 0.45 * oxygenBias)
        const { next: compNext, importRate } = stepHif1aTranslocation(
          liveCompRef.current,
          local,
          dt,
          BASE_IMPORT_RATE,
        )
        liveCompRef.current = compNext
        importRateRef.current = importRate

        setGrid(next)
        setLiveCompartment(compNext)
        setLiveImportRate(importRate)
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [playing, speed, oxygenBias, barrier.meshCoupling])

  const loadHistology = useCallback(async (file?: File | null) => {
    const result = loadHistologyMesh({
      n: gridRef.current.n,
      file: file ?? null,
      base: gridRef.current,
    })
    gridRef.current = result.grid
    setGrid(result.grid)
    setHistologyLabel(result.label)
  }, [])

  const onCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * grid.n
    const y = ((e.clientY - rect.top) / rect.height) * grid.n
    const placeSpecies = placeMode === 'sink' ? 'DRUG' : species === 'DRUG' ? 'VEGFA' : species
    const next = placeOnGrid(gridRef.current, x, y, placeMode, {
      species: placeSpecies,
      radius: placeMode === 'clear' ? 2 : 1,
      strength: placeMode === 'sink' ? 1 : 0.85,
    })
    gridRef.current = next
    setGrid(next)
  }

  const reset = () => {
    const next = createDiffusionGrid({ n: 56 })
    gridRef.current = next
    setGrid(next)
    const init = initialHifState(compartmentTraj, focusSym)
    liveCompRef.current = init
    setLiveCompartment(init)
    setLiveImportRate(0)
  }

  const means = useMemo(() => {
    const out: Record<string, number> = {}
    for (const s of SPECIES_OPTS) {
      const f = grid.fields[s]
      if (f) out[s] = meanField(f)
    }
    return out
  }, [grid])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      <div className="grid shrink-0 gap-3 sm:grid-cols-3">
        <GlassCard>
          <div className="text-[0.68rem] uppercase tracking-[0.08em] text-slate-500">
            Mesh time
          </div>
          <div className="mt-1 font-mono text-xl font-bold text-cyan-300">
            {meshTime.toFixed(1)}
            <span className="text-sm font-medium text-slate-500"> min</span>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="text-[0.68rem] uppercase tracking-[0.08em] text-slate-500">
            ⟨{species}⟩
          </div>
          <div className="mt-1 font-mono text-xl font-bold text-emerald-300">
            {(means[species] ?? 0).toFixed(3)}
          </div>
        </GlassCard>
        <GlassCard>
          <div className="text-[0.68rem] uppercase tracking-[0.08em] text-slate-500">
            HIF1A nucleus
          </div>
          <div className="mt-1 font-mono text-xl font-bold text-coral-action">
            {liveCompartment.nucleus.toFixed(3)}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            O₂={localO2.toFixed(2)} · k_import={liveImportRate.toFixed(3)} · cyto→nuc ↑ hypoxia
          </div>
        </GlassCard>
      </div>

      <div
        className="lab-grid-panel relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-slate-800/80 bg-obsidian"
        data-cistron-export="spatial-mesh"
      >
        <canvas
          ref={canvasRef}
          onClick={onCanvasClick}
          className="h-full w-full cursor-crosshair image-rendering-pixelated"
          style={{ imageRendering: 'pixelated' }}
          title="Click to place source / drug sink"
        />

        <div className="pointer-events-none absolute left-2 top-2 z-10 max-w-[200px] rounded-lg border border-slate-700/70 bg-obsidian/90 px-2.5 py-2 backdrop-blur-md">
          <MetaLabel className="!text-cyan-300/90">Spatial microenvironment</MetaLabel>
          <p className="mt-1 text-[10px] leading-snug text-slate-400">
            Reaction–diffusion mesh · 5-point Laplacian · click to dose
          </p>
          {histologyLabel ? (
            <p className="mt-1 truncate text-[9px] text-emerald-300/90" title={histologyLabel}>
              Mask: {histologyLabel}
            </p>
          ) : null}
          <div
            className="mt-2 h-1.5 w-full rounded-full"
            style={{
              background: `linear-gradient(90deg, ${
                grid.species.find((s) => s.id === species)?.colors?.[0] ?? '#0f172a'
              }, ${
                grid.species.find((s) => s.id === species)?.colors?.[1] ?? '#06b6d4'
              }, ${
                grid.species.find((s) => s.id === species)?.colors?.[2] ?? '#ecfeff'
              })`,
            }}
          />
        </div>

        <div className="absolute right-2 top-2 z-10 flex flex-col items-end gap-1.5">
          <input
            ref={histologyInputRef}
            type="file"
            accept=".csv,.png,.jpg,.jpeg,.tif,.tiff,image/*"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              void loadHistology(f)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            onClick={() => {
              // Always seed geometry; optionally attach a user mask file
              if (!histologyInputRef.current) {
                void loadHistology(null)
                return
              }
              // One-click synthetic Visium mask; hold Shift to pick a file
              void loadHistology(null)
            }}
            onContextMenu={(e) => {
              e.preventDefault()
              histologyInputRef.current?.click()
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-950/70 px-2.5 py-1.5 text-[11px] font-bold text-amber-100 shadow-[0_0_12px_rgba(245,158,11,0.2)] backdrop-blur-md hover:bg-amber-900/70"
            title="Click: load synthetic Visium/H&E mask · Right-click: choose file"
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Load Histology Mask
          </button>
          <button
            type="button"
            onClick={() => histologyInputRef.current?.click()}
            className="rounded-md border border-slate-700/80 bg-obsidian/80 px-2 py-0.5 text-[9px] font-semibold text-slate-400 hover:text-slate-200"
          >
            Or choose Visium / H&E file…
          </button>
          <span className="max-w-[180px] rounded-md border border-slate-700/60 bg-obsidian/80 px-2 py-1 text-[9px] leading-snug text-slate-400">
            {barrierMode === 'bbb' ? 'BBB' : 'Peripheral'} · {barrier.summary}
          </span>
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-xl border border-slate-800/80 bg-obsidian-panel/60 px-3 py-2">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-100"
        >
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {playing ? 'Pause' : 'Run'}
        </button>
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-[11px] font-semibold text-slate-300 hover:bg-slate-800"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Reset
        </button>

        <div className="mx-1 h-5 w-px bg-slate-800" />

        {SPECIES_OPTS.map((sp) => (
          <button
            key={sp}
            type="button"
            onClick={() => setSpecies(sp)}
            className={`rounded-lg border px-2 py-1 font-mono text-[10px] font-bold ${
              species === sp
                ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-100'
                : 'border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {sp}
          </button>
        ))}

        <div className="mx-1 h-5 w-px bg-slate-800" />

        <ToolBtn
          active={placeMode === 'source'}
          onClick={() => setPlaceMode('source')}
          icon={<Droplets className="h-3.5 w-3.5" />}
          label="Source"
        />
        <ToolBtn
          active={placeMode === 'sink'}
          onClick={() => setPlaceMode('sink')}
          icon={<Syringe className="h-3.5 w-3.5" />}
          label="Drug sink"
        />
        <ToolBtn
          active={placeMode === 'tumor'}
          onClick={() => setPlaceMode('tumor')}
          icon={<Crosshair className="h-3.5 w-3.5" />}
          label="Tumor"
        />
        <ToolBtn
          active={placeMode === 'clear'}
          onClick={() => setPlaceMode('clear')}
          icon={<Eraser className="h-3.5 w-3.5" />}
          label="Erase"
        />

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-950/30 px-2 py-1 text-[10px] font-semibold text-sky-100">
            <input
              type="checkbox"
              checked={bbbEnabled}
              onChange={(e) => setBbbEnabled(e.target.checked)}
              className="accent-sky-400"
            />
            Blood-Brain Barrier (BBB)
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            MW (Da)
            <input
              type="range"
              min={150}
              max={900}
              step={10}
              value={drugMw}
              onChange={(e) => setDrugMw(Number(e.target.value))}
              className="w-16 accent-violet-400"
            />
            <span className="lab-mono w-8 text-violet-200">{drugMw}</span>
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            logP
            <input
              type="range"
              min={-1}
              max={6}
              step={0.1}
              value={drugLogP}
              onChange={(e) => setDrugLogP(Number(e.target.value))}
              className="w-16 accent-violet-400"
            />
            <span className="lab-mono w-7 text-violet-200">{drugLogP.toFixed(1)}</span>
          </label>
          <label className="flex items-center gap-1.5 text-[10px] text-slate-500">
            O₂ bias
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={oxygenBias}
              onChange={(e) => setOxygenBias(Number(e.target.value))}
              className="w-20 accent-cyan-flux"
            />
            <span className="lab-mono text-cyan-200/90">{oxygenBias.toFixed(2)}</span>
          </label>
          <label className="flex items-center gap-1.5 text-[10px] text-slate-500">
            speed
            <input
              type="range"
              min={1}
              max={8}
              step={1}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="w-16 accent-emerald-active"
            />
          </label>
        </div>
      </div>

      <OrganelleCompartments
        meshTime={meshTime}
        symbol={compartmentTraj?.nodes[focusSym] ? focusSym : 'HIF1A'}
        compartment={displayCompartment}
        localO2={localO2}
        importRate={focusIsHif ? liveImportRate : undefined}
      />
    </div>
  )
}

function ToolBtn({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold ${
        active
          ? 'border-violet-hub/50 bg-violet-500/15 text-violet-100'
          : 'border-slate-700 text-slate-400 hover:bg-slate-800'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}
