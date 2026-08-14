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
 * Full-bleed 3D Structural Inspector — left rail + maximized mol viewer.
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
          color: selectedResi === s.position ? '#fb7185' : '#22d3ee',
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
    <div className="flex h-full min-h-0 flex-col overflow-hidden lg:flex-row">
      {/* Compact control rail — scrolls independently; viewer gets the rest */}
      <aside className="flex max-h-[38vh] w-full shrink-0 flex-col overflow-y-auto border-b border-vcl-border bg-obsidian-panel/80 lg:max-h-none lg:w-[272px] lg:border-b-0 lg:border-r">
        <div className="space-y-2.5 p-2.5">
          <div>
            <p className="lab-meta text-cyan-flux/80">3D · UniProt · PDB · AlphaFold</p>
            <h1 className="font-display mt-0.5 text-[15px] font-semibold tracking-tight text-vcl-text">
              Structure
            </h1>
          </div>

          <GlassCard className="!rounded-lg !p-2.5 space-y-2">
            <MetaLabel className="text-cyan-flux/90">Gene</MetaLabel>
            <form onSubmit={onSubmit} className="flex gap-1.5">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value.toUpperCase())}
                placeholder="TP53"
                spellCheck={false}
                className="vcl-focus-ring min-w-0 flex-1 rounded-md border border-vcl-border bg-obsidian/80 px-2 py-1.5 font-mono text-[12px] text-vcl-text outline-none placeholder:text-vcl-dim focus:border-cyan-flux/50"
              />
              <button
                type="submit"
                className="vcl-focus-ring inline-flex items-center gap-1 rounded-md border border-cyan-flux/40 bg-[#0a1f28] px-2.5 py-1.5 text-[11px] font-semibold text-cyan-flux hover:brightness-110"
              >
                <Search className="h-3.5 w-3.5" />
                Load
              </button>
            </form>
          </GlassCard>

          {geneSites.length > 0 ? (
            <GlassCard className="!rounded-lg !p-2.5 space-y-1.5">
              <MetaLabel className="!text-cyan-flux/80">PTM sites</MetaLabel>
              <div className="flex max-h-[9rem] flex-col gap-1 overflow-y-auto">
                {geneSites.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => loadSymbol(s.symbol, s.position)}
                    className={clsx(
                      'vcl-focus-ring rounded-md border px-2 py-1 text-left font-mono text-[11px] font-semibold transition',
                      selectedResi === s.position
                        ? 'border-rose-inhib/50 bg-rose-950/40 text-rose-100'
                        : 'border-vcl-border bg-vcl-surface text-vcl-soft hover:border-cyan-flux/40',
                    )}
                  >
                    {s.label}
                    <span className="ml-1.5 text-vcl-dim">×{s.phosphoRatio.toFixed(2)}</span>
                  </button>
                ))}
              </div>
            </GlassCard>
          ) : null}

          {scenarioGenes.length > 0 ? (
            <GlassCard className="!rounded-lg !p-2.5 space-y-1.5">
              <MetaLabel>Scenario</MetaLabel>
              <div className="flex flex-wrap gap-1">
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

          <GlassCard className="!rounded-lg !p-2.5 space-y-1.5">
            <MetaLabel>Quick load</MetaLabel>
            <div className="flex flex-wrap gap-1">
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
              className="vcl-focus-ring mt-0.5 inline-flex items-center gap-1.5 text-[11px] font-medium text-vcl-dim hover:text-cyan-flux"
            >
              <Box className="h-3 w-3" />
              Back to Studio
            </button>
          </GlassCard>
        </div>
      </aside>

      {/* Maximized mol viewport — fills remaining height */}
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden bg-[#071018]">
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
        'vcl-focus-ring rounded-md border px-1.5 py-0.5 font-mono text-[10.5px] font-semibold transition',
        active
          ? 'border-cyan-flux/50 bg-[#0a1f28] text-cyan-flux'
          : 'border-vcl-border bg-vcl-surface text-vcl-soft hover:border-vcl-border-strong hover:text-vcl-text',
      )}
    >
      {label}
    </button>
  )
}
