/**
 * Extracellular reaction–diffusion PDE on an N×N tissue mesh.
 *
 *   ∂C/∂t = D · ∇²C + Secretion(x,y) − Uptake(x,y) − λ·C
 *
 * Laplacian via 5-point finite-difference stencil (Neumann / reflective borders).
 */

export type GridSpecies = 'VEGFA' | 'TNF' | 'O2' | 'DRUG' | string

export type GridCellKind = 'empty' | 'tumor' | 'source' | 'sink' | 'vessel'

export type GridCellMeta = {
  kind: GridCellKind
  /** Optional gene / ligand identity for sources */
  label?: string
  /** Secretion rate (concentration / min) */
  secretion?: number
  /** Uptake / dosing rate */
  uptake?: number
}

export type DiffusionSpeciesConfig = {
  id: GridSpecies
  /** Diffusion coefficient D (cm²/s), scaled internally to grid units */
  D: number
  /** First-order degradation λ (1/min) */
  degradation: number
  /** Display color stops [low, mid, high] */
  colors?: [string, string, string]
}

export type DiffusionGridConfig = {
  n?: number
  /** Physical domain length (cm) */
  domainCm?: number
  dt?: number
  species?: DiffusionSpeciesConfig[]
}

export type DiffusionGridState = {
  n: number
  domainCm: number
  dx: number
  time: number
  /** speciesId → Float64Array length n*n, row-major */
  fields: Record<string, Float64Array>
  meta: GridCellMeta[]
  species: DiffusionSpeciesConfig[]
}

export const DEFAULT_SPECIES: DiffusionSpeciesConfig[] = [
  {
    id: 'O2',
    D: 1.5e-5,
    degradation: 0.02,
    colors: ['#0f172a', '#06b6d4', '#ecfeff'],
  },
  {
    id: 'VEGFA',
    D: 8e-7,
    degradation: 0.04,
    colors: ['#0f172a', '#10b981', '#a7f3d0'],
  },
  {
    id: 'TNF',
    D: 1.2e-6,
    degradation: 0.05,
    colors: ['#0f172a', '#f59e0b', '#fde68a'],
  },
  {
    id: 'DRUG',
    D: 2.5e-6,
    degradation: 0.03,
    colors: ['#0f172a', '#a855f7', '#e9d5ff'],
  },
]

function idx(n: number, x: number, y: number): number {
  return y * n + x
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/**
 * Convert physical D (cm²/s) → grid diffusivity in (concentration / min)
 * using Δx and a seconds→minutes factor.
 */
function gridDiffusivity(D_cm2_s: number, dx: number): number {
  // D_grid such that D * dt * Laplacian with 1/dx² stays stable for dt~0.05
  const D_cm2_min = D_cm2_s * 60
  return D_cm2_min / (dx * dx)
}

/** 5-point Laplacian with Neumann (zero-flux) boundaries. */
export function laplacian5(
  field: Float64Array,
  n: number,
  x: number,
  y: number,
): number {
  const c = field[idx(n, x, y)]!
  const xm = field[idx(n, x > 0 ? x - 1 : x, y)]!
  const xp = field[idx(n, x < n - 1 ? x + 1 : x, y)]!
  const ym = field[idx(n, x, y > 0 ? y - 1 : y)]!
  const yp = field[idx(n, x, y < n - 1 ? y + 1 : y)]!
  return xm + xp + ym + yp - 4 * c
}

export function createDiffusionGrid(config: DiffusionGridConfig = {}): DiffusionGridState {
  const n = config.n ?? 48
  const domainCm = config.domainCm ?? 0.1
  const dx = domainCm / n
  const species = config.species ?? DEFAULT_SPECIES
  const fields: Record<string, Float64Array> = {}
  for (const s of species) {
    fields[s.id] = new Float64Array(n * n)
  }
  const meta: GridCellMeta[] = Array.from({ length: n * n }, () => ({ kind: 'empty' }))

  // Seed a hypoxic tumor core + peripheral vessels
  const cx = (n - 1) / 2
  const cy = (n - 1) / 2
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const i = idx(n, x, y)
      const r = Math.hypot(x - cx, y - cy) / (n * 0.45)
      if (r < 0.55) {
        meta[i] = {
          kind: 'tumor',
          label: 'tumor',
          secretion: 0.15 * (1 - r), // VEGFA / TNF from hypoxic core
          uptake: 0.08,
        }
        // Low oxygen in core
        fields.O2![i] = 0.15 + 0.25 * r
        fields.VEGFA![i] = 0.35 * (1 - r)
        fields.TNF![i] = 0.12 * (1 - r)
      } else if (r > 0.85 && (x + y) % 11 === 0) {
        meta[i] = { kind: 'vessel', label: 'vessel', secretion: 0, uptake: 0 }
        fields.O2![i] = 0.95
      } else {
        fields.O2![i] = 0.55 + 0.2 * Math.random() * 0.1
      }
    }
  }

  return { n, domainCm, dx, time: 0, fields, meta, species }
}

export type PlaceMode = 'source' | 'sink' | 'tumor' | 'clear'

/** Click interaction: place secretable source cell or drug dosing sink. */
export function placeOnGrid(
  state: DiffusionGridState,
  x: number,
  y: number,
  mode: PlaceMode,
  opts?: { species?: GridSpecies; radius?: number; strength?: number },
): DiffusionGridState {
  const n = state.n
  const gx = clamp(Math.floor(x), 0, n - 1)
  const gy = clamp(Math.floor(y), 0, n - 1)
  const radius = opts?.radius ?? 1
  const strength = opts?.strength ?? 0.8
  const species = opts?.species ?? (mode === 'sink' ? 'DRUG' : 'VEGFA')
  const meta = state.meta.slice()
  const fields: Record<string, Float64Array> = {}
  for (const [k, v] of Object.entries(state.fields)) {
    fields[k] = new Float64Array(v)
  }

  for (let dy = -radius; dy <= radius; dy++) {
    for (let dx = -radius; dx <= radius; dx++) {
      if (dx * dx + dy * dy > radius * radius) continue
      const xx = gx + dx
      const yy = gy + dy
      if (xx < 0 || yy < 0 || xx >= n || yy >= n) continue
      const i = idx(n, xx, yy)
      if (mode === 'clear') {
        meta[i] = { kind: 'empty' }
        continue
      }
      if (mode === 'source') {
        meta[i] = {
          kind: 'source',
          label: String(species),
          secretion: strength,
          uptake: 0.02,
        }
        if (fields[species]) fields[species]![i] = Math.max(fields[species]![i]!, strength)
      } else if (mode === 'sink') {
        meta[i] = {
          kind: 'sink',
          label: 'DRUG',
          secretion: 0,
          uptake: strength * 1.5,
        }
        // Local drug bolus
        if (fields.DRUG) fields.DRUG[i] = Math.max(fields.DRUG[i]!, strength)
      } else if (mode === 'tumor') {
        meta[i] = {
          kind: 'tumor',
          label: 'tumor',
          secretion: 0.2,
          uptake: 0.1,
        }
      }
    }
  }

  return { ...state, meta, fields }
}

/**
 * Advance the reaction–diffusion system by `steps` explicit Euler ticks.
 * CFL-ish safety: D_grid * dt <= 0.2
 */
export function stepDiffusion(
  state: DiffusionGridState,
  opts?: { dt?: number; steps?: number },
): DiffusionGridState {
  const dt = opts?.dt ?? 0.05
  const steps = opts?.steps ?? 1
  const { n, dx, meta, species } = state
  const fields: Record<string, Float64Array> = {}
  for (const [k, v] of Object.entries(state.fields)) {
    fields[k] = new Float64Array(v)
  }

  let time = state.time

  for (let s = 0; s < steps; s++) {
    const next: Record<string, Float64Array> = {}
    for (const spec of species) {
      const cur = fields[spec.id]!
      const out = new Float64Array(n * n)
      const D = Math.min(0.2 / Math.max(dt, 1e-6), gridDiffusivity(spec.D, dx))
      const lam = spec.degradation

      for (let y = 0; y < n; y++) {
        for (let x = 0; x < n; x++) {
          const i = idx(n, x, y)
          const cell = meta[i]!
          const C = cur[i]!
          const lap = laplacian5(cur, n, x, y)

          let secretion = 0
          let uptake = 0

          if (spec.id === 'VEGFA' || spec.id === 'TNF') {
            if (cell.kind === 'tumor' || cell.kind === 'source') {
              // Hypoxia-linked secretion: stronger when O2 low
              const o2 = fields.O2?.[i] ?? 0.5
              const hypoxia = clamp(1 - o2, 0, 1)
              const base =
                cell.kind === 'source' && cell.label === spec.id
                  ? cell.secretion ?? 0.5
                  : (cell.secretion ?? 0) * (spec.id === 'VEGFA' ? 1 : 0.6)
              secretion = base * (0.35 + 0.65 * hypoxia)
            }
          }

          if (spec.id === 'O2') {
            if (cell.kind === 'vessel') secretion = 0.6
            if (cell.kind === 'tumor' || cell.kind === 'source') {
              uptake = cell.uptake ?? 0.1
            }
          }

          if (spec.id === 'DRUG') {
            if (cell.kind === 'sink') secretion = (cell.uptake ?? 0.5) * 0.4 // depot release
            if (cell.kind === 'tumor') uptake = 0.12
          }

          // Generic uptake on sinks for matching species
          if (cell.kind === 'sink' && (cell.label === spec.id || spec.id === 'DRUG')) {
            uptake += cell.uptake ?? 0.2
          }
          if (cell.kind === 'source' && cell.label === spec.id) {
            secretion = Math.max(secretion, cell.secretion ?? 0.5)
          }

          let dC = D * lap + secretion - uptake * C - lam * C
          // Soft production floor near vessels for O2
          if (spec.id === 'O2' && cell.kind === 'vessel') dC += 0.15 * (0.95 - C)

          out[i] = clamp(C + dt * dC, 0, 1.5)
        }
      }
      next[spec.id] = out
    }
    for (const id of Object.keys(next)) {
      fields[id] = next[id]!
    }
    time += dt
  }

  return { ...state, fields, time }
}

/** Run until approximate steady / for a wall-clock budget. */
export function relaxDiffusion(
  state: DiffusionGridState,
  minutes: number,
  dt = 0.05,
): DiffusionGridState {
  const steps = Math.max(1, Math.round(minutes / dt))
  // Chunk to keep UI responsive callers can use smaller minutes
  return stepDiffusion(state, { dt, steps: Math.min(steps, 400) })
}

export function fieldMinMax(field: Float64Array): { min: number; max: number } {
  let min = Infinity
  let max = -Infinity
  for (let i = 0; i < field.length; i++) {
    const v = field[i]!
    if (v < min) min = v
    if (v > max) max = v
  }
  if (!Number.isFinite(min)) return { min: 0, max: 1 }
  if (max - min < 1e-9) return { min, max: min + 1e-6 }
  return { min, max }
}

function parseHex(h: string): [number, number, number] {
  const x = h.replace('#', '')
  return [
    parseInt(x.slice(0, 2), 16),
    parseInt(x.slice(2, 4), 16),
    parseInt(x.slice(4, 6), 16),
  ]
}

function lerpColor(a: string, b: string, t: number): string {
  const ca = parseHex(a)
  const cb = parseHex(b)
  const m = (i: number) => Math.round(ca[i]! + (cb[i]! - ca[i]!) * t)
  return `rgb(${m(0)},${m(1)},${m(2)})`
}

/** Map scalar field → ImageData for canvas blit. */
export function fieldToImageData(
  field: Float64Array,
  n: number,
  colors: [string, string, string] = ['#0f172a', '#06b6d4', '#ecfeff'],
  meta?: GridCellMeta[],
): ImageData {
  const { min, max } = fieldMinMax(field)
  const img = new ImageData(n, n)
  for (let i = 0; i < n * n; i++) {
    const t = clamp((field[i]! - min) / (max - min), 0, 1)
    const col =
      t < 0.5 ? lerpColor(colors[0], colors[1], t * 2) : lerpColor(colors[1], colors[2], (t - 0.5) * 2)
    const m = col.match(/\d+/g)!
    const o = i * 4
    img.data[o] = Number(m[0])
    img.data[o + 1] = Number(m[1])
    img.data[o + 2] = Number(m[2])
    img.data[o + 3] = 255

    // Overlay markers
    if (meta) {
      const kind = meta[i]?.kind
      if (kind === 'source') {
        img.data[o] = 16
        img.data[o + 1] = 185
        img.data[o + 2] = 129
      } else if (kind === 'sink') {
        img.data[o] = 168
        img.data[o + 1] = 85
        img.data[o + 2] = 247
      } else if (kind === 'vessel') {
        img.data[o] = 56
        img.data[o + 1] = 189
        img.data[o + 2] = 248
      }
    }
  }
  return img
}

export function meanField(field: Float64Array): number {
  let s = 0
  for (let i = 0; i < field.length; i++) s += field[i]!
  return s / Math.max(1, field.length)
}
