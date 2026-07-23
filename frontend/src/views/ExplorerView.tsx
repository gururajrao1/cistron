import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Network, Play, Timer } from 'lucide-react'
import { GlassCard } from '../components/GlassCard'
import { ProvenanceBadge, SOURCE_COLORS } from '../components/ProvenanceBadge'
import { fetchKnowledgeSources, fetchSourceSituations } from '../api/client'
import { useLab } from '../lab/LabContext'
import { DEFAULT_SELECTED_SOURCES } from '../api/types'

export function ExplorerView() {
  const lab = useLab()
  const edges = lab.graph?.edges ?? []
  const nodes = lab.graph?.nodes ?? {}
  const provenance = (lab.graph?.provenance ?? {}) as Record<string, unknown>
  const sourceStatus = (provenance.source_status ?? {}) as Record<string, string>
  const [situationId, setSituationId] = useState('')

  const sourcesQ = useQuery({
    queryKey: ['knowledge-sources'],
    queryFn: fetchKnowledgeSources,
    staleTime: 60_000,
  })

  const situationsQ = useQuery({
    queryKey: ['source-situations', lab.controls.selectedSources.join(',')],
    queryFn: () => fetchSourceSituations(lab.controls.selectedSources),
    staleTime: 30_000,
  })

  const catalogue =
    sourcesQ.data?.length
      ? sourcesQ.data
      : DEFAULT_SELECTED_SOURCES.map((id) => ({ id, label: id }))

  const situations = situationsQ.data ?? []

  const situationsBySource = useMemo(() => {
    const groups: Record<string, typeof situations> = {}
    for (const s of situations) {
      ;(groups[s.source] ??= []).push(s)
    }
    return groups
  }, [situations])

  const selectedSituation = situations.find((s) => s.id === situationId)

  const toggleSource = (id: string) => {
    const cur = lab.controls.selectedSources
    if (id === 'local') return
    const next = cur.includes(id) ? cur.filter((s) => s !== id) : [...cur, id]
    if (!next.includes('local')) next.unshift('local')
    lab.patchControls({ selectedSources: next })
    setSituationId('')
  }

  const applySituation = (id: string) => {
    setSituationId(id)
    const sit = situations.find((s) => s.id === id)
    if (!sit) return
    const sources = lab.controls.selectedSources.includes(sit.source)
      ? lab.controls.selectedSources
      : [...lab.controls.selectedSources, sit.source]
    lab.patchControls({
      conditionQuery: sit.query,
      selectedSources: sources.includes('local') ? sources : ['local', ...sources],
    })
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      <div>
        <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
          Dynamic Query & Network Builder
        </h1>
        <p className="text-sm text-slate-500">
          Multi-source knowledge search · consensus fusion · τ parameterization
        </p>
      </div>

      <GlassCard title="Knowledge Sources" hint="Toggle databases included in resolve_multisource_network">
        <div className="flex flex-wrap gap-2">
          {catalogue.map((s) => {
            const on = lab.controls.selectedSources.includes(s.id)
            const status = sourceStatus[s.id]
            return (
              <button
                key={s.id}
                type="button"
                disabled={s.id === 'local'}
                onClick={() => toggleSource(s.id)}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                  on
                    ? SOURCE_COLORS[s.id] ??
                      'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                    : 'border-slate-800 bg-slate-950/50 text-slate-600'
                }`}
                title={status ? `Last status: ${status}` : s.label}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    on ? 'bg-emerald-active shadow-[0_0_6px_#10B981]' : 'bg-slate-700'
                  }`}
                />
                {s.label}
              </button>
            )
          })}
        </div>
        {Object.keys(sourceStatus).length ? (
          <p className="mt-3 text-[0.7rem] text-slate-500">
            Last resolve:{' '}
            {Object.entries(sourceStatus)
              .map(([k, v]) => `${k}=${v}`)
              .join(' · ')}
          </p>
        ) : null}

        <div className="mt-4 border-t border-slate-800/80 pt-4">
          <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">
            Situation by source
          </label>
          <p className="mb-2 text-[0.7rem] text-slate-500">
            Pick a curated pathway or disease context from the enabled databases above.
          </p>
          <select
            className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-100"
            value={situationId}
            disabled={situationsQ.isLoading || situations.length === 0}
            onChange={(e) => applySituation(e.target.value)}
          >
            <option value="">
              {situationsQ.isLoading
                ? 'Loading situations…'
                : situations.length
                  ? 'Select a situation…'
                  : 'Enable a source to see situations'}
            </option>
            {Object.entries(situationsBySource).map(([source, items]) => (
              <optgroup key={source} label={source.toUpperCase()}>
                {items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                    {s.pathway_id ? ` (${s.pathway_id})` : ''}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {selectedSituation?.description ? (
            <p className="mt-2 flex flex-wrap items-center gap-2 text-xs leading-relaxed text-slate-400">
              <ProvenanceBadge source={selectedSituation.source} />
              <span>{selectedSituation.description}</span>
            </p>
          ) : null}
        </div>
      </GlassCard>

      <GlassCard title="Condition Resolver" hint="Free-text → multi-source CausalActivityGraph">
        <div className="mb-3 flex flex-wrap gap-2">
          {(lab.suggestions.length
            ? lab.suggestions
            : [
                { label: 'Hypoxia', query: 'Hypoxia-induced angiogenesis' },
                { label: 'Glioblastoma', query: 'Glioblastoma EGFR resistance' },
              ]
          ).map((s) => (
            <button
              key={s.query}
              type="button"
              disabled={lab.busy}
              onClick={() => {
                setSituationId('')
                lab.runQuery(s.query)
              }}
              className="rounded-full border border-slate-700 bg-slate-900/80 px-3 py-1 text-xs text-slate-300 hover:border-emerald-500/40 hover:text-emerald-200 disabled:opacity-50"
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm"
            value={lab.controls.conditionQuery}
            onChange={(e) => {
              setSituationId('')
              lab.patchControls({ conditionQuery: e.target.value })
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') lab.runQuery(lab.controls.conditionQuery)
            }}
            placeholder="e.g. Alzheimer's amyloid stress"
          />
          <button
            type="button"
            disabled={!lab.engineLive || lab.busy}
            onClick={() => lab.runSimulation()}
            className="inline-flex items-center gap-2 rounded-xl bg-coral-action px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
          >
            <Play className="h-4 w-4" /> Resolve
          </button>
        </div>
      </GlassCard>

      <div className="grid gap-4 md:grid-cols-2">
        <GlassCard title="Resolved Topology" hint="Nodes · edges · provenance badges">
          {!lab.graph ? (
            <p className="text-sm text-slate-500">No network resolved yet.</p>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap gap-3 text-xs text-slate-400">
                <span className="inline-flex items-center gap-1.5">
                  <Network className="h-3.5 w-3.5 text-emerald-active" />
                  {Object.keys(nodes).length} nodes · {edges.length} edges
                </span>
                <span className="font-mono text-slate-500">{lab.graph.id}</span>
              </div>
              <div className="max-h-72 overflow-auto rounded-xl border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-950 text-slate-500">
                    <tr>
                      <th className="px-2 py-2">Source</th>
                      <th className="px-2 py-2">Target</th>
                      <th className="px-2 py-2">Sign</th>
                      <th className="px-2 py-2">Provenance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {edges.map((e, i) => (
                      <tr key={`${e.source}-${e.target}-${i}`} className="border-t border-slate-800/80">
                        <td className="px-2 py-1.5 font-semibold text-slate-200">{e.source}</td>
                        <td className="px-2 py-1.5 text-slate-300">{e.target}</td>
                        <td className="px-2 py-1.5 font-mono text-emerald-300">
                          {e.sign > 0 ? '+1' : '−1'}
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="flex flex-wrap gap-1">
                            {(e.sources?.length
                              ? e.sources
                              : e.datasets?.length
                                ? e.datasets
                                : ['local']
                            ).map((s) => (
                              <ProvenanceBadge key={s} source={s} />
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </GlassCard>

        <GlassCard title="Kinetic Parameterizer" hint="τ enzymatic 1 min · transcriptional 120 min">
          {!lab.graph ? (
            <p className="text-sm text-slate-500">Resolve a network to edit latencies.</p>
          ) : (
            <div className="max-h-72 space-y-2 overflow-auto">
              {Object.entries(nodes)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([sym, n]) => (
                  <div
                    key={sym}
                    className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2 text-xs"
                  >
                    <div>
                      <div className="font-semibold text-slate-200">{sym}</div>
                      <div className="text-slate-500">
                        y₀={Number(n.initial_concentration ?? 0.35).toFixed(2)} · w=
                        {Number(n.activity_weight ?? 1).toFixed(2)}
                      </div>
                    </div>
                    <div className="inline-flex items-center gap-1.5 font-mono text-emerald-300">
                      <Timer className="h-3.5 w-3.5" />τ={Number(n.tau_min).toFixed(0)} min
                    </div>
                  </div>
                ))}
            </div>
          )}

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-400">Driver</label>
              <select
                className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-2 py-2 text-sm"
                value={lab.controls.sourceNode}
                onChange={(e) => lab.patchControls({ sourceNode: e.target.value })}
              >
                {(lab.nodes.length ? lab.nodes : [lab.controls.sourceNode]).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Readout</label>
              <select
                className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-2 py-2 text-sm"
                value={lab.controls.targetNode}
                onChange={(e) => lab.patchControls({ targetNode: e.target.value })}
              >
                {(lab.nodes.length ? lab.nodes : [lab.controls.targetNode]).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  )
}
