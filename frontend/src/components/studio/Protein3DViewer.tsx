import { X } from 'lucide-react'
import { MetaLabel } from '../ui'
import { ProteinStructureCanvas } from './ProteinStructureCanvas'

/**
 * Slide-over wrapper around {@link ProteinStructureCanvas}.
 * Prefer the full-page `/biophysics` workspace for serious inspection.
 */
export function Protein3DViewer({
  open,
  onClose,
  symbol,
}: {
  open: boolean
  onClose: () => void
  symbol: string
}) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/55 backdrop-blur-[2px]">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="Close 3D inspector backdrop"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-full max-w-xl flex-col border-l border-slate-700/80 bg-obsidian-panel shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-slate-800/80 px-4 py-3">
          <div className="min-w-0">
            <MetaLabel className="text-cyan-300/90">3D Structural Inspector</MetaLabel>
            <h2 className="mt-1 truncate text-lg font-extrabold tracking-tight text-slate-50">
              {symbol}
            </h2>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Narrow drawer — use sidebar <span className="text-cyan-300">3D Structure</span> for
              full viewport.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700/80 p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            aria-label="Close 3D inspector"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <ProteinStructureCanvas symbol={symbol} className="min-h-0 flex-1" />
      </aside>
    </div>
  )
}
