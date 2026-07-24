import { FlaskConical } from 'lucide-react'
import { GeneBadge, MetaLabel } from '../ui'
import type { CompartmentState } from '../../engine/compartmentOde'

/** Baseline cytoplasm→nucleus import (1/min) before hypoxia scaling. */
export const BASE_IMPORT_RATE = 0.18
const BASE_EXPORT_RATE = 0.06

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

/**
 * Advance HIF1A pools with hypoxia-driven nuclear import:
 *   cytoToNucRate = baseImportRate * (1 - localO2)
 *   nuc = min(1, nuc + cytoToNucRate * dt)
 */
export function stepHif1aTranslocation(
  state: CompartmentState,
  localO2: number,
  dt: number,
  baseImportRate = BASE_IMPORT_RATE,
): { next: CompartmentState; importRate: number } {
  const o2 = clamp01(localO2)
  const cytoToNucRate = baseImportRate * (1 - o2)
  const exportRate = BASE_EXPORT_RATE * o2

  let cytoplasm = state.cytoplasm
  let nucleus = state.nucleus
  let mitochondria = state.mitochondria

  const importFlux = cytoToNucRate * dt
  const movedIn = Math.min(Math.max(0, cytoplasm), importFlux)
  cytoplasm = Math.max(0, cytoplasm - movedIn)
  nucleus = Math.min(1.0, nucleus + movedIn)

  const movedOut = Math.min(nucleus, exportRate * dt)
  nucleus = Math.max(0, nucleus - movedOut)
  cytoplasm = Math.min(1.0, cytoplasm + movedOut)

  const mitoLeak = 0.01 * dt
  const toMito = Math.min(cytoplasm, mitoLeak)
  cytoplasm -= toMito
  mitochondria = Math.min(1.0, mitochondria + toMito * 0.5)

  return {
    next: {
      cytoplasm: clamp01(cytoplasm),
      nucleus: clamp01(nucleus),
      mitochondria: clamp01(mitochondria),
    },
    importRate: cytoToNucRate,
  }
}

type Props = {
  /** Spatial mesh animation time (minutes) — tracks RAF / diffusion clock. */
  meshTime: number
  symbol: string
  compartment: CompartmentState | null
  /** Mean extracellular O₂ used for the cyto→nuc import law. */
  localO2?: number
  importRate?: number
}

/**
 * Organelle compartment readout locked to the spatial reaction–diffusion clock
 * (not the Studio scrubber, which often sits at t=0).
 */
export function OrganelleCompartments({
  meshTime,
  symbol,
  compartment,
  localO2,
  importRate,
}: Props) {
  if (!compartment) {
    return (
      <p className="text-[10px] text-slate-600">
        Load a Studio graph to couple compartmental Hill-cube translocation with the mesh.
      </p>
    )
  }

  return (
    <div className="shrink-0 rounded-xl border border-violet-hub/30 bg-violet-950/20 px-3 py-2">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <FlaskConical className="h-3.5 w-3.5 text-violet-300" />
        <MetaLabel className="!text-violet-300">Organelle compartments</MetaLabel>
        <GeneBadge name={symbol} tone="violet" />
        <span className="lab-mono text-[10px] text-slate-500">
          t={meshTime.toFixed(1)} min
        </span>
        {localO2 != null ? (
          <span className="lab-mono text-[10px] text-cyan-400/80">
            O₂={localO2.toFixed(2)}
            {importRate != null ? ` · k_import=${importRate.toFixed(3)}` : ''}
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <CompBar label="Cytoplasm" value={compartment.cytoplasm} color="#34d399" />
        <CompBar label="Nucleus" value={compartment.nucleus} color="#f43f5e" />
        <CompBar label="Mitochondria" value={compartment.mitochondria} color="#f59e0b" />
      </div>
    </div>
  )
}

function CompBar({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color: string
}) {
  return (
    <div>
      <div className="mb-0.5 flex justify-between text-[9px] text-slate-500">
        <span>{label}</span>
        <span className="lab-mono text-slate-300">{value.toFixed(3)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full transition-[width] duration-150"
          style={{ width: `${Math.max(2, Math.min(100, value * 100))}%`, background: color }}
        />
      </div>
    </div>
  )
}
