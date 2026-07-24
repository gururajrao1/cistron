/**
 * Histology / Visium spatial transcriptomics → discrete tissue mesh masks.
 * Maps H&E-style regions onto diffusion-grid cell types with local IFP / vessel BCs.
 */

import {
  createDiffusionGrid,
  type DiffusionGridState,
  type GridCellMeta,
} from './diffusionGrid'

export type HistologyCellType =
  | 'tumor_core'
  | 'vascular_shell'
  | 'stroma'
  | 'necrotic_center'
  | 'healthy_parenchyma'

export type HistologyRegion = {
  type: HistologyCellType
  /** Fractional radius band [r0, r1] from tissue center (0–1) */
  r0: number
  r1: number
  ifpMmHg: number
  o2Baseline: number
  secretion?: number
  uptake?: number
}

export type HistologyMeshResult = {
  grid: DiffusionGridState
  regions: HistologyRegion[]
  source: 'synthetic_visium' | 'he_mask' | 'visium_csv'
  label: string
}

const DEFAULT_REGIONS: HistologyRegion[] = [
  { type: 'necrotic_center', r0: 0, r1: 0.18, ifpMmHg: 28, o2Baseline: 0.05, uptake: 0.02 },
  { type: 'tumor_core', r0: 0.18, r1: 0.52, ifpMmHg: 22, o2Baseline: 0.18, secretion: 0.22, uptake: 0.12 },
  { type: 'vascular_shell', r0: 0.52, r1: 0.68, ifpMmHg: 12, o2Baseline: 0.85, secretion: 0.05 },
  { type: 'stroma', r0: 0.68, r1: 0.88, ifpMmHg: 8, o2Baseline: 0.55, uptake: 0.04 },
  { type: 'healthy_parenchyma', r0: 0.88, r1: 1.2, ifpMmHg: 3, o2Baseline: 0.75 },
]

function idx(n: number, x: number, y: number): number {
  return y * n + x
}

function regionAt(r: number, regions: HistologyRegion[]): HistologyRegion {
  return regions.find((reg) => r >= reg.r0 && r < reg.r1) ?? regions[regions.length - 1]!
}

function toGridKind(t: HistologyCellType): GridCellMeta['kind'] {
  if (t === 'vascular_shell') return 'vessel'
  if (t === 'tumor_core' || t === 'necrotic_center') return 'tumor'
  if (t === 'stroma') return 'source'
  return 'empty'
}

/**
 * Build / overlay a Visium-style histology mask onto an N×N diffusion mesh.
 * Pass `file` for future CSV/PNG loaders; without a file, seeds a clinical tumor geometry.
 */
export function loadHistologyMesh(opts?: {
  n?: number
  file?: File | null
  label?: string
  base?: DiffusionGridState | null
}): HistologyMeshResult {
  const n = opts?.n ?? opts?.base?.n ?? 56
  const regions = DEFAULT_REGIONS
  const grid = opts?.base
    ? {
        ...opts.base,
        fields: Object.fromEntries(
          Object.entries(opts.base.fields).map(([k, v]) => [k, new Float64Array(v)]),
        ),
        meta: opts.base.meta.slice(),
        time: 0,
      }
    : createDiffusionGrid({ n })

  const cx = (n - 1) / 2
  const cy = (n - 1) / 2
  const scale = n * 0.48

  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const i = idx(n, x, y)
      const r = Math.hypot(x - cx, y - cy) / scale
      const reg = regionAt(r, regions)
      const kind = toGridKind(reg.type)
      grid.meta[i] = {
        kind,
        label: reg.type,
        secretion: reg.secretion ?? 0,
        uptake: reg.uptake ?? 0.03,
        // stash IFP in unused numeric via secretion metadata convention
      }
      // IFP encoded lightly into TNF for visualization of pressure shell
      if (grid.fields.TNF) {
        grid.fields.TNF[i] = Math.min(1.2, (reg.ifpMmHg / 30) * 0.9)
      }
      if (grid.fields.O2) {
        grid.fields.O2[i] = reg.o2Baseline
      }
      if (grid.fields.VEGFA && (reg.type === 'tumor_core' || reg.type === 'necrotic_center')) {
        grid.fields.VEGFA[i] = 0.15 + 0.55 * (1 - r)
      }
      if (grid.fields.DRUG && reg.type === 'vascular_shell') {
        grid.fields.DRUG[i] = 0.35
      }
    }
  }

  const source: HistologyMeshResult['source'] = opts?.file
    ? opts.file.name.toLowerCase().endsWith('.csv')
      ? 'visium_csv'
      : 'he_mask'
    : 'synthetic_visium'

  return {
    grid,
    regions,
    source,
    label: opts?.label ?? opts?.file?.name ?? 'Synthetic Visium / H&E tumor mask',
  }
}
