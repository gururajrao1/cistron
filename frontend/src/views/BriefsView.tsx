import { Download, FileJson, FileText } from 'lucide-react'
import { GlassCard } from '../components/GlassCard'
import { useLab } from '../lab/LabContext'

function downloadBlob(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function BriefsView() {
  const lab = useLab()
  const brief = lab.reason?.brief ?? ''
  const scientist = lab.scientist?.brief ?? ''
  const paths = lab.reason?.context.extracted_paths ?? []

  const exportJson = () => {
    const payload = {
      query: lab.controls.conditionQuery,
      profile_id: lab.profileId,
      simulation_id: lab.payload?.simulation_id,
      elapsed_ms: lab.latencyMs,
      causal_brief: lab.reason,
      scientist_reasoning: lab.scientist,
      xai_attributions: lab.xai,
      prioritization: {
        master_regulators: lab.prioritization?.master_regulators ?? [],
        attention_matrix: lab.prioritization?.attention_matrix ?? {},
      },
      graph: {
        id: lab.graph?.id,
        n_nodes: lab.graph ? Object.keys(lab.graph.nodes).length : 0,
        n_edges: lab.graph?.edges.length ?? 0,
      },
      controls: lab.controls,
      exported_at: new Date().toISOString(),
    }
    downloadBlob(
      `voidsignal_${lab.profileId}_${Date.now()}.json`,
      JSON.stringify(payload, null, 2),
      'application/json',
    )
  }

  const exportMarkdown = () => {
    const md = [
      `# VoidSignal Research Brief`,
      ``,
      `**Scenario:** ${lab.controls.conditionQuery}`,
      `**Profile:** ${lab.profileId}`,
      `**Simulation:** ${lab.payload?.simulation_id ?? '—'}`,
      `**Latency:** ${lab.latencyMs != null ? `${lab.latencyMs.toFixed(1)} ms` : '—'}`,
      ``,
      `## AI Scientist Observation`,
      ``,
      scientist || '_No scientist brief yet._',
      ``,
      `## Causal BioReasoner`,
      ``,
      brief || '_No causal brief yet._',
      ``,
      `## Counterfactuals`,
      ``,
      ...(lab.xai?.counterfactuals ?? []).map(
        (c) => `- **${c.node} → ${c.readout_node}** (${c.fold_change.toFixed(1)}×): ${c.narrative}`,
      ),
      ``,
      `## Top Master Regulators`,
      ``,
      ...(lab.prioritization?.master_regulators ?? [])
        .slice(0, 8)
        .map(([g, s], i) => `${i + 1}. \`${g}\` — Sᵢ = ${s.toFixed(4)}`),
      ``,
    ].join('\n')
    downloadBlob(`voidsignal_brief_${lab.profileId}.md`, md, 'text/markdown')
  }

  const exportPdfFriendly = () => {
    // Printable HTML the browser can Save as PDF
    const html = `<!doctype html><html><head><meta charset="utf-8"/><title>VoidSignal Brief</title>
<style>
body{font-family:Georgia,serif;max-width:720px;margin:40px auto;color:#0f172a;line-height:1.5}
h1{font-size:22px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #cbd5e1;padding-bottom:4px}
.meta{color:#64748b;font-size:13px}code{background:#f1f5f9;padding:1px 4px;border-radius:4px}
</style></head><body>
<h1>VoidSignal Research Brief</h1>
<p class="meta">${lab.controls.conditionQuery} · ${lab.profileId} · ${new Date().toLocaleString()}</p>
<h2>AI Scientist</h2><p>${scientist || '—'}</p>
<h2>Causal BioReasoner</h2><p>${brief || '—'}</p>
<h2>Counterfactuals</h2>
<ul>${(lab.xai?.counterfactuals ?? [])
  .map((c) => `<li><strong>${c.node}</strong>: ${c.narrative}</li>`)
  .join('')}</ul>
<script>window.onload=()=>window.print()</script>
</body></html>`
    const w = window.open('', '_blank')
    if (w) {
      w.document.write(html)
      w.document.close()
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-extrabold tracking-tight text-slate-50">
            Research Briefs & Export
          </h1>
          <p className="text-sm text-slate-500">
            Grounded narratives · JSON dump · publication-ready print/PDF
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ExportBtn icon={FileJson} label="JSON" onClick={exportJson} />
          <ExportBtn icon={FileText} label="Markdown" onClick={exportMarkdown} />
          <ExportBtn icon={Download} label="Print / PDF" onClick={exportPdfFriendly} />
        </div>
      </div>

      <GlassCard title="Scenario" hint="Active laboratory context">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-slate-500">Condition</dt>
          <dd className="font-semibold text-slate-100">{lab.controls.conditionQuery}</dd>
          <dt className="text-slate-500">Profile</dt>
          <dd className="font-mono text-emerald-300">{lab.profileId}</dd>
          <dt className="text-slate-500">Simulation</dt>
          <dd className="font-mono text-slate-300">{lab.payload?.simulation_id ?? '—'}</dd>
          <dt className="text-slate-500">ODE cycle</dt>
          <dd className="font-mono text-slate-300">
            {lab.latencyMs != null ? `${lab.latencyMs.toFixed(1)} ms` : '—'}
          </dd>
        </dl>
      </GlassCard>

      <GlassCard title="AI Scientist Observation" hint="Live filter reasoning">
        <p className="text-sm leading-relaxed text-slate-300">
          {scientist || 'No scientist brief yet — run a simulation from Studio or the header search.'}
        </p>
      </GlassCard>

      <GlassCard title="Causal BioReasoner Brief" hint="Dijkstra-grounded pathway narrative">
        <p className="text-sm leading-relaxed text-slate-300">
          {brief || 'No causal brief yet.'}
        </p>
        {paths.length ? (
          <div className="mt-4 space-y-2">
            <div className="text-[0.68rem] font-semibold uppercase tracking-wide text-slate-500">
              Extracted cascades
            </div>
            {paths.map((p, i) => (
              <div
                key={i}
                className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 font-mono text-xs text-emerald-100/90"
              >
                {p.nodes.join(' → ')}
                <span className="ml-2 text-slate-500">Σα={p.cumulative_attention.toFixed(3)}</span>
              </div>
            ))}
          </div>
        ) : null}
        {lab.reason?.prompt ? (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs text-slate-500">LLM discovery prompt</summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[0.7rem] text-slate-400">
              {lab.reason.prompt}
            </pre>
          </details>
        ) : null}
      </GlassCard>
    </div>
  )
}

function ExportBtn({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof FileJson
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-emerald-500/40 hover:text-emerald-200"
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}
