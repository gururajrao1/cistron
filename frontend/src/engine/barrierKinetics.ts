/**
 * Blood–brain barrier & peripheral tissue permeability kinetics.
 *
 *   Flux_BBB = P_bbb * (C_vascular - C_tissue)
 *
 * P_bbb derived from Lipinski-ish lipophilicity (logP), MW, and P-gp efflux.
 */

export type TissueBarrierMode = 'peripheral' | 'bbb'

export type DrugPhyschem = {
  /** Octanol/water partition coefficient */
  logP: number
  /** Molecular weight (Da) */
  mwDa: number
  /** P-glycoprotein efflux multiplier (1 = none, >1 stronger efflux) */
  pgpEfflux?: number
}

export type BBBPermeabilityResult = {
  /** Effective permeability (cm/s), scaled for mesh flux */
  P_bbb: number
  /** Unitless mesh coupling coefficient used in RD step */
  meshCoupling: number
  mode: TissueBarrierMode
  lipophilicityScore: number
  sizePenalty: number
  pgpPenalty: number
  summary: string
}

/** Passive permeability proxy (cm/s) from logP + MW. */
export function calculateBBBPermeability(
  drug: DrugPhyschem,
  mode: TissueBarrierMode = 'bbb',
): BBBPermeabilityResult {
  const logP = Number.isFinite(drug.logP) ? drug.logP : 2
  const mw = Math.max(50, drug.mwDa || 400)
  const pgp = Math.max(1, drug.pgpEfflux ?? 1.5)

  // Lipophilicity sweet-spot ~1–3 for CNS
  const lipophilicityScore = Math.exp(-Math.pow((logP - 2.2) / 1.6, 2))
  // MW penalty (CNS drugs typically <450 Da)
  const sizePenalty = 1 / (1 + Math.pow(mw / 420, 2.2))
  const pgpPenalty = mode === 'bbb' ? 1 / pgp : 1 / Math.sqrt(pgp)

  // Peripheral capillaries are ~50–200× more permeable than tight BBB
  const base = mode === 'bbb' ? 2.5e-7 : 4e-5
  const P_bbb = base * lipophilicityScore * sizePenalty * pgpPenalty

  // Map to O(0.01–0.8) mesh coupling for Euler stability at dt~0.05
  const meshCoupling =
    mode === 'bbb'
      ? Math.min(0.35, Math.max(0.01, P_bbb / 1e-6))
      : Math.min(0.85, Math.max(0.15, P_bbb / 5e-5))

  return {
    P_bbb,
    meshCoupling,
    mode,
    lipophilicityScore,
    sizePenalty,
    pgpPenalty,
    summary:
      mode === 'bbb'
        ? `BBB P=${P_bbb.toExponential(2)} cm/s · logP=${logP.toFixed(1)} · MW=${mw.toFixed(0)}`
        : `Peripheral P=${P_bbb.toExponential(2)} cm/s · logP=${logP.toFixed(1)} · MW=${mw.toFixed(0)}`,
  }
}

/** Instantaneous barrier flux (vascular → tissue). */
export function fluxBBB(
  C_vascular: number,
  C_tissue: number,
  P_bbb: number,
): number {
  return P_bbb * (C_vascular - C_tissue)
}

/**
 * Apply barrier-limited exchange between vessel cells and neighbors for DRUG field.
 * Mutates a copy of the drug field and returns it.
 */
export function applyBarrierExchange(
  drugField: Float64Array,
  meta: Array<{ kind: string }>,
  n: number,
  meshCoupling: number,
  dt: number,
): Float64Array {
  const out = new Float64Array(drugField)
  const idx = (x: number, y: number) => y * n + x
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const i = idx(x, y)
      if (meta[i]?.kind !== 'vessel') continue
      const Cv = drugField[i]!
      for (const [dx, dy] of [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ] as const) {
        const xx = x + dx
        const yy = y + dy
        if (xx < 0 || yy < 0 || xx >= n || yy >= n) continue
        const j = idx(xx, yy)
        if (meta[j]?.kind === 'vessel') continue
        const Ct = drugField[j]!
        const flux = meshCoupling * (Cv - Ct) * dt
        out[i] = Math.max(0, out[i]! - flux * 0.25)
        out[j] = Math.max(0, Math.min(1.5, out[j]! + flux))
      }
    }
  }
  return out
}
