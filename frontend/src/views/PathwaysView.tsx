import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FlaskConical,
  GitBranch,
  Loader2,
  Network,
  Search,
  Sparkles,
  Zap,
} from 'lucide-react'
import { clsx } from 'clsx'
import { GlassCard } from '../components/GlassCard'
import { GeneBadge, MetaLabel } from '../components/ui'
import { ApplyToStudioButton } from '../components/studio/ApplyToStudioButton'
import { useLab } from '../lab/LabContext'
import {
  searchDiseasePathways,
  type ReactomePathwayHit,
} from '../services/pathwayApi'

const EXAMPLES = [
  'Alzheimer Disease',
  'Colorectal Cancer',
  'Parkinson Disease',
  'Glioblastoma',
  'Type 2 Diabetes Mellitus',
  'Breast Cancer',
]

/**
 * Dedicated sidebar workspace: Reactome disease → STRING interactome → Studio ODE.
 * Auto-picks the top-ranked pathway so you don't trial-and-error.
 */
export function PathwaysView() {
  const lab = useLab()
  const navigate = useNavigate()
  const [draft, setDraft] = useState('')
  const [hits, setHits] = useState<ReactomePathwayHit[]>([])
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<ReactomePathwayHit | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingNav, setPendingNav] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  /** When set, auto-build as soon as ranked hits arrive for this query. */
  const autoBuildFor = useRef<string | null>(null)

  const recommended = useMemo(() => hits[0] ?? null, [hits])

  const runDynamicRef = useRef(lab.runDynamicDisease)
  runDynamicRef.current = lab.runDynamicDisease

  // Debounced Reactome search — always auto-select the #1 ranked hit.
  useEffect(() => {
    const q = draft.trim()
    if (q.length < 2) {
      setHits([])
      setSelected(null)
      setSearching(false)
      return
    }
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    const t = window.setTimeout(() => {
      setSearching(true)
      setError(null)
      void searchDiseasePathways(q, { limit: 12, signal: ac.signal })
        .then((rows) => {
          if (ac.signal.aborted) return
          setHits(rows)
          const best = rows[0] ?? null
          setSelected(best)
          const wantAuto = autoBuildFor.current
          if (wantAuto && best && wantAuto.toLowerCase() === q.toLowerCase()) {
            autoBuildFor.current = null
            setPendingNav(true)
            runDynamicRef.current(best, { query: q })
          }
        })
        .catch((err) => {
          if (ac.signal.aborted) return
          setHits([])
          setSelected(null)
          setError(err instanceof Error ? err.message : 'Reactome search failed')
        })
        .finally(() => {
          if (!ac.signal.aborted) setSearching(false)
        })
    }, 280)
    return () => {
      window.clearTimeout(t)
      ac.abort()
    }
  }, [draft])

  // After Build & simulate finishes, open Studio so the canvas is obvious.
  useEffect(() => {
    if (!pendingNav || lab.busy) return
    setPendingNav(false)
    if (lab.graph) navigate('/studio')
  }, [pendingNav, lab.busy, lab.graph, navigate])

  const construct = (hit?: ReactomePathwayHit | null) => {
    const target = hit ?? selected ?? recommended
    const q = draft.trim()
    setError(null)
    if (!target) {
      if (!q) return
      setPendingNav(true)
      lab.runDynamicDisease(q)
      return
    }
    setSelected(target)
    setPendingNav(true)
    lab.runDynamicDisease(target, { query: q || target.name })
  }

  /** One-click from an example chip: search + immediately build the top match. */
  const quickBuild = (query: string) => {
    if (lab.busy) return
    autoBuildFor.current = query.trim()
    setSelected(null)
    setDraft(query)
  }

  const nNodes = lab.graph ? Object.keys(lab.graph.nodes).length : 0
  const nEdges = lab.graph?.edges?.length ?? 0
  const buildTarget = selected ?? recommended

  return (
    <div className="mx-auto flex h-full max-w-[88rem] flex-col gap-4 overflow-y-auto p-4">
      <div>
        <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
          Disease Pathways
        </h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Type a disease — we auto-pick the best Reactome pathway. Click Build (or an example)
          and go straight to Studio.
        </p>
      </div>

      <GlassCard className="space-y-3">
        <MetaLabel className="text-cyan-300/90">Disease / condition</MetaLabel>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!lab.busy) construct(buildTarget)
          }}
        >
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={draft}
              onChange={(e) => {
                autoBuildFor.current = null
                setDraft(e.target.value)
              }}
              placeholder="e.g. Alzheimer Disease, Colorectal Cancer…"
              disabled={lab.busy}
              spellCheck={false}
              className="w-full rounded-xl border border-slate-700 bg-slate-950/80 py-2.5 pl-10 pr-4 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-flux/50 disabled:opacity-50"
            />
          </div>
          <button
            type="submit"
            disabled={lab.busy || !draft.trim() || !lab.engineLive || searching}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-sm font-bold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-40"
          >
            {lab.busy || searching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Zap className="h-4 w-4" />
            )}
            Build
          </button>
        </form>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              disabled={lab.busy}
              onClick={() => quickBuild(ex)}
              title="Search and auto-build the best Reactome match"
              className="rounded-md border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-300 hover:border-cyan-flux/40 hover:text-cyan-100 disabled:opacity-40"
            >
              {ex}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-slate-600">
          Example chips auto-build the top match — no pathway shopping required.
        </p>
      </GlassCard>

      {recommended && !searching ? (
        <GlassCard className="space-y-2 border border-emerald-500/30 bg-emerald-950/20">
          <MetaLabel className="text-emerald-300/90">Recommended for you</MetaLabel>
          <p className="text-sm font-semibold text-slate-50">{recommended.name}</p>
          <p className="font-mono text-[10px] text-slate-500">
            {recommended.pathwayId}
            {recommended.matchHint ? ` · ${recommended.matchHint}` : ''}
          </p>
          <button
            type="button"
            disabled={lab.busy || !lab.engineLive}
            onClick={() => construct(recommended)}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/50 bg-emerald-500/20 px-4 py-2.5 text-sm font-bold text-emerald-50 hover:bg-emerald-500/30 disabled:opacity-40"
          >
            {lab.busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Network className="h-4 w-4" />
            )}
            {lab.busy ? 'Building…' : 'Build this pathway'}
          </button>
        </GlassCard>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <GlassCard className="min-h-[240px] space-y-2">
          <div className="flex items-center justify-between gap-2">
            <MetaLabel>Other Reactome options</MetaLabel>
            {searching ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-cyan-300">
                <Loader2 className="h-3 w-3 animate-spin" />
                Ranking…
              </span>
            ) : (
              <span className="text-[11px] text-slate-600">{hits.length} ranked</span>
            )}
          </div>

          {error ? (
            <p className="rounded-lg border border-coral-action/40 bg-coral-action/10 px-3 py-2 text-xs text-red-100">
              {error}
            </p>
          ) : null}

          {!searching && draft.trim().length >= 2 && hits.length === 0 && !error ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No human pathways matched “{draft.trim()}”.
            </p>
          ) : null}

          {draft.trim().length < 2 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              Type a disease — or click an example chip to auto-build.
            </p>
          ) : null}

          <ul className="max-h-[360px] space-y-1 overflow-y-auto">
            {hits.map((hit, idx) => {
              const on = selected?.pathwayId === hit.pathwayId
              const kindLabel =
                hit.matchKind === 'name'
                  ? 'Name match'
                  : hit.matchKind === 'alias'
                    ? 'Best related'
                    : hit.matchKind === 'text'
                      ? 'Mentions your term'
                      : 'Weak match'
              return (
                <li key={hit.pathwayId}>
                  <button
                    type="button"
                    disabled={lab.busy}
                    onClick={() => setSelected(hit)}
                    onDoubleClick={() => construct(hit)}
                    className={clsx(
                      'flex w-full flex-col gap-1 rounded-xl border px-3 py-2.5 text-left transition disabled:opacity-40',
                      on
                        ? 'border-cyan-flux/50 bg-cyan-950/40 text-cyan-50'
                        : 'border-slate-800 bg-slate-950/40 text-slate-200 hover:border-slate-600',
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      {idx === 0 ? (
                        <span className="rounded-md border border-emerald-500/50 bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-emerald-200">
                          #1 pick
                        </span>
                      ) : null}
                      <span className="text-[13px] font-semibold leading-snug">{hit.name}</span>
                      <span
                        className={clsx(
                          'rounded-md border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide',
                          hit.matchKind === 'name' || hit.matchKind === 'alias'
                            ? 'border-emerald-500/40 bg-emerald-950/50 text-emerald-200'
                            : hit.matchKind === 'text'
                              ? 'border-amber-500/40 bg-amber-950/40 text-amber-100'
                              : 'border-slate-700 text-slate-500',
                        )}
                      >
                        {kindLabel}
                      </span>
                    </div>
                    <span className="font-mono text-[10px] text-slate-500">
                      {hit.pathwayId}
                      {hit.isDisease ? ' · disease' : ''}
                    </span>
                    {hit.matchHint ? (
                      <span className="text-[11px] leading-snug text-slate-400">
                        {hit.matchHint}
                      </span>
                    ) : null}
                  </button>
                </li>
              )
            })}
          </ul>
          {hits.length > 1 ? (
            <p className="pt-1 text-[10px] leading-relaxed text-slate-600">
              Optional: click another row only if you want a different scaffold. Double-click builds
              immediately.
            </p>
          ) : null}
        </GlassCard>

        <div className="flex flex-col gap-4">
          <GlassCard className="space-y-3">
            <MetaLabel className="text-emerald-300/90">Status</MetaLabel>
            {lab.busy ? (
              <p className="inline-flex items-start gap-2 rounded-lg border border-amber-kinase/30 bg-amber-950/30 px-3 py-2 text-[11px] text-amber-100">
                <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
                {lab.statusStage ||
                  'Constructing dynamic interactome from Reactome & STRING-DB…'}
              </p>
            ) : buildTarget ? (
              <p className="text-[12px] text-slate-400">
                Ready to build{' '}
                <span className="font-semibold text-slate-200">{buildTarget.name}</span>
              </p>
            ) : (
              <p className="text-[12px] text-slate-500">Waiting for a disease query…</p>
            )}
            {!lab.engineLive ? (
              <p className="text-[11px] text-red-200">API offline — start uvicorn on :8001</p>
            ) : null}
          </GlassCard>

          <GlassCard className="space-y-2">
            <MetaLabel>Active scenario</MetaLabel>
            <div className="flex flex-wrap items-center gap-1.5">
              {lab.profileId ? <GeneBadge name={lab.profileId} tone="violet" /> : null}
              <span className="text-[11px] text-slate-500">
                {nNodes} nodes · {nEdges} edges
              </span>
            </div>
            <p className="truncate text-[12px] text-slate-300" title={lab.controls.conditionQuery}>
              {lab.controls.conditionQuery || '—'}
            </p>
            <button
              type="button"
              onClick={() => navigate('/studio')}
              className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-semibold text-cyan-300 hover:text-cyan-200"
            >
              <FlaskConical className="h-3.5 w-3.5" />
              Open Simulation Studio
            </button>
            <div className="pt-1">
              <ApplyToStudioButton
                label="Apply → Studio"
                disabled={!lab.graph || lab.busy}
                busy={lab.busy}
              />
            </div>
          </GlassCard>

          <GlassCard className="space-y-2">
            <MetaLabel>Pipeline</MetaLabel>
            <ol className="space-y-1.5 text-[11px] text-slate-400">
              <li className="flex items-center gap-2">
                <Search className="h-3.5 w-3.5 text-cyan-flux" />
                Reactome pathway search + rank
              </li>
              <li className="flex items-center gap-2">
                <GitBranch className="h-3.5 w-3.5 text-violet-300" />
                Participating gene symbols
              </li>
              <li className="flex items-center gap-2">
                <Network className="h-3.5 w-3.5 text-emerald-300" />
                STRING-DB interaction network
              </li>
              <li className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-amber-200" />
                Hill-cube ODE · Studio canvas
              </li>
            </ol>
          </GlassCard>
        </div>
      </div>
    </div>
  )
}
