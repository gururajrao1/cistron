import { memo, useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  Ban,
  BookOpen,
  Box,
  Crosshair,
  ExternalLink,
  GitBranch,
  Lightbulb,
  Loader2,
  Network,
  Shuffle,
  X,
} from 'lucide-react'
import { GlassCard } from './GlassCard'
import { GeneBadge, MetaLabel, SparkBar } from './ui'
import { fetchProteinMeta } from '../api/client'
import type {
  EdgeFlowImpact,
  NodeFeatureVector,
  NodeShapAttribution,
  PresetDetail,
  ProteinMeta,
  ScrubberPayload,
  XAIAttributionResult,
} from '../api/types'
import { ProvenanceBadge } from './ProvenanceBadge'
import { useLab } from '../lab/LabContext'
import { useNavigate } from 'react-router-dom'

/** Map scrubber minutes → discrete trajectory keyframe index. */
function frameIndexAt(payload: ScrubberPayload | null, scrubT: number): number {
  if (!payload?.time_steps.length) return 0
  const trajLen =
    (payload.nodes && Object.values(payload.nodes)[0]?.length) ||
    payload.time_steps.length
  if (trajLen <= 1) return 0
  const tEnd = payload.time_steps[payload.time_steps.length - 1] ?? 60
  if (tEnd <= 0) return 0
  return Math.max(0, Math.min(trajLen - 1, Math.round((scrubT / tEnd) * (trajLen - 1))))
}

function yAt(
  payload: ScrubberPayload | null,
  node: string,
  frame: number,
): number {
  return payload?.nodes[node]?.[frame] ?? 0
}

/** Instantaneous mass-action flux Fᵢⱼ(t) = wᵢⱼ · y_source(t) · (1 − y_target(t)). */
function instantaneousFlux(
  payload: ScrubberPayload | null,
  source: string,
  target: string,
  frame: number,
  w: number,
): number {
  const ys = yAt(payload, source, frame)
  const yt = yAt(payload, target, frame)
  return w * ys * (1 - yt)
}

function edgeWeight(evidence: number | null | undefined): number {
  return typeof evidence === 'number' && Number.isFinite(evidence) ? Math.max(0, evidence) : 1
}

/** Isolated so scrubbing only recomputes this card, not SHAP / identifiers. */
const LocalFluxesCard = memo(function LocalFluxesCard({
  nodeId,
  graph,
  payload,
  xai,
}: {
  nodeId: string
  graph: PresetDetail | null
  payload: ScrubberPayload | null
  xai?: XAIAttributionResult | null
}) {
  const { scrubT } = useLab()
  const frame = useMemo(() => frameIndexAt(payload, scrubT), [payload, scrubT])
  const scrubMin = Math.round(scrubT)

  const { upstream, downstream } = useMemo(() => {
    const edges = graph?.edges ?? []
    const impacts = xai?.edge_flow_impacts

    const upstream = edges
      .filter((e) => e.target === nodeId)
      .map((e) => {
        const key = `${e.source}->${e.target}`
        const w = edgeWeight(e.evidence_score)
        const flux = instantaneousFlux(payload, e.source, e.target, frame, w)
        const impact: EdgeFlowImpact | undefined = impacts?.find((f) => f.edge_key === key)
        return { source: e.source, sign: e.sign, flux, alpha: impact?.alpha ?? 0 }
      })

    const downstream = edges
      .filter((e) => e.source === nodeId)
      .map((e) => {
        const key = `${e.source}->${e.target}`
        const w = edgeWeight(e.evidence_score)
        const flux = instantaneousFlux(payload, e.source, e.target, frame, w)
        const impact = impacts?.find((f) => f.edge_key === key)
        return { target: e.target, sign: e.sign, flux, alpha: impact?.alpha ?? 0 }
      })

    return { upstream, downstream }
  }, [graph, payload, nodeId, frame, xai])

  return (
    <GlassCard
      title="Local Fluxes"
      hint={`Fᵢⱼ(t)=w·yₛ(t)·(1−yₜ(t)) · frame ${frame} · t=${scrubMin} min`}
    >
      <MetaLabel className="mb-1.5">Upstream → {nodeId}</MetaLabel>
      {upstream.length ? (
        <ul className="mb-2.5 space-y-1">
          {upstream.map((u) => (
            <li
              key={u.source}
              className="flex items-center justify-between gap-2 rounded-lg border border-slate-800/80 bg-obsidian/50 px-2 py-1.5 text-[11px]"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <GeneBadge name={u.source} tone={u.sign < 0 ? 'coral' : 'cyan'} />
                <span className={u.sign < 0 ? 'text-coral-action' : 'text-cyan-flux'}>
                  {u.sign < 0 ? '⊣' : '→'}
                </span>
              </span>
              <span className="lab-mono shrink-0 text-emerald-300/90">
                F({scrubMin}m) = {u.flux.toFixed(3)} · α={u.alpha.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-2.5 text-[11px] text-slate-500">No upstream edges.</p>
      )}
      <MetaLabel className="mb-1.5">{nodeId} → Downstream</MetaLabel>
      {downstream.length ? (
        <ul className="space-y-1">
          {downstream.map((d) => (
            <li
              key={d.target}
              className="flex items-center justify-between gap-2 rounded-lg border border-slate-800/80 bg-obsidian/50 px-2 py-1.5 text-[11px]"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className={d.sign < 0 ? 'text-coral-action' : 'text-cyan-flux'}>
                  {d.sign < 0 ? '⊣' : '→'}
                </span>
                <GeneBadge name={d.target} tone={d.sign < 0 ? 'coral' : 'emerald'} />
              </span>
              <span className="lab-mono shrink-0 text-emerald-300/90">
                F({scrubMin}m) = {d.flux.toFixed(3)} · α={d.alpha.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[11px] text-slate-500">No downstream edges.</p>
      )}
    </GlassCard>
  )
})

export function NodeBiophysicsInspector({
  nodeId,
  graph,
  payload,
  vector,
  xai,
  onClose,
  onKnockout,
  onClamp,
}: {
  nodeId: string
  graph: PresetDetail | null
  payload: ScrubberPayload | null
  vector?: NodeFeatureVector | null
  xai?: XAIAttributionResult | null
  onClose: () => void
  onKnockout: (node: string) => void
  onClamp: (node: string) => void
}) {
  const activeNode = nodeId
  const navigate = useNavigate()
  const lab = useLab()

  const neighborCtx = useMemo(() => {
    const edges = graph?.edges ?? []
    const upstream = edges.filter((e) => e.target === activeNode).map((e) => e.source)
    const downstream = edges.filter((e) => e.source === activeNode).map((e) => e.target)
    return { upstream, downstream }
  }, [graph, activeNode])

  const [meta, setMeta] = useState<ProteinMeta | null>(null)
  const [loadingMeta, setLoadingMeta] = useState(false)

  const upstreamKey = neighborCtx.upstream.join(',')
  const downstreamKey = neighborCtx.downstream.join(',')

  useEffect(() => {
    let cancelled = false
    setLoadingMeta(true)
    const upstream = upstreamKey ? upstreamKey.split(',') : []
    const downstream = downstreamKey ? downstreamKey.split(',') : []
    fetchProteinMeta(activeNode, {
      condition: lab.controls.conditionQuery,
      upstream,
      downstream,
      delta_y: vector?.delta_y ?? null,
    })
      .then((m) => {
        if (!cancelled) setMeta(m)
      })
      .catch(() => {
        if (!cancelled)
          setMeta({
            gene_symbol: activeNode,
            localization: 'Unknown',
            plain_english: `${activeNode} is a node in your virtual cell network. Connect the API to load a plain-language UniProt explanation.`,
            why_it_matters:
              'When the API is live we explain what this protein does, why disease biologists care, and how it sits in your current pathway.',
            in_this_network:
              upstream.length || downstream.length
                ? `Local links: ← ${upstream.slice(0, 4).join(', ') || '—'} · → ${downstream.slice(0, 4).join(', ') || '—'}`
                : 'No local edges found for this node yet.',
          })
      })
      .finally(() => {
        if (!cancelled) setLoadingMeta(false)
      })
    return () => {
      cancelled = true
    }
    // Intentionally omit vector.delta_y — scrubbing must not re-hit UniProt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeNode, lab.controls.conditionQuery, upstreamKey, downstreamKey])

  const shap: NodeShapAttribution | undefined = xai?.node_attributions.find(
    (a) => a.node === activeNode,
  )

  const featureRows = [
    { key: 'y₀', label: 'y_init', value: vector?.y_init ?? 0, tone: 'cyan' as const },
    { key: 'y₆₀', label: 'y_final', value: vector?.y_final ?? 0, tone: 'emerald' as const },
    {
      key: 'Δy',
      label: 'delta_y',
      value: Math.abs(vector?.delta_y ?? 0),
      raw: vector?.delta_y ?? 0,
      tone: (vector && vector.delta_y < 0 ? 'coral' : 'emerald') as 'coral' | 'emerald',
    },
    { key: 'wᵢ', label: 'capacity', value: vector?.capacity ?? 1, tone: 'amber' as const },
    {
      key: 'KO',
      label: 'is_knocked_out',
      value: vector?.is_knocked_out ? 1 : 0,
      tone: 'violet' as const,
    },
  ]

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-slate-800/80 bg-obsidian-panel/95 shadow-2xl backdrop-blur-xl">
      <div className="flex items-start justify-between gap-3 border-b border-slate-800/80 px-4 py-3">
        <div className="min-w-0">
          <MetaLabel className="text-emerald-400/80">Node Biophysics Inspector</MetaLabel>
          <div className="mt-1 flex items-center gap-2">
            <h2 className="text-lg font-extrabold tracking-tight text-slate-50">{activeNode}</h2>
            <GeneBadge name={activeNode} tone="emerald" />
          </div>
          {meta?.full_name ? (
            <p className="mt-0.5 truncate text-[11px] text-slate-400">{meta.full_name}</p>
          ) : loadingMeta ? (
            <p className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500">
              <Loader2 className="h-3 w-3 animate-spin" /> Resolving MyGene · UniProt…
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-slate-700/80 p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          aria-label="Close inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-2.5 overflow-y-auto px-4 py-3">
        <GlassCard
          title="What is this protein?"
          hint="MyGene · UniProt grounded · optional HF LLM polish"
        >
          {loadingMeta && !meta?.plain_english ? (
            <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Looking up biology…
            </p>
          ) : (
            <div className="space-y-2.5 text-[12px] leading-relaxed text-slate-200">
              {(meta?.sources_used?.length || meta?.narrative_mode) && (
                <div className="flex flex-wrap gap-1">
                  {(meta?.sources_used ?? []).map((s) => (
                    <span
                      key={s}
                      className="rounded-full border border-vcl-border bg-vcl-surface px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-vcl-muted"
                    >
                      {s.replace(/_/g, ' ')}
                    </span>
                  ))}
                      {meta?.narrative_mode ? (
                    <span
                      className={
                        meta.narrative_mode === 'hf_llm' ||
                        meta.narrative_mode.includes('biogpt') ||
                        meta.narrative_mode === 'cached' ||
                        meta.narrative_mode === 'custom_llm'
                          ? 'rounded-full border border-violet-hub/40 bg-violet-950/50 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-violet-200'
                          : 'rounded-full border border-emerald-500/30 bg-emerald-950/40 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-200/90'
                      }
                    >
                      {meta.narrative_mode === 'hf_llm' ||
                      meta.narrative_mode.includes('biogpt') ||
                      meta.narrative_mode === 'cached'
                        ? 'HF LLM narrative'
                        : meta.narrative_mode === 'custom_llm'
                          ? 'Custom LLM'
                          : meta.narrative_mode === 'template_curated'
                            ? 'Curated explainer'
                            : 'Fact template'}
                    </span>
                  ) : null}
                </div>
              )}
              <p>{meta?.plain_english || `${activeNode} is a network node in this experiment.`}</p>
              {meta?.analogy ? (
                <p className="flex gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-2.5 py-2 text-[11px] text-amber-50/95">
                  <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                  <span>
                    <span className="font-semibold text-amber-200">Analogy — </span>
                    {meta.analogy}
                  </span>
                </p>
              ) : null}
              <div>
                <MetaLabel className="mb-1 flex items-center gap-1">
                  <BookOpen className="h-3 w-3" /> Why it matters
                </MetaLabel>
                <p className="text-[11px] text-slate-300">
                  {meta?.why_it_matters ||
                    'This protein participates in signaling that can change disease-relevant cell behavior.'}
                </p>
              </div>
              <div>
                <MetaLabel className="mb-1 flex items-center gap-1">
                  <Network className="h-3 w-3" /> In this network
                </MetaLabel>
                <p className="text-[11px] text-slate-300">
                  {meta?.in_this_network ||
                    'Open a built pathway graph to see who talks to whom.'}
                </p>
              </div>
              {meta?.diseases?.length ? (
                <div className="flex flex-wrap gap-1">
                  {meta.diseases.map((d) => (
                    <span
                      key={d}
                      className="rounded-full border border-rose-inhib/30 bg-rose-950/40 px-2 py-0.5 text-[10px] font-medium text-rose-100"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2 pt-0.5">
                {meta?.uniprot_url ? (
                  <a
                    href={meta.uniprot_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-vcl-border px-2 py-1 text-[10px] font-semibold text-vcl-link hover:bg-vcl-raised"
                  >
                    UniProt <ExternalLink className="h-3 w-3" />
                  </a>
                ) : null}
                {meta?.entrez_url ? (
                  <a
                    href={meta.entrez_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-vcl-border px-2 py-1 text-[10px] font-semibold text-vcl-link hover:bg-vcl-raised"
                  >
                    NCBI Gene <ExternalLink className="h-3 w-3" />
                  </a>
                ) : null}
                {meta?.alphafold_url ? (
                  <a
                    href={meta.alphafold_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-vcl-border px-2 py-1 text-[10px] font-semibold text-vcl-link hover:bg-vcl-raised"
                  >
                    AlphaFold <ExternalLink className="h-3 w-3" />
                  </a>
                ) : null}
              </div>
            </div>
          )}
        </GlassCard>

        {meta?.disease_impact?.overview ? (
          <GlassCard
            title="If this protein changes…"
            hint={
              lab.controls.conditionQuery
                ? `Disease path: ${lab.controls.conditionQuery}`
                : 'Works for any Pathways disease — not just hypoxia'
            }
          >
            <div className="space-y-2.5 text-[12px] leading-relaxed text-slate-200">
              {meta.disease_impact.mode &&
              (meta.disease_impact.mode === 'hf_llm' ||
                meta.disease_impact.mode === 'cached' ||
                meta.disease_impact.mode === 'custom_llm') ? (
                <span className="inline-flex rounded-full border border-violet-hub/40 bg-violet-950/50 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-violet-200">
                  {meta.disease_impact.mode === 'custom_llm'
                    ? 'Custom LLM impact'
                    : 'HF LLM impact'}
                </span>
              ) : (
                <span className="inline-flex rounded-full border border-emerald-500/30 bg-emerald-950/40 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-200/90">
                  Network template
                </span>
              )}
              <p className="text-[11px] text-slate-300">{meta.disease_impact.overview}</p>
              {meta.disease_impact.if_activity_up ? (
                <div>
                  <MetaLabel className="mb-1 flex items-center gap-1">
                    <ArrowUp className="h-3 w-3 text-emerald-400" /> Activity up
                  </MetaLabel>
                  <p className="text-[11px] text-slate-300">
                    {meta.disease_impact.if_activity_up}
                  </p>
                </div>
              ) : null}
              {meta.disease_impact.if_activity_down ? (
                <div>
                  <MetaLabel className="mb-1 flex items-center gap-1">
                    <ArrowDown className="h-3 w-3 text-rose-300" /> Activity down / KO
                  </MetaLabel>
                  <p className="text-[11px] text-slate-300">
                    {meta.disease_impact.if_activity_down}
                  </p>
                </div>
              ) : null}
              {meta.disease_impact.structure_or_interaction ? (
                <div>
                  <MetaLabel className="mb-1 flex items-center gap-1">
                    <Shuffle className="h-3 w-3 text-amber-300" /> Structure / interactions
                  </MetaLabel>
                  <p className="text-[11px] text-slate-300">
                    {meta.disease_impact.structure_or_interaction}
                  </p>
                </div>
              ) : null}
            </div>
          </GlassCard>
        ) : null}

        <GlassCard title="Identifiers" hint="Gene · UniProt · localization · provenance">
          <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1.5 text-[12px]">
            <dt className="lab-meta !normal-case !tracking-normal text-slate-500">Gene</dt>
            <dd>
              <GeneBadge name={activeNode} />
            </dd>
            <dt className="lab-meta !normal-case !tracking-normal text-slate-500">UniProt</dt>
            <dd className="lab-mono text-emerald-300">{meta?.uniprot_id ?? '—'}</dd>
            <dt className="lab-meta !normal-case !tracking-normal text-slate-500">Locale</dt>
            <dd className="text-slate-200">{meta?.localization ?? '—'}</dd>
            {meta?.function ? (
              <>
                <dt className="lab-meta !normal-case !tracking-normal text-slate-500">Function</dt>
                <dd className="text-[11px] leading-relaxed text-slate-300">{meta.function}</dd>
              </>
            ) : null}
            <dt className="lab-meta !normal-case !tracking-normal text-slate-500">Sources</dt>
            <dd className="flex flex-wrap gap-1">
              {(() => {
                const nodeMeta = graph?.nodes?.[activeNode]?.metadata ?? {}
                const badges = new Set<string>()
                const prov = nodeMeta.provenance as Record<string, unknown> | undefined
                if (prov?.source) badges.add(String(prov.source))
                if (nodeMeta.source) badges.add(String(nodeMeta.source))
                for (const e of graph?.edges ?? []) {
                  if (e.source === activeNode || e.target === activeNode) {
                    for (const s of e.sources ?? e.datasets ?? []) badges.add(s)
                  }
                }
                if (!badges.size) badges.add('local')
                return Array.from(badges).map((s) => <ProvenanceBadge key={s} source={s} />)
              })()}
            </dd>
          </dl>
        </GlassCard>

        <GlassCard title="5D Feature Vector" hint="y₀ · y₆₀ · Δy · wᵢ · KO · live sparkline">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="lab-meta text-slate-500">
                <th className="pb-1.5 font-semibold">Dim</th>
                <th className="pb-1.5 font-semibold">Value</th>
                <th className="pb-1.5 font-semibold">Level</th>
              </tr>
            </thead>
            <tbody>
              {featureRows.map((row) => (
                <tr key={row.key} className="border-t border-slate-800/70">
                  <td className="py-1.5 font-mono text-slate-300">{row.key}</td>
                  <td className="lab-mono py-1.5 text-slate-100">
                    {'raw' in row && typeof row.raw === 'number'
                      ? `${row.raw >= 0 ? '+' : ''}${row.raw.toFixed(3)}`
                      : row.key === 'KO'
                        ? vector?.is_knocked_out
                          ? '1'
                          : '0'
                        : row.value.toFixed(3)}
                  </td>
                  <td className="py-1.5">
                    <SparkBar value={row.value} tone={row.tone} className="max-w-[7rem]" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shap ? (
            <div className="mt-2 flex items-center justify-between rounded-lg border border-violet-hub/25 bg-violet-950/30 px-2.5 py-1.5 text-[11px]">
              <span className="lab-meta text-cyan-flux/80">Node importance</span>
              <span className="lab-mono text-cyan-100">
                #{shap.rank} · {shap.importance >= 0 ? '+' : ''}
                {shap.importance.toFixed(3)}
              </span>
            </div>
          ) : null}
          {shap?.feature_attributions?.length ? (
            <div className="mt-2.5 space-y-1">
              <MetaLabel>Feature attributions</MetaLabel>
              {shap.feature_attributions.map((f) => (
                <div key={f.feature_name} className="flex items-center gap-2 text-[11px]">
                  <span className="w-24 shrink-0 truncate font-mono text-slate-400">
                    {f.feature_name}
                  </span>
                  <SparkBar
                    value={Math.abs(f.attribution)}
                    max={0.5}
                    tone={f.attribution >= 0 ? 'emerald' : 'coral'}
                    className="flex-1"
                  />
                  <span className="lab-mono w-12 text-right text-slate-300">
                    {f.attribution.toFixed(3)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </GlassCard>

        <LocalFluxesCard
          nodeId={activeNode}
          graph={graph}
          payload={payload}
          xai={xai}
        />

        <GlassCard title="Quick Actions" hint="Instant virtual perturbations · 3D structure">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onKnockout(activeNode)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-coral-action/40 bg-coral-action/10 px-3 py-2 text-[11px] font-semibold text-red-200 hover:bg-coral-action/20"
            >
              <Ban className="h-3.5 w-3.5" />
              Knockout (wᵢ=0)
            </button>
            <button
              type="button"
              onClick={() => onClamp(activeNode)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/20"
            >
              <Crosshair className="h-3.5 w-3.5" />
              Clamp expression
            </button>
            <button
              type="button"
              onClick={() =>
                navigate(`/biophysics?symbol=${encodeURIComponent(activeNode)}`)
              }
              className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-flux/40 bg-cyan-950/40 px-3 py-2 text-[11px] font-semibold text-cyan-100 shadow-[0_0_14px_rgba(6,182,212,0.15)] hover:bg-cyan-900/40"
            >
              <Box className="h-3.5 w-3.5" />
              Open 3D Structure
            </button>
            <button
              type="button"
              onClick={() => {
                try {
                  sessionStorage.setItem('cistron.combo.focus', activeNode)
                } catch {
                  /* ignore */
                }
                navigate('/combinations')
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-violet-hub/40 bg-violet-950/40 px-3 py-2 text-[11px] font-semibold text-violet-100 hover:bg-violet-900/40"
            >
              <GitBranch className="h-3.5 w-3.5" />
              Add to Combos
            </button>
          </div>
        </GlassCard>
      </div>
    </div>
  )
}
