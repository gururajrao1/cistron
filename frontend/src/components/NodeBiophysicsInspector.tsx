import { memo, useEffect, useMemo, useState } from 'react'
import { Ban, Crosshair, Loader2, X } from 'lucide-react'
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

  const [meta, setMeta] = useState<ProteinMeta | null>(null)
  const [loadingMeta, setLoadingMeta] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoadingMeta(true)
    fetchProteinMeta(activeNode)
      .then((m) => {
        if (!cancelled) setMeta(m)
      })
      .catch(() => {
        if (!cancelled) setMeta({ gene_symbol: activeNode, localization: 'Unknown' })
      })
      .finally(() => {
        if (!cancelled) setLoadingMeta(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeNode])

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
              <Loader2 className="h-3 w-3 animate-spin" /> Resolving UniProt…
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
              <span className="lab-meta text-violet-300/80">SHAP</span>
              <span className="lab-mono text-violet-200">
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

        <GlassCard title="Quick Actions" hint="Instant virtual perturbations">
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
          </div>
        </GlassCard>
      </div>
    </div>
  )
}
