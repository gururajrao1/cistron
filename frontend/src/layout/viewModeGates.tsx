import { type ReactNode } from 'react'
import { useLab } from '../lab/LabContext'
import type { ViewMode } from '../lab/viewMode'

export function useViewMode(): ViewMode {
  return useLab().viewMode
}

/** Charts, heatmaps, spatial mesh, drug sliders. */
export function showCharts(mode: ViewMode): boolean {
  return mode !== 'biologist'
}

/** Raw matrices, ODE params, Sobol tables, FBA vectors. */
export function showRawMath(mode: ViewMode): boolean {
  return mode === 'systems'
}

/** Open numeric tables by default (Systems Math). */
export function defaultShowNumbers(mode: ViewMode): boolean {
  return mode === 'systems'
}

type GateProps = { children: ReactNode; fallback?: ReactNode }

/** Hide charts / dense viz in Biologist mode. */
export function ChartsOnly({ children, fallback = null }: GateProps) {
  const mode = useViewMode()
  return <>{showCharts(mode) ? children : fallback}</>
}

/** Show only in Systems Math (raw derivatives, matrices). */
export function RawMathOnly({ children, fallback = null }: GateProps) {
  const mode = useViewMode()
  return <>{showRawMath(mode) ? children : fallback}</>
}

/** Researcher + Systems (not Biologist). */
export function ResearcherPlus({ children, fallback = null }: GateProps) {
  const mode = useViewMode()
  return <>{showCharts(mode) ? children : fallback}</>
}
