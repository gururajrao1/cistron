import { FlaskConical } from 'lucide-react'
import { GeneBadge, MetaLabel } from '../ui'
import type { CompartmentState } from '../../engine/compartmentOde'

type Props = {
  /** Scrubber / display time (minutes) — locked to server trajectory clock. */
  meshTime: number
  symbol: string
  compartment: CompartmentState | null
  /** Mean extracellular O₂ (display only). */
  localO2?: number
  /** Hypoxia import rate proxy (display only; not integrated on client). */
  importRate?: number
}

/**
 * Organelle compartment readout bound to server 2-compartment trajectories.
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
        Run a Studio simulation to load server HIF1A cytoplasm / nucleus pools.
      </p>
    )
  }

  return (
    <div className="shrink-0 rounded-xl border border-violet-hub/30 bg-cyan-950/20 px-3 py-2">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <FlaskConical className="h-3.5 w-3.5 text-cyan-300" />
        <MetaLabel className="!text-cyan-300">Organelle compartments</MetaLabel>
        <GeneBadge name={symbol} tone="violet" />
        <span className="lab-mono text-[10px] text-slate-500">
          t={meshTime.toFixed(1)} min
        </span>
        {localO2 != null ? (
          <span className="lab-mono text-[10px] text-cyan-400/80">
            O₂={localO2.toFixed(2)}
            {importRate != null ? ` · k_import≈${importRate.toFixed(3)}` : ''}
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <CompBar label="Cytoplasm" value={compartment.cytoplasm} color="#34d399" />
        <CompBar label="Nucleus" value={compartment.nucleus} color="#f43f5e" />
        <CompBar label="Mitochondria" value={compartment.mitochondria} color="#f59e0b" />
      </div>
      <p className="mt-1.5 text-[9px] leading-relaxed text-slate-500">
        cyto/nuc from server LSODA mass-action (not client Euler).
      </p>
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
