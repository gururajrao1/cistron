import { Play } from 'lucide-react'
import { TopologyPanel } from '../components/TopologyPanel'
import { useLab } from '../lab/LabContext'

export function CombinationsView() {
  const lab = useLab()
  const topo = lab.topologicalAnalysis
  const hasSl = (topo?.synthetic_lethal_pairs?.length ?? 0) > 0

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
            Combination Therapy & Synthetic Lethality
          </h1>
          <p className="text-sm text-slate-500">
            Studio stays fast (centrality + loops). Run a deep pairwise KO scan here.
          </p>
        </div>
        <button
          type="button"
          disabled={!lab.engineLive || lab.busy}
          onClick={() => lab.runSimulation({ includeSyntheticLethality: true })}
          className="inline-flex items-center gap-2 rounded-xl bg-coral-action px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
        >
          <Play className="h-4 w-4" />
          {hasSl ? 'Re-scan SL pairs' : 'Deep SL scan'}
        </button>
      </div>

      <TopologyPanel topo={topo} />

      {topo ? (
        <p className="font-mono text-[0.65rem] text-slate-600">
          n={String(topo.metadata?.n_nodes ?? '—')} · edges=
          {String(topo.metadata?.n_edges ?? '—')} · loops={topo.feedback_loops.length} ·
          bottlenecks={topo.bottlenecks.length} · SL={topo.synthetic_lethal_pairs.length} ·{' '}
          {topo.elapsed_ms.toFixed(0)} ms
        </p>
      ) : null}
    </div>
  )
}
