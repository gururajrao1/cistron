import { useMemo, useState } from 'react'
import { BookOpen, Download, FileJson, FileText, Loader2 } from 'lucide-react'
import { GlassCard } from '../components/GlassCard'
import { PageHeader, VclButton } from '../components/PageHeader'
import { fetchLiteratureCopilot } from '../api/client'
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

type LitHit = { source: string; id: string; title: string; url: string }

export function BriefsView() {
  const lab = useLab()
  const brief = lab.reason?.brief ?? ''
  const scientist = lab.scientist?.brief ?? ''
  const paths = lab.reason?.context.extracted_paths ?? []

  const seedGene = useMemo(() => {
    const regs = lab.prioritization?.master_regulators ?? []
    if (regs[0]?.[0]) return String(regs[0][0])
    const nodes = lab.graph ? Object.keys(lab.graph.nodes) : []
    return nodes[0] ?? 'HIF1A'
  }, [lab.prioritization, lab.graph])

  const [gene, setGene] = useState('')
  const [partner, setPartner] = useState('')
  const [litBusy, setLitBusy] = useState(false)
  const [litSummary, setLitSummary] = useState<string | null>(null)
  const [citations, setCitations] = useState<LitHit[]>([])
  const [reactome, setReactome] = useState<LitHit[]>([])

  const runLiterature = async () => {
    setLitBusy(true)
    setLitSummary(null)
    try {
      const data = await fetchLiteratureCopilot({
        gene: (gene || seedGene).trim(),
        partner: partner.trim(),
        disease: lab.controls.conditionQuery.trim(),
        max_hits: 5,
      })
      setCitations(data.citations ?? [])
      setReactome(data.reactome ?? [])
      setLitSummary(data.summary)
    } catch (err) {
      setCitations([])
      setReactome([])
      setLitSummary(err instanceof Error ? err.message : 'Literature retrieve failed')
    } finally {
      setLitBusy(false)
    }
  }

  const exportJson = () => {
    const payload = {
      query: lab.controls.conditionQuery,
      profile_id: lab.profileId,
      simulation_id: lab.payload?.simulation_id,
      elapsed_ms: lab.latencyMs,
      causal_brief: lab.reason,
      scientist_reasoning: lab.scientist,
      xai_attributions: lab.xai,
      literature: { summary: litSummary, citations, reactome },
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
      `cistron_${lab.profileId}_${Date.now()}.json`,
      JSON.stringify(payload, null, 2),
      'application/json',
    )
  }

  const exportMarkdown = () => {
    const md = [
      `# Cistron Research Brief`,
      ``,
      `**Scenario:** ${lab.controls.conditionQuery}`,
      `**Profile:** ${lab.profileId}`,
      `**Simulation:** ${lab.payload?.simulation_id ?? '—'}`,
      `**Latency:** ${lab.latencyMs != null ? `${lab.latencyMs.toFixed(1)} ms` : '—'}`,
      ``,
      `## Mechanistic Brief`,
      ``,
      scientist || '_No scientist brief yet._',
      ``,
      `## Causal BioReasoner`,
      ``,
      brief || '_No causal brief yet._',
      ``,
      `## Literature Copilot (retrieve-only)`,
      ``,
      litSummary || '_Not retrieved yet._',
      ``,
      ...citations.map((c) => `- [${c.title}](${c.url})`),
      ...reactome.map((c) => `- [${c.title}](${c.url})`),
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
    downloadBlob(`cistron_brief_${lab.profileId}.md`, md, 'text/markdown')
  }

  const exportPdfFriendly = () => {
    const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Cistron Brief</title>
<style>
body{font-family:Georgia,serif;max-width:720px;margin:40px auto;color:#0f172a;line-height:1.5}
h1{font-size:22px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #cbd5e1;padding-bottom:4px}
.meta{color:#64748b;font-size:13px}code{background:#f1f5f9;padding:1px 4px;border-radius:4px}
</style></head><body>
<h1>Cistron Research Brief</h1>
<p class="meta">${lab.controls.conditionQuery} · ${lab.profileId} · ${new Date().toLocaleString()}</p>
<h2>Mechanistic Brief</h2><p>${scientist || '—'}</p>
<h2>Causal BioReasoner</h2><p>${brief || '—'}</p>
<h2>Literature</h2><p>${litSummary || '—'}</p>
<ul>${[...citations, ...reactome]
  .map((c) => `<li><a href="${c.url}">${c.title}</a></li>`)
  .join('')}</ul>
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
    <div className="mx-auto flex max-w-[76rem] flex-col gap-4 p-4 md:p-5">
      <PageHeader
        code="BR · Narrative · Export"
        title="Research Briefs"
        description="Grounded narratives, retrieve-only literature, JSON dump, and print-ready export."
        actions={
          <>
            <VclButton variant="ghost" onClick={exportJson}>
              <FileJson className="h-3.5 w-3.5" /> JSON
            </VclButton>
            <VclButton variant="ghost" onClick={exportMarkdown}>
              <FileText className="h-3.5 w-3.5" /> Markdown
            </VclButton>
            <VclButton variant="secondary" onClick={exportPdfFriendly}>
              <Download className="h-3.5 w-3.5" /> Print / PDF
            </VclButton>
          </>
        }
      />

      <GlassCard title="Scenario" hint="Active laboratory context">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-vcl-dim">Condition</dt>
          <dd className="font-semibold text-vcl-text">{lab.controls.conditionQuery}</dd>
          <dt className="text-vcl-dim">Profile</dt>
          <dd className="font-mono text-cyan-flux">{lab.profileId}</dd>
          <dt className="text-vcl-dim">Simulation</dt>
          <dd className="font-mono text-vcl-soft">{lab.payload?.simulation_id ?? '—'}</dd>
          <dt className="text-vcl-dim">ODE cycle</dt>
          <dd className="font-mono text-vcl-soft">
            {lab.latencyMs != null ? `${lab.latencyMs.toFixed(1)} ms` : '—'}
          </dd>
        </dl>
      </GlassCard>

      <GlassCard title="Mechanistic Brief" hint="Template Δy / flux reasoning (not an LLM)">
        <p className="text-sm leading-relaxed text-slate-300">
          {scientist || 'No scientist brief yet — run a simulation from Studio or the header search.'}
        </p>
      </GlassCard>

      <GlassCard
        title="Literature Copilot"
        hint="Retrieve-only PubMed + Reactome (no embeddings / vector DB)"
      >
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-vcl-dim">
            Gene
            <input
              className="rounded-md border border-vcl-border bg-vcl-surface px-2 py-1.5 font-mono text-xs text-vcl-text"
              value={gene}
              placeholder={seedGene}
              onChange={(e) => setGene(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-vcl-dim">
            Partner
            <input
              className="rounded-md border border-vcl-border bg-vcl-surface px-2 py-1.5 font-mono text-xs text-vcl-text"
              value={partner}
              placeholder="optional"
              onChange={(e) => setPartner(e.target.value)}
            />
          </label>
          <VclButton variant="secondary" disabled={litBusy} onClick={() => void runLiterature()}>
            {litBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <BookOpen className="h-3.5 w-3.5" />
            )}
            Retrieve
          </VclButton>
        </div>
        {litSummary ? (
          <p className="mb-3 text-sm leading-relaxed text-slate-300">{litSummary}</p>
        ) : (
          <p className="mb-3 text-sm text-vcl-dim">
            Pull PubMed titles and Reactome pathways for the active condition / gene. Citations are
            links only — nothing is invented.
          </p>
        )}
        {[...citations, ...reactome].length ? (
          <ul className="space-y-1.5 text-xs">
            {citations.map((c) => (
              <li key={`pm-${c.id}`}>
                <a
                  className="text-cyan-flux hover:underline"
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  PubMed · {c.title}
                </a>
              </li>
            ))}
            {reactome.map((c) => (
              <li key={`re-${c.id}`}>
                <a
                  className="text-emerald-active hover:underline"
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Reactome · {c.title}
                </a>
              </li>
            ))}
          </ul>
        ) : null}
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
