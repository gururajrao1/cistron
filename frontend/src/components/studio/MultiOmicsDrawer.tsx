import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity,
  Beaker,
  Dna,
  FileSpreadsheet,
  FlaskConical,
  Loader2,
  Sparkles,
  Upload,
} from 'lucide-react'
import { clsx } from 'clsx'
import { GlassCard } from '../GlassCard'
import { GeneBadge, MetaLabel } from '../ui'
import { useLab } from '../../lab/LabContext'
import {
  EXAMPLE_PHOSPHO_CSV,
  baselinesToClamps,
  buildPtmBaselines,
  ingestPtmCsv,
  type CombinedBaseline,
  type PtmSite,
} from '../../services/ptmIngestion'
import {
  EXAMPLE_MAXQUANT_CSV,
  massSpecToPtmIngest,
  parseMassSpecCsv,
} from '../../services/massSpecParser'
import {
  metabolicAtTime,
  simulateMetabolicBridge,
  type MetabolicBridgeResult,
} from '../../engine/metabolicBridge'
import { mapLog2FcToY0 } from '../../api/types'

export type OmicsLayer =
  | 'transcriptomics'
  | 'proteomics'
  | 'phospho'
  | 'metabolomics'

const LAYERS: Array<{ id: OmicsLayer; label: string; hint: string }> = [
  { id: 'transcriptomics', label: 'Transcriptomics (RNA-seq)', hint: 'mRNA log2FC → Boltzmann y₀' },
  { id: 'proteomics', label: 'Proteomics (Mass Spec)', hint: 'Total protein abundance' },
  { id: 'phospho', label: 'Phospho-Proteomics (PTM)', hint: 'Site ratios × transcript y₀' },
  { id: 'metabolomics', label: 'Metabolomics', hint: 'Enzyme → metabolite flux (MM)' },
]

/**
 * Multi-omics ingestion inspector: layer toggle, PTM baselines, transcript vs phospho
 * overlay across t₀→t₆₀, and metabolomics flux readouts.
 */
export function MultiOmicsDrawer({
  className,
  compact,
}: {
  className?: string
  compact?: boolean
}) {
  const lab = useLab()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const massSpecRef = useRef<HTMLInputElement>(null)

  const [layer, setLayer] = useState<OmicsLayer>('phospho')
  const [ptmSites, setPtmSites] = useState<PtmSite[]>([])
  const [activeSiteBySymbol, setActiveSiteBySymbol] = useState<Record<string, string | null>>({})
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [msFormat, setMsFormat] = useState<string | null>(null)

  const transcriptLfc = useMemo(() => {
    const map: Record<string, number> = {}
    const feats = lab.activeOmicsProfile?.features
    if (feats) {
      for (const [k, f] of Object.entries(feats)) {
        map[k.toUpperCase()] = f.log2_fc
        map[f.symbol.toUpperCase()] = f.log2_fc
      }
    }
    return map
  }, [lab.activeOmicsProfile])

  const ptmBySymbol = useMemo(() => {
    const m: Record<string, PtmSite[]> = {}
    for (const s of ptmSites) {
      if (!m[s.symbol]) m[s.symbol] = []
      m[s.symbol]!.push(s)
    }
    return m
  }, [ptmSites])

  const baselines = useMemo(
    () => buildPtmBaselines(transcriptLfc, ptmBySymbol, activeSiteBySymbol),
    [transcriptLfc, ptmBySymbol, activeSiteBySymbol],
  )

  const metabolic = useMemo<MetabolicBridgeResult | null>(() => {
    if (!lab.payload) return null
    return simulateMetabolicBridge(lab.payload)
  }, [lab.payload])

  const metaNow = useMemo(
    () => (metabolic ? metabolicAtTime(metabolic, lab.scrubT) : null),
    [metabolic, lab.scrubT],
  )

  const fluxPill = useMemo(() => {
    if (!metaNow || !metabolic) {
      return { atpPct: 0, lactate: 0, ocrPct: 0 }
    }
    const first = metabolic.series[0]
    const atp0 = first?.atpYield ?? 0.5
    const atp = metaNow.atpYield
    const atpPct = atp0 > 1e-6 ? ((atp - atp0) / atp0) * 100 : 0
    // OCR proxy: inverse of lactate / NAD redox (Warburg ↑ → OCR ↓)
    const ocrPct = Math.max(
      5,
      Math.min(100, 100 - metaNow.lactateExport * 35 + metaNow.nadRatio * 8),
    )
    return {
      atpPct,
      lactate: metaNow.lactateExport * 4.2, // scale to mmol/L-ish display
      ocrPct,
    }
  }, [metaNow, metabolic])

  const handleMassSpecUpload = useCallback(async (file: File | null) => {
    if (!file) return
    setBusy(true)
    setStatus(null)
    try {
      const text = await file.text()
      const parsed = parseMassSpecCsv(text, { sampleName: file.name })
      const asPtm = massSpecToPtmIngest(parsed)
      setPtmSites(asPtm.sites)
      setWarnings(asPtm.warnings.slice(0, 6))
      setMsFormat(parsed.format)
      setStatus(
        `MaxQuant/FragPipe (${parsed.format}): ${parsed.sites.length} sites · stoichiometric occupancy`,
      )
      setLayer('phospho')
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Mass-spec parse failed')
    } finally {
      setBusy(false)
    }
  }, [])

  const loadMaxQuantExample = () => {
    const parsed = parseMassSpecCsv(EXAMPLE_MAXQUANT_CSV, { sampleName: 'example_maxquant' })
    const asPtm = massSpecToPtmIngest(parsed)
    setPtmSites(asPtm.sites)
    setWarnings(asPtm.warnings)
    setMsFormat(parsed.format)
    setStatus(`Example MaxQuant: ${parsed.sites.length} phospho-sites`)
    setLayer('phospho')
  }

  const overlaySeries = useMemo(() => {
    return buildOverlaySeries({
      payload: lab.payload,
      baselines,
      transcriptLfc,
      scrubSteps: lab.payload?.time_steps ?? Array.from({ length: 61 }, (_, i) => i),
    })
  }, [lab.payload, baselines, transcriptLfc])

  const ingestFile = useCallback(async (file: File | null) => {
    if (!file) return
    setBusy(true)
    setStatus(null)
    try {
      const text = await file.text()
      const result = ingestPtmCsv(text, {
        sampleName: file.name,
        condition: 'Phospho MS',
      })
      setPtmSites(result.sites)
      setWarnings(result.warnings.slice(0, 6))
      setStatus(`Loaded ${result.sites.length} PTM site(s)`)
      setLayer('phospho')
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'PTM ingest failed')
    } finally {
      setBusy(false)
    }
  }, [])

  const loadExample = () => {
    const result = ingestPtmCsv(EXAMPLE_PHOSPHO_CSV, {
      sampleName: 'example_phospho',
      condition: 'Hypoxia phospho',
    })
    setPtmSites(result.sites)
    setWarnings(result.warnings)
    setStatus(`Example: ${result.sites.length} phospho-sites`)
    setLayer('phospho')
  }

  const applyPtmClamps = () => {
    const clamps = baselinesToClamps(baselines.filter((b) => b.sites.length > 0 || b.log2FcTranscript !== 0))
    const entries = Object.entries(clamps)
    if (!entries.length) {
      setStatus('No PTM/transcript baselines to apply')
      return
    }
    // Apply without N intermediate resims, then one resim on last
    entries.forEach(([sym, y0], i) => {
      lab.setNodePerturbation(sym, y0, { resim: i === entries.length - 1 })
    })
    setStatus(`Applied ${entries.length} PTM-conditioned y₀ clamps`)
  }

  const selectSite = (site: PtmSite) => {
    setActiveSiteBySymbol((prev) => ({ ...prev, [site.symbol]: site.id }))
    lab.setSelectedNode(site.symbol)
  }

  const openStructure = (site: PtmSite) => {
    selectSite(site)
    navigate(`/biophysics?symbol=${encodeURIComponent(site.symbol)}&resi=${site.position}`)
  }

  return (
    <div className={clsx('space-y-3', className)}>
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-orange-500/30 bg-orange-950/20 px-2.5 py-2">
        <input
          ref={massSpecRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            void handleMassSpecUpload(e.target.files?.[0] ?? null)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => massSpecRef.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-orange-500/45 bg-orange-950/50 px-2.5 py-1.5 text-[11px] font-bold text-orange-100"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          Upload MaxQuant / FragPipe CSV
        </button>
        <button
          type="button"
          onClick={loadMaxQuantExample}
          className="rounded-lg border border-slate-700 px-2 py-1.5 text-[10px] font-semibold text-slate-300 hover:bg-slate-800"
        >
          Example MaxQuant
        </button>
        {msFormat ? (
          <span className="lab-mono text-[9px] text-orange-300/80">{msFormat}</span>
        ) : null}
        <span className="ml-auto inline-flex items-center gap-2 rounded-full border border-emerald-500/35 bg-emerald-950/40 px-2.5 py-1 font-mono text-[10px] font-semibold text-emerald-100">
          ATP: {fluxPill.atpPct >= 0 ? '+' : ''}
          {fluxPill.atpPct.toFixed(0)}% | Lactate: {fluxPill.lactate.toFixed(1)} mmol/L | OCR:{' '}
          {fluxPill.ocrPct.toFixed(0)}%
        </span>
      </div>

      <GlassCard
        title="Multi-Omics Layers"
        hint="Transcript · Proteomics · PTM · Metabolite flux"
      >
        <div className="flex flex-wrap gap-1.5">
          {LAYERS.map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => setLayer(l.id)}
              className={clsx(
                'rounded-lg border px-2.5 py-1.5 text-left text-[10px] font-semibold leading-tight transition',
                layer === l.id
                  ? 'border-orange-500/45 bg-orange-950/40 text-orange-100'
                  : 'border-slate-700 text-slate-400 hover:bg-slate-800',
              )}
              title={l.hint}
            >
              {l.label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-slate-500">
          {LAYERS.find((l) => l.id === layer)?.hint}
        </p>
      </GlassCard>

      {(layer === 'phospho' || layer === 'proteomics') && (
        <GlassCard title="PTM / Mass-spec ingest" hint="p-HIF1A(Ser643) · phospho ratios → y₀">
          <div className="flex flex-wrap gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => void ingestFile(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-hub/40 bg-violet-950/40 px-2.5 py-1.5 text-[11px] font-bold text-violet-100"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              Upload PTM CSV
            </button>
            <button
              type="button"
              onClick={loadExample}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-[11px] font-semibold text-slate-300 hover:bg-slate-800"
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Example phospho
            </button>
            <button
              type="button"
              disabled={!ptmSites.length || lab.busy}
              onClick={applyPtmClamps}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-bold text-emerald-100 disabled:opacity-40"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Apply PTM y₀
            </button>
          </div>
          {status ? <p className="mt-2 text-[10px] text-cyan-200/90">{status}</p> : null}
          {warnings.length ? (
            <p className="mt-1 text-[10px] text-amber-200/80">{warnings.join(' · ')}</p>
          ) : null}

          {ptmSites.length > 0 ? (
            <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto">
              {ptmSites.slice(0, compact ? 6 : 12).map((s) => {
                const active = activeSiteBySymbol[s.symbol] === s.id ||
                  (!activeSiteBySymbol[s.symbol] && ptmBySymbol[s.symbol]?.[0]?.id === s.id)
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => selectSite(s)}
                      onDoubleClick={() => openStructure(s)}
                      className={clsx(
                        'flex w-full items-center justify-between gap-2 rounded-lg border px-2 py-1 text-left text-[11px]',
                        active
                          ? 'border-violet-400/40 bg-violet-950/40 text-violet-100'
                          : 'border-slate-800 bg-slate-950/40 text-slate-300 hover:border-slate-600',
                      )}
                    >
                      <span className="min-w-0 truncate font-mono">
                        <GeneBadge name={s.symbol} tone="violet" className="!mr-1" />
                        {s.label}
                      </span>
                      <span className="lab-mono shrink-0 text-slate-400">
                        ×{s.phosphoRatio.toFixed(2)}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="mt-2 text-[10px] text-slate-600">
              Upload a phospho table or load the hypoxia example (HIF1A Ser643, MTOR Ser2448, …).
              Double-click a site to open the 3D viewer on that residue.
            </p>
          )}
        </GlassCard>
      )}

      {layer === 'transcriptomics' && (
        <GlassCard title="Transcriptomics" hint="Active RNA-seq profile">
          {lab.activeOmicsProfile ? (
            <div className="space-y-1 text-[11px] text-slate-300">
              <div>
                {lab.activeOmicsProfile.condition} · {lab.activeOmicsProfile.sample_name}
              </div>
              <div className="lab-mono text-slate-500">
                {Object.keys(lab.activeOmicsProfile.features).length} genes · fit{' '}
                {lab.omicsAlignmentScore != null ? `${lab.omicsAlignmentScore.toFixed(0)}%` : '—'}
              </div>
              <button
                type="button"
                className="mt-1 text-[11px] font-semibold text-cyan-300 underline"
                onClick={() => navigate('/omics')}
              >
                Open full Omics uploader
              </button>
            </div>
          ) : (
            <p className="text-[11px] text-slate-500">
              No RNA-seq profile loaded.{' '}
              <button
                type="button"
                className="font-semibold text-cyan-300 underline"
                onClick={() => navigate('/omics')}
              >
                Upload
              </button>
            </p>
          )}
        </GlassCard>
      )}

      {(layer === 'phospho' || layer === 'transcriptomics' || layer === 'proteomics') && (
        <GlassCard
          title="Transcript vs phospho activity"
          hint="Overlay across t₀ → t₆₀"
        >
          <OverlayChart series={overlaySeries} scrubT={lab.scrubT} />
          {!compact && baselines.filter((b) => b.sites.length).length > 0 ? (
            <div className="mt-2 space-y-1">
              <MetaLabel>PTM-conditioned baselines</MetaLabel>
              {baselines
                .filter((b) => b.sites.length)
                .slice(0, 5)
                .map((b) => (
                  <BaselineRow key={b.symbol} row={b} />
                ))}
            </div>
          ) : null}
        </GlassCard>
      )}

      {layer === 'metabolomics' && (
        <GlassCard
          title="Metabolomics flux bridge"
          hint="Flux = k_cat · y_enzyme · S/(K_m+S)"
        >
          {metaNow && metabolic ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <Metric label="Lactate" value={metaNow.lactateExport} />
                <Metric label="Pyruvate" value={metaNow.pools.Pyruvate ?? 0} />
                <Metric label="ATP" value={metaNow.atpYield} />
                <Metric label="NAD+/NADH" value={metaNow.nadRatio} />
              </div>
              <MetaLabel className="!mt-1">Active enzyme fluxes @ t={lab.scrubT.toFixed(0)}</MetaLabel>
              <ul className="space-y-1">
                {Object.entries(metaNow.fluxes)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 6)
                  .map(([id, f]) => (
                    <li
                      key={id}
                      className="flex justify-between font-mono text-[10px] text-slate-400"
                    >
                      <span className="text-emerald-300/90">{id}</span>
                      <span>{f.toFixed(3)}</span>
                    </li>
                  ))}
              </ul>
              <p className="text-[10px] text-slate-600">
                Enzymes coupled:{' '}
                {metabolic.enzymesUsed.join(', ') || 'none in active graph'}
              </p>
            </div>
          ) : (
            <p className="text-[11px] text-slate-500">
              Run a Studio simulation with GLUT1 / LDHA / PKM2 in the network to populate metabolite
              fluxes.
            </p>
          )}
        </GlassCard>
      )}

      <p className="px-1 text-[10px] leading-relaxed text-slate-600">
        <Dna className="mr-1 inline h-3 w-3" />
        y₀,i = Boltzmann(log2FC_transcript) × Phospho_Ratio_Site ·{' '}
        <Beaker className="mx-0.5 inline h-3 w-3" />
        metabolite pools integrate with the scrubber.
      </p>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="lab-mono text-sm font-bold text-slate-100">{value.toFixed(3)}</div>
    </div>
  )
}

function BaselineRow({ row }: { row: CombinedBaseline }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-slate-800/80 bg-obsidian/40 px-2 py-1 text-[10px]">
      <GeneBadge name={row.symbol} tone="amber" />
      <span className="lab-mono text-slate-400">
        B={row.boltzmannY0.toFixed(2)} × {row.phosphoRatio.toFixed(2)} →{' '}
        <span className="text-emerald-300">{row.y0.toFixed(2)}</span>
      </span>
    </div>
  )
}

type OverlayPoint = {
  t: number
  transcript: number
  phospho: number
}

function buildOverlaySeries(args: {
  payload: ReturnType<typeof useLab>['payload']
  baselines: CombinedBaseline[]
  transcriptLfc: Record<string, number>
  scrubSteps: number[]
}): OverlayPoint[] {
  const focus =
    args.baselines.find((b) => b.sites.length)?.symbol ??
    Object.keys(args.transcriptLfc)[0] ??
    null
  if (!focus) {
    return args.scrubSteps.map((t) => ({ t, transcript: 0.5, phospho: 0.5 }))
  }
  const base = args.baselines.find((b) => b.symbol === focus)
  const txY0 = mapLog2FcToY0(args.transcriptLfc[focus] ?? 0)
  const phY0 = base?.y0 ?? txY0
  const series = args.payload?.nodes[focus]

  return args.scrubSteps.map((t, i) => {
    const ySim = series?.[Math.min(i, (series?.length ?? 1) - 1)] ?? null
    // Transcript curve: Boltzmann baseline relaxing toward sim (or flat)
    const transcript = ySim != null ? 0.35 * txY0 + 0.65 * ySim : txY0
    // Phospho-active form: elevated by site ratio, tracks sim shape
    const phospho =
      ySim != null ? Math.min(0.99, (0.25 * phY0 + 0.75 * ySim) * (base?.phosphoRatio ?? 1) ** 0.35) : phY0
    return { t, transcript, phospho }
  })
}

function OverlayChart({
  series,
  scrubT,
}: {
  series: OverlayPoint[]
  scrubT: number
}) {
  const w = 280
  const h = 88
  const pad = 6
  if (series.length < 2) {
    return <p className="text-[10px] text-slate-600">Insufficient series for overlay.</p>
  }
  const t0 = series[0]!.t
  const t1 = series[series.length - 1]!.t || 60
  const xOf = (t: number) => pad + ((t - t0) / (t1 - t0 || 1)) * (w - pad * 2)
  const yOf = (v: number) => h - pad - Math.max(0, Math.min(1, v)) * (h - pad * 2)

  const path = (key: 'transcript' | 'phospho') =>
    series
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.t).toFixed(1)},${yOf(p[key]).toFixed(1)}`)
      .join(' ')

  const scrubX = xOf(scrubT)

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="h-24 w-full overflow-visible">
        <line
          x1={pad}
          x2={w - pad}
          y1={yOf(0.5)}
          y2={yOf(0.5)}
          stroke="#334155"
          strokeDasharray="3 3"
        />
        <path d={path('transcript')} fill="none" stroke="#38bdf8" strokeWidth={1.8} />
        <path d={path('phospho')} fill="none" stroke="#c084fc" strokeWidth={1.8} />
        <line x1={scrubX} x2={scrubX} y1={pad} y2={h - pad} stroke="#94a3b8" strokeWidth={1} />
      </svg>
      <div className="mt-1 flex flex-wrap gap-3 text-[9px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-1.5 w-3 rounded bg-sky-400" /> Transcript abundance
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-1.5 w-3 rounded bg-violet-400" /> Phospho-active form
        </span>
        <span className="inline-flex items-center gap-1">
          <Activity className="h-3 w-3" /> scrub t={scrubT.toFixed(0)}
        </span>
      </div>
    </div>
  )
}

/** Compact rail for Studio aside. */
export function MultiOmicsRail() {
  return (
    <div className="rounded-2xl border border-orange-500/25 bg-orange-950/10 p-0.5">
      <div className="flex items-center gap-1.5 px-3 pt-2.5">
        <FlaskConical className="h-3.5 w-3.5 text-orange-300" />
        <span className="text-[0.65rem] font-bold uppercase tracking-[0.1em] text-orange-200/90">
          Multi-omics
        </span>
      </div>
      <div className="p-2.5 pt-1.5">
        <MultiOmicsDrawer compact />
      </div>
    </div>
  )
}
