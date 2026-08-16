import { clsx } from 'clsx'

type Props = {
  /** Cytoplasmic pool fraction or absolute (normalized internally). */
  cyto: number
  /** Nuclear pool fraction or absolute. */
  nuc: number
  label?: string
  className?: string
}

/** Cell glyph — cytoplasm ring + nucleus; dots encode relative pool mass. */
export function CompartmentCellGlyph({
  cyto,
  nuc,
  label = 'HIF1A localization',
  className,
}: Props) {
  const total = Math.max(1e-6, cyto + nuc)
  const cytoF = cyto / total
  const nucF = nuc / total
  const cytoDots = Math.max(1, Math.round(cytoF * 8))
  const nucDots = Math.max(0, Math.round(nucF * 8))
  const tip = `${label}: cyto=${cyto.toFixed(3)} · nuc=${nuc.toFixed(3)} (${(nucF * 100).toFixed(0)}% nuclear)`

  return (
    <div className={clsx('flex flex-col gap-1', className)} title={tip}>
      <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-vcl-dim">
        <span>{label}</span>
        <span className="text-cyan-flux">{(nucF * 100).toFixed(0)}% nuc</span>
      </div>
      <svg viewBox="0 0 100 72" className="mx-auto h-12 w-full max-w-[120px]" aria-hidden>
        {/* Cell body */}
        <ellipse
          cx="50"
          cy="36"
          rx="42"
          ry="30"
          fill="#0a1f28"
          stroke="#2A3A4A"
          strokeWidth="1.5"
        />
        {/* Cytoplasm dots */}
        {Array.from({ length: cytoDots }).map((_, i) => {
          const a = (i / cytoDots) * Math.PI * 2 + 0.4
          const r = 22
          return (
            <circle
              key={`c-${i}`}
              cx={50 + Math.cos(a) * r}
              cy={36 + Math.sin(a) * r * 0.7}
              r="2.2"
              fill="#34d399"
              opacity="0.85"
            />
          )
        })}
        {/* Nucleus */}
        <circle cx="50" cy="36" r="14" fill="#12202c" stroke="#38BDF8" strokeWidth="1.5" />
        {Array.from({ length: nucDots }).map((_, i) => {
          const a = (i / Math.max(1, nucDots)) * Math.PI * 2
          const r = 6
          return (
            <circle
              key={`n-${i}`}
              cx={50 + Math.cos(a) * r}
              cy={36 + Math.sin(a) * r}
              r="2"
              fill="#f43f5e"
              opacity="0.9"
            />
          )
        })}
      </svg>
      <div className="flex justify-center gap-3 font-mono text-[9px] text-vcl-dim">
        <span className="text-emerald-active">cyto {(cytoF * 100).toFixed(0)}%</span>
        <span className="text-coral-action">nuc {(nucF * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}
