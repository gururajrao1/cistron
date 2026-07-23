import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
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
import { uploadOmicsCsv } from '../../api/client'
import {
  EXAMPLE_HYPOXIA_RNASEQ_CSV,
  mapLog2FcToY0,
  type OmicsFeature,
  type OmicsProfile,
} from '../../api/types'
import { useLab } from '../../lab/LabContext'

type PreviewRow = {
  symbol: string
  log2_fc: number
  p_value: number | null
  y0: number
  mapped: boolean
}

function featureRows(
  profile: OmicsProfile,
  networkNodes: string[],
  clamps: Record<string, number>,
): PreviewRow[] {
  const net = new Set(networkNodes.map((n) => n.toUpperCase()))
  return Object.values(profile.features)
    .map((f: OmicsFeature) => {
      const sym = f.symbol.toUpperCase()
      const mapped = net.has(sym)
      const y0 =
        clamps[sym] ??
        clamps[f.symbol] ??
        mapLog2FcToY0(f.log2_fc)
      return {
        symbol: sym,
        log2_fc: f.log2_fc,
        p_value: f.p_value ?? null,
        y0,
        mapped,
      }
    })
    .sort((a, b) => Number(b.mapped) - Number(a.mapped) || a.symbol.localeCompare(b.symbol))
}

export function OmicsUploader() {
  const lab = useLab()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const [sampleName, setSampleName] = useState('Tumor Sample 01')
  const [condition, setCondition] = useState('Core Hypoxia')
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [previewProfile, setPreviewProfile] = useState<OmicsProfile | null>(
    lab.activeOmicsProfile,
  )

  const busy = uploading || lab.busy
  const active = previewProfile ?? lab.activeOmicsProfile

  const rows = useMemo(
    () =>
      active
        ? featureRows(active, lab.nodes, lab.omicsClamps)
        : [],
    [active, lab.nodes, lab.omicsClamps],
  )

  const mappedCount = rows.filter((r) => r.mapped).length

  const ingestProfile = useCallback(
    (profile: OmicsProfile) => {
      setPreviewProfile(profile)
      setLocalError(null)
      lab.runOmicsProfile(profile)
    },
    [lab.runOmicsProfile],
  )

  const handleFile = useCallback(
    async (file: File | null) => {
      if (!file || busy) return
      setUploading(true)
      setLocalError(null)
      try {
        const profile = await uploadOmicsCsv(file, sampleName.trim() || 'Tumor Sample 01', condition.trim() || 'Core Hypoxia')
        ingestProfile(profile)
      } catch (err) {
        setLocalError(err instanceof Error ? err.message : 'Upload failed')
      } finally {
        setUploading(false)
      }
    },
    [busy, sampleName, condition, ingestProfile],
  )

  const loadExample = useCallback(async () => {
    if (busy) return
    setUploading(true)
    setLocalError(null)
    try {
      const blob = new File(
        [EXAMPLE_HYPOXIA_RNASEQ_CSV],
        'hypoxia_rnaseq_example.csv',
        { type: 'text/csv' },
      )
      const profile = await uploadOmicsCsv(
        blob,
        sampleName.trim() || 'Tumor Sample 01',
        condition.trim() || 'Core Hypoxia',
      )
      ingestProfile(profile)
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Example load failed')
    } finally {
      setUploading(false)
    }
  }, [busy, sampleName, condition, ingestProfile])

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 lg:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-flux/35 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.25)]">
              <Dna className="h-3 w-3" /> Phase 2 · Omics
            </span>
            {lab.activeOmicsProfile ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-200 shadow-[0_0_14px_rgba(16,185,129,0.2)]">
                <Sparkles className="h-3 w-3" /> Profile live
              </span>
            ) : null}
          </div>
          <h1 className="text-xl font-extrabold tracking-tight text-slate-50">
            Multi-Omics Profile Mapper
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-500">
            Upload differential RNA-seq / proteomics CSV. Fold-changes map to Hill-cube
            baselines <span className="lab-mono text-slate-400">y₀</span> and re-run the
            hypoxia cascade on the Studio canvas.
          </p>
        </div>
        <button
          type="button"
          disabled={!lab.activeOmicsProfile || busy}
          onClick={() => navigate('/studio')}
          className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[12px] font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <FlaskConical className="h-3.5 w-3.5" />
          Open Studio canvas
        </button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
        <GlassCard title="Upload CSV" hint="Drag & drop · gene / log2FC / padj headers">
          <div className="mb-3 grid gap-2 sm:grid-cols-2">
            <label className="block text-[11px]">
              <MetaLabel className="mb-1">Sample name</MetaLabel>
              <input
                value={sampleName}
                onChange={(e) => setSampleName(e.target.value)}
                disabled={busy}
                className="w-full rounded-lg border border-slate-800 bg-obsidian/80 px-2.5 py-2 text-[12px] text-slate-100 outline-none focus:border-emerald-500/40"
              />
            </label>
            <label className="block text-[11px]">
              <MetaLabel className="mb-1">Condition</MetaLabel>
              <input
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
                disabled={busy}
                className="w-full rounded-lg border border-slate-800 bg-obsidian/80 px-2.5 py-2 text-[12px] text-slate-100 outline-none focus:border-emerald-500/40"
              />
            </label>
          </div>

          <div
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragOver(false)
              const f = e.dataTransfer.files?.[0] ?? null
              void handleFile(f)
            }}
            onClick={() => inputRef.current?.click()}
            className={clsx(
              'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-10 transition',
              dragOver
                ? 'border-cyan-flux/60 bg-cyan-950/30 shadow-[0_0_24px_rgba(6,182,212,0.15)]'
                : 'border-slate-700/80 bg-obsidian/40 hover:border-emerald-500/40 hover:bg-emerald-950/20',
              busy && 'pointer-events-none opacity-60',
            )}
          >
            {busy ? (
              <Loader2 className="h-7 w-7 animate-spin text-emerald-active" />
            ) : (
              <Upload className="h-7 w-7 text-cyan-flux" />
            )}
            <div className="text-center text-[13px] font-semibold text-slate-200">
              {busy ? (lab.statusStage ?? 'Processing omics profile…') : 'Drop CSV here or browse'}
            </div>
            <p className="text-center text-[11px] text-slate-500">
              Accepts <span className="lab-mono">gene/symbol</span>,{' '}
              <span className="lab-mono">log2fc</span>, <span className="lab-mono">padj/fdr</span>
            </p>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.tsv,text/csv,text/tab-separated-values"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null
                e.target.value = ''
                void handleFile(f)
              }}
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || !lab.engineLive}
              onClick={() => void loadExample()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-violet-hub/40 bg-violet-950/40 px-3 py-2 text-[11px] font-semibold text-violet-200 shadow-[0_0_14px_rgba(139,92,246,0.15)] hover:bg-violet-900/40 disabled:opacity-40"
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Load Example RNA-seq (Hypoxia log2FC)
            </button>
          </div>

          {localError || lab.offlineMessage ? (
            <p className="mt-3 rounded-lg border border-coral-action/30 bg-coral-action/10 px-2.5 py-2 text-[11px] text-red-200">
              {localError ?? lab.offlineMessage}
            </p>
          ) : null}
        </GlassCard>

        <GlassCard
          title="Active profile"
          hint={
            active
              ? `${active.sample_name} · ${active.condition} · ${Object.keys(active.features).length} genes`
              : 'No profile loaded yet'
          }
        >
          {active ? (
            <div className="space-y-3">
              <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1.5 text-[12px]">
                <dt className="text-slate-500">Profile ID</dt>
                <dd className="lab-mono truncate text-emerald-300">{active.profile_id}</dd>
                <dt className="text-slate-500">Mapped</dt>
                <dd className="text-slate-200">
                  <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/35 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-200">
                    {mappedCount}/{rows.length} network hits
                  </span>
                </dd>
                <dt className="text-slate-500">Latency</dt>
                <dd className="lab-mono text-slate-300">
                  {lab.latencyMs != null ? `${lab.latencyMs.toFixed(0)} ms` : '—'}
                </dd>
              </dl>
              <div className="flex flex-wrap gap-1.5">
                {rows
                  .filter((r) => r.mapped)
                  .slice(0, 12)
                  .map((r) => (
                    <span
                      key={r.symbol}
                      className="inline-flex items-center gap-1 rounded-full border border-cyan-flux/35 bg-cyan-950/50 px-2 py-0.5 text-[10px] font-semibold text-cyan-200 shadow-[0_0_10px_rgba(6,182,212,0.2)]"
                    >
                      <GeneBadge name={r.symbol} tone="cyan" />
                      <span className="lab-mono text-cyan-300/90">y₀={r.y0.toFixed(2)}</span>
                    </span>
                  ))}
              </div>
            </div>
          ) : (
            <p className="text-[12px] leading-relaxed text-slate-500">
              Load the hypoxia example or upload a DE table to condition the cascade.
            </p>
          )}
        </GlassCard>
      </div>

      <GlassCard
        title="Feature preview"
        hint="log2_fc → sigmoid y₀ · glowing rows are present in the active network"
      >
        {rows.length ? (
          <div className="max-h-[340px] overflow-auto rounded-xl border border-slate-800/80">
            <table className="w-full text-left text-[11px]">
              <thead className="sticky top-0 bg-obsidian-panel/95 backdrop-blur">
                <tr className="lab-meta text-slate-500">
                  <th className="px-2.5 py-2 font-semibold">Gene</th>
                  <th className="px-2.5 py-2 font-semibold">log2FC</th>
                  <th className="px-2.5 py-2 font-semibold">p / FDR</th>
                  <th className="px-2.5 py-2 font-semibold">y₀ clamp</th>
                  <th className="px-2.5 py-2 font-semibold">Network</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    className={clsx(
                      'border-t border-slate-800/70',
                      r.mapped && 'bg-emerald-500/[0.04]',
                    )}
                  >
                    <td className="px-2.5 py-1.5">
                      <GeneBadge name={r.symbol} tone={r.mapped ? 'emerald' : 'cyan'} />
                    </td>
                    <td
                      className={clsx(
                        'lab-mono px-2.5 py-1.5',
                        r.log2_fc >= 0 ? 'text-emerald-300' : 'text-coral-action',
                      )}
                    >
                      {r.log2_fc >= 0 ? '+' : ''}
                      {r.log2_fc.toFixed(3)}
                    </td>
                    <td className="lab-mono px-2.5 py-1.5 text-slate-400">
                      {r.p_value != null ? r.p_value.toExponential(2) : '—'}
                    </td>
                    <td className="lab-mono px-2.5 py-1.5 text-cyan-300">
                      {r.y0.toFixed(3)}
                    </td>
                    <td className="px-2.5 py-1.5">
                      {r.mapped ? (
                        <span className="rounded-md border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-200 shadow-[0_0_10px_rgba(16,185,129,0.2)]">
                          Mapped
                        </span>
                      ) : (
                        <span className="text-[10px] uppercase tracking-wide text-slate-600">
                          Off-graph
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[12px] text-slate-500">No features to preview.</p>
        )}
      </GlassCard>
    </div>
  )
}
