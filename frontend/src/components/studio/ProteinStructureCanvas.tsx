import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Box,
  Loader2,
  Palette,
  RotateCcw,
  Scan,
  ZoomIn,
} from 'lucide-react'
import { clsx } from 'clsx'
import { fetchPdbForGeneSymbol, type PdbFetchResult } from '../../utils/bioApi'

type ColorMode = 'ss' | 'chain' | 'bFactor'

type MolViewer = {
  addModel: (data: string, format: string) => unknown
  setStyle: (sel: object, style: object) => void
  addSurface?: (
    type: unknown,
    style?: object,
    sel?: object,
  ) => Promise<unknown> | unknown
  removeAllSurfaces?: () => void
  zoomTo: (sel?: object) => void
  zoom: (factor: number, animationDuration?: number) => void
  render: () => void
  clear: () => void
  resize?: () => void
  setBackgroundColor?: (c: string | number) => void
  setClickable?: (
    sel: object,
    clickable: boolean,
    callback?: (atom: { resi?: number; resn?: string }) => void,
  ) => void
}

type MolModule = {
  createViewer: (element: HTMLElement, config?: object) => MolViewer
  SurfaceType?: { VDW?: unknown; SAS?: unknown }
  ssColors?: { Jmol?: unknown }
}

export type StructureResidueHighlight = {
  position: number
  label?: string
  color?: string
}

async function load3Dmol(): Promise<MolModule> {
  const mod = await import('3dmol/build/3Dmol.js')
  const $3Dmol = (mod as { default?: MolModule } & MolModule).default ?? (mod as MolModule)
  return $3Dmol
}

/**
 * Embeddable 3Dmol canvas — resolves UniProt/PDB/AlphaFold for any gene symbol.
 * Supports PTM residue highlights + click-to-select phosphorylation sites.
 */
export function ProteinStructureCanvas({
  symbol,
  className,
  highlightResidues,
  selectedResidue,
  onResidueSelect,
}: {
  symbol: string
  className?: string
  highlightResidues?: StructureResidueHighlight[]
  selectedResidue?: number | null
  onResidueSelect?: (resi: number | null) => void
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<MolViewer | null>(null)
  const molRef = useRef<MolModule | null>(null)
  const onResidueSelectRef = useRef(onResidueSelect)
  onResidueSelectRef.current = onResidueSelect
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [resolved, setResolved] = useState<PdbFetchResult | null>(null)
  const [surfaceOn, setSurfaceOn] = useState(false)
  const [showLigands, setShowLigands] = useState(true)
  const [colorMode, setColorMode] = useState<ColorMode>('ss')

  useEffect(() => {
    const sym = symbol.trim()
    if (!sym) {
      setStatus('idle')
      setResolved(null)
      setError(null)
      return
    }
    let cancelled = false
    const run = async () => {
      setStatus('loading')
      setError(null)
      setResolved(null)
      setSurfaceOn(false)
      setColorMode('ss')
      try {
        const hit = await fetchPdbForGeneSymbol(sym)
        if (cancelled) return
        setResolved(hit)

        const $3Dmol = await load3Dmol()
        if (cancelled) return
        molRef.current = $3Dmol

        const el = hostRef.current
        if (!el) throw new Error(`No 3D structural model found for ${sym}`)
        el.innerHTML = ''
        const viewer = $3Dmol.createViewer(el, {
          backgroundColor: 0x0b1220,
          antialias: true,
        })
        viewerRef.current = viewer
        viewer.clear()
        viewer.addModel(hit.pdbText, 'pdb')
        applyStyles(viewer, $3Dmol, true, 'ss', [], null)
        // Click residues for PTM site selection
        viewer.setClickable?.({}, true, (atom) => {
          const resi = typeof atom?.resi === 'number' ? atom.resi : null
          onResidueSelectRef.current?.(resi)
        })
        viewer.zoomTo()
        viewer.render()
        viewer.resize?.()
        setStatus('ready')
        requestAnimationFrame(() => viewer.resize?.())
      } catch (err) {
        if (cancelled) return
        setStatus('error')
        const msg =
          err instanceof Error ? err.message : `No 3D structural model found for ${sym}`
        setError(
          msg.includes('No 3D structural model')
            ? msg
            : `No 3D structural model found for ${sym}`,
        )
      }
    }
    void run()
    return () => {
      cancelled = true
      viewerRef.current = null
    }
  }, [symbol])

  useEffect(() => {
    if (status !== 'ready' || !viewerRef.current || !molRef.current) return
    applyStyles(
      viewerRef.current,
      molRef.current,
      showLigands,
      colorMode,
      highlightResidues ?? [],
      selectedResidue ?? null,
    )
    viewerRef.current.render()
  }, [showLigands, colorMode, status, highlightResidues, selectedResidue])

  useEffect(() => {
    if (status !== 'ready' || !viewerRef.current || !molRef.current) return
    const viewer = viewerRef.current
    const $3Dmol = molRef.current
    const toggle = async () => {
      try {
        viewer.removeAllSurfaces?.()
        if (surfaceOn) {
          const surf = $3Dmol.SurfaceType?.VDW ?? 1
          await viewer.addSurface?.(surf, {
            opacity: 0.35,
            color: 'lightblue',
          })
        }
        viewer.render()
      } catch (err) {
        console.warn('Surface toggle failed', err)
      }
    }
    void toggle()
  }, [surfaceOn, status])

  useEffect(() => {
    if (status !== 'ready') return
    const onResize = () => viewerRef.current?.resize?.()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [status])

  const cycleColor = () => {
    setColorMode((m) => (m === 'ss' ? 'chain' : m === 'chain' ? 'bFactor' : 'ss'))
  }

  const empty = !symbol.trim()

  return (
    <div className={clsx('flex min-h-0 flex-col overflow-hidden', className)}>
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-2 border-b border-slate-800/80 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-slate-100">
            {symbol.trim() || 'Select a gene'}
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-slate-500">
            {resolved ? (
              <>
                {resolved.accession}
                {' · '}
                <a
                  className="text-cyan-300 hover:underline"
                  href={resolved.structureUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {resolved.structureId}
                </a>
                <span className="text-slate-600">
                  {' '}
                  (
                  {resolved.source === 'pdb'
                    ? `experimental${
                        resolved.resolutionAngstrom != null
                          ? ` · ${resolved.resolutionAngstrom.toFixed(2)} Å`
                          : ''
                      }`
                    : 'AlphaFold'}
                  )
                </span>
              </>
            ) : (
              '—'
            )}
          </p>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 bg-[#0b1220]">
        <div ref={hostRef} className="absolute inset-0 h-full w-full" />
        {empty ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center p-8 text-center text-sm text-slate-400">
            Enter a gene symbol or pick a node from the active scenario to load a structure.
          </div>
        ) : null}
        {!empty && status === 'loading' ? (
          <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-[#0b1220]/85 px-6 text-center text-sm text-slate-300">
            <Loader2 className="h-7 w-7 animate-spin text-cyan-flux" />
            Resolving 3D structure for {symbol} via UniProt/PDB…
          </div>
        ) : null}
        {!empty && status === 'error' ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center p-8 text-center text-sm text-red-200">
            {error ?? `No 3D structural model found for ${symbol}`}
          </div>
        ) : null}
      </div>

      <div className="shrink-0 space-y-2 border-t border-slate-800/80 px-3 py-2.5">
        <div className="flex flex-wrap gap-1.5">
          <ControlBtn
            label="Reset camera"
            icon={<RotateCcw className="h-3.5 w-3.5" />}
            disabled={status !== 'ready'}
            onClick={() => {
              viewerRef.current?.zoomTo()
              viewerRef.current?.render()
            }}
          />
          <ControlBtn
            label="Zoom in"
            icon={<ZoomIn className="h-3.5 w-3.5" />}
            disabled={status !== 'ready'}
            onClick={() => {
              viewerRef.current?.zoom(1.2, 200)
              viewerRef.current?.render()
            }}
          />
          <ControlBtn
            label={
              colorMode === 'ss'
                ? 'Color · SS'
                : colorMode === 'chain'
                  ? 'Color · Chain'
                  : 'Color · B-factor'
            }
            icon={<Palette className="h-3.5 w-3.5" />}
            disabled={status !== 'ready'}
            active
            onClick={cycleColor}
          />
          <ControlBtn
            label={surfaceOn ? 'Hide surface' : 'Surface'}
            icon={<Scan className="h-3.5 w-3.5" />}
            disabled={status !== 'ready'}
            active={surfaceOn}
            onClick={() => setSurfaceOn((v) => !v)}
          />
          <ControlBtn
            label={showLigands ? 'Ligands on' : 'Ligands off'}
            icon={<Box className="h-3.5 w-3.5" />}
            disabled={status !== 'ready'}
            active={showLigands}
            onClick={() => setShowLigands((v) => !v)}
          />
        </div>
        <p className="text-[10px] leading-relaxed text-slate-500">
          Drag to rotate · scroll to zoom · click a residue to select phospho / PTM sites
          {highlightResidues?.length
            ? ` · ${highlightResidues.length} PTM site(s) highlighted`
            : ''}
          .
        </p>
      </div>
    </div>
  )
}

function applyStyles(
  viewer: MolViewer,
  $3Dmol: MolModule,
  ligands: boolean,
  colorMode: ColorMode,
  highlights: StructureResidueHighlight[],
  selected: number | null,
) {
  const cartoon =
    colorMode === 'ss'
      ? {
          cartoon: {
            colorscheme: {
              prop: 'ss',
              map: $3Dmol.ssColors?.Jmol ?? {
                h: '0xFF0000',
                s: '0xFFFF00',
                c: '0x00FF00',
              },
            },
          },
        }
      : colorMode === 'chain'
        ? { cartoon: { color: 'spectrum' } }
        : { cartoon: { colorscheme: 'whiteCarbon' }, cartoonOpacity: 0.95 }

  if (colorMode === 'bFactor') {
    viewer.setStyle({}, { cartoon: { colorscheme: { prop: 'b', gradient: 'roygb' } } })
  } else {
    viewer.setStyle({}, cartoon)
  }

  if (ligands) {
    viewer.setStyle(
      { hetflag: true },
      {
        stick: { radius: 0.18 },
        sphere: { scale: 0.25 },
      },
    )
  }

  for (const h of highlights) {
    if (!h.position || h.position <= 0) continue
    const isSel = selected != null && selected === h.position
    viewer.setStyle(
      { resi: h.position },
      {
        cartoon: { color: h.color ?? (isSel ? '#f43f5e' : '#a855f7') },
        stick: { radius: isSel ? 0.28 : 0.18, color: h.color ?? '#e9d5ff' },
      },
    )
  }

  if (selected != null && selected > 0 && !highlights.some((h) => h.position === selected)) {
    viewer.setStyle(
      { resi: selected },
      {
        cartoon: { color: '#f43f5e' },
        stick: { radius: 0.25, color: '#fb7185' },
      },
    )
  }
}

function ControlBtn({
  label,
  icon,
  onClick,
  disabled,
  active,
}: {
  label: string
  icon: ReactNode
  onClick: () => void
  disabled?: boolean
  active?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold disabled:opacity-40',
        active
          ? 'border-cyan-flux/50 bg-cyan-950/50 text-cyan-100'
          : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:border-slate-500',
      )}
    >
      {icon}
      {label}
    </button>
  )
}
