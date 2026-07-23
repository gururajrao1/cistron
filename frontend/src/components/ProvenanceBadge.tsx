const SOURCE_COLORS: Record<string, string> = {
  local: 'border-slate-600/70 bg-slate-900/80 text-slate-300',
  omnipath: 'border-emerald-800/50 bg-emerald-950/60 text-emerald-400',
  signor: 'border-teal-800/50 bg-teal-950/60 text-teal-300',
  kegg: 'border-cyan-800/50 bg-cyan-950/60 text-cyan-300',
  reactome: 'border-indigo-800/50 bg-indigo-950/60 text-indigo-300',
  string: 'border-amber-800/50 bg-amber-950/60 text-amber-300',
  biogrid: 'border-orange-800/50 bg-orange-950/60 text-orange-300',
  uniprot: 'border-violet-800/50 bg-violet-950/60 text-violet-300',
}

export function ProvenanceBadge({ source }: { source: string }) {
  const key = source.toLowerCase()
  const cls = SOURCE_COLORS[key] ?? 'border-slate-700 bg-slate-900 text-slate-400'
  return (
    <span
      className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${cls}`}
    >
      {source}
    </span>
  )
}

export { SOURCE_COLORS }
