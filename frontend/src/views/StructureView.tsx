import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Box, Search } from 'lucide-react'
import { clsx } from 'clsx'
import { GlassCard } from '../components/GlassCard'
import { MetaLabel } from '../components/ui'
import { ProteinStructureCanvas } from '../components/studio/ProteinStructureCanvas'
import { useLab } from '../lab/LabContext'
import {
  EXAMPLE_PHOSPHO_CSV,
  ingestPtmCsv,
  type PtmSite,
} from '../services/ptmIngestion'

const SUGGESTIONS = ['TP53', 'EGFR', 'BRCA1', 'HIF1A', 'VEGFA', 'KRAS', 'MYC', 'AKT1']

/**
 * Full-page 3D Structural Inspector workspace (sidebar → 3D Structure).
 * Supports PTM residue selection via ?resi= and phospho-site chips.
 */
export function StructureView() {
  const lab = useLab()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const symbolFromUrl = (params.get('symbol') || '').trim().toUpperCase()
  const resiFromUrl = Number(params.get('resi') || 0) || null

  const [draft, setDraft] = useState(symbolFromUrl)
  const [active, setActive] = useState(symbolFromUrl)
  const [selectedResi, setSelectedResi] = useState<number | null>(resiFromUrl)

  const demoSites = useMemo(() => ingestPtmCsv(EXAMPLE_PHOSPHO_CSV).bySymbol, [])

  useEffect(() => {
    const next = symbolFromUrl
    setDraft(next)
    setActive(next)
  }, [symbolFromUrl])

  useEffect(() => {
    setSelectedResi(resiFromUrl)
  }, [resiFromUrl])

  useEffect(() => {
    if (symbolFromUrl) return
    if (lab.selectedNode) {
      setParams({ symbol: lab.selectedNode }, { replace: true })
    }
  }, [lab.selectedNode, symbolFromUrl, setParams])

  const scenarioGenes = useMemo(() => {
    const skip = new Set(['O2', 'ROS', 'LPS', 'EGF', 'ATP', 'GTP'])
    return lab.nodes.filter((n) => !skip.has(n.toUpperCase()))
  }, [lab.nodes])

  const geneSites: PtmSite[] = demoSites[active] ?? []

  const highlights = useMemo(
    () =>
      geneSites
        .filter((s) => s.position > 0)
        .map((s) => ({
          position: s.position,
          label: s.label,
          color: selectedResi === s.position ? '#f43f5e' : '#a855f7',
        })),
    [geneSites, selectedResi],
  )

  const loadSymbol = (raw: string, resi?: number | null) => {
    const sym = raw.trim().toUpperCase()
    if (!sym) return
    setDraft(sym)
    setActive(sym)
    const next: Record<string, string> = { symbol: sym }
    if (resi && resi > 0) next.resi = String(resi)
    setParams(next, { replace: true })
    setSelectedResi(resi && resi > 0 ? resi : null)
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    loadSymbol(draft)
  }

  const onResidueSelect = (resi: number | null) => {
    setSelectedResi(resi)
    if (!active) return
    const next: Record<string, string> = { symbol: active }
    if (resi && resi > 0) next.resi = String(resi)
    setParams(next, { replace: true })
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3 lg:flex-row lg:gap-4 lg:p-4">
      <aside className="flex w-full shrink-0 flex-col gap-3 overflow-y-auto lg:w-[300px]">
        <div>
          <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
            3D Structure
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Full-viewport UniProt / PDB / AlphaFold inspector · click residues for PTM sites.
          </p>
        </div>

        <GlassCard className="space-y-3">
          <MetaLabel className="text-cyan-300/90">Gene symbol</MetaLabel>
          <form onSubmit={onSubmit} className="flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value.toUpperCase())}
              placeholder="e.g. TP53"
              spellCheck={false}
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950/80 px-3 py-2 font-mono text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-flux/50"
            />
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-flux/40 bg-cyan-950/50 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-900/50"
            >
              <Search className="h-3.5 w-3.5" />
              Load
            </button>
          </form>
          <p className="text-[10px] leading-relaxed text-slate-500">
            Resolves human Swiss-Prot entries, prefers best-resolution experimental PDB, else
            AlphaFold.
          </p>
        </GlassCard>

        {geneSites.length > 0 ? (
          <GlassCard className="space-y-2">
            <MetaLabel className="!text-violet-300">Phospho / PTM sites</MetaLabel>
            <p className="text-[10px] text-slate-500">
              Select an active phosphorylation residue on the structure.
            </p>
            <div className="flex flex-col gap-1">
              {geneSites.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => loadSymbol(s.symbol, s.position)}
                  className={clsx(
                    'rounded-lg border px-2 py-1.5 text-left font-mono text-[11px] font-semibold',
                    selectedResi === s.position
                      ? 'border-violet-400/50 bg-violet-950/50 text-violet-100'
                      : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:border-violet-500/40',
                  )}
                >
                  {s.label}
                  <span className="ml-2 text-slate-500">×{s.phosphoRatio.toFixed(2)}</span>
                </button>
              ))}
            </div>
          </GlassCard>
        ) : null}

        {scenarioGenes.length > 0 ? (
          <GlassCard className="space-y-2">
            <MetaLabel>Scenario proteins</MetaLabel>
            <p className="text-[11px] text-slate-500">
              From active network · {lab.profileId || 'unresolved'}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {scenarioGenes.map((sym) => (
                <GeneChip
                  key={sym}
                  label={sym}
                  active={active === sym}
                  onClick={() => loadSymbol(sym)}
                />
              ))}
            </div>
          </GlassCard>
        ) : null}

        <GlassCard className="space-y-2">
          <MetaLabel>Quick load</MetaLabel>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((sym) => (
              <GeneChip
                key={sym}
                label={sym}
                active={active === sym}
                onClick={() => loadSymbol(sym)}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={() => navigate('/studio')}
            className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 hover:text-emerald-300"
          >
            <Box className="h-3 w-3" />
            Back to Simulation Studio
          </button>
        </GlassCard>
      </aside>

      <div className="min-h-[420px] min-w-0 flex-1 overflow-hidden rounded-xl border border-slate-800/80 bg-obsidian-panel shadow-[inset_0_0_0_1px_rgba(15,23,42,0.6)] lg:min-h-0">
        <ProteinStructureCanvas
          symbol={active}
          className="h-full"
          highlightResidues={highlights}
          selectedResidue={selectedResi}
          onResidueSelect={onResidueSelect}
        />
      </div>
    </div>
  )
}

function GeneChip({
  label,
  active,
  onClick,
}: {
  label: string
  active?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'rounded-md border px-2 py-1 font-mono text-[11px] font-semibold transition',
        active
          ? 'border-cyan-flux/50 bg-cyan-950/60 text-cyan-100'
          : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:border-slate-500 hover:text-slate-100',
      )}
    >
      {label}
    </button>
  )
}
