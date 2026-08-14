import type { ReactNode } from 'react'
import { GitBranch, FlaskConical, Sparkles, Loader2 } from 'lucide-react'
import type { CausalHypothesis } from '../../services/aiCausalEngine'
import { GeneBadge, MetaLabel } from '../ui'

function Section({
  icon,
  label,
  children,
}: {
  icon: ReactNode
  label: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 text-[0.62rem] font-semibold uppercase tracking-[0.08em] text-vcl-dim">
        {icon}
        {label}
      </div>
      <p className="text-[11px] leading-relaxed text-vcl-soft">{children}</p>
    </div>
  )
}

export function HypothesisCard({ hypothesis }: { hypothesis: CausalHypothesis }) {
  const [a, b] = hypothesis.targets
  const syn =
    hypothesis.synergyScore != null && Number.isFinite(hypothesis.synergyScore)
      ? hypothesis.synergyScore
      : null

  return (
    <article className="lab-glass overflow-hidden rounded-xl border-cyan-flux/25 shadow-[0_0_20px_rgba(34,211,238,0.08)]">
      <header className="border-b border-vcl-border bg-vcl-surface/60 px-3 py-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <MetaLabel className="!text-cyan-flux/80">Hypothesis</MetaLabel>
            <h3 className="font-display mt-0.5 text-[13px] font-semibold leading-snug tracking-tight text-vcl-text">
              {hypothesis.title}
            </h3>
            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              <GeneBadge name={a} tone="coral" />
              <span className="text-[10px] font-bold text-vcl-dim">+</span>
              <GeneBadge name={b} tone="coral" />
              {hypothesis.source === 'synthetic_lethality' || hypothesis.source === 'screen' ? (
                <span className="rounded-md border border-phosphor/35 bg-[#1a2a0a] px-1.5 py-0.5 text-[0.58rem] font-semibold uppercase tracking-wide text-phosphor">
                  SL
                </span>
              ) : (
                <span className="rounded-md border border-vcl-border bg-vcl-raised px-1.5 py-0.5 text-[0.58rem] font-semibold uppercase tracking-wide text-vcl-muted">
                  Dual KO
                </span>
              )}
            </div>
          </div>
          {syn != null ? (
            <div className="shrink-0 rounded-lg border border-cyan-flux/30 bg-[#0a1f28] px-2 py-1 text-right">
              <div className="text-[0.55rem] font-semibold uppercase tracking-wider text-cyan-flux/70">
                Synergy
              </div>
              <div className="lab-mono text-[12px] font-bold text-cyan-flux">{syn.toFixed(2)}</div>
            </div>
          ) : null}
        </div>
      </header>

      <div className="space-y-2.5 px-3 py-2.5">
        <Section
          icon={<GitBranch className="h-3 w-3 text-cyan-flux/80" />}
          label="Pathway collapse mechanism"
        >
          {hypothesis.pathwayCollapse}
        </Section>

        {hypothesis.convergenceNodes.length ? (
          <div className="flex flex-wrap gap-1">
            {hypothesis.convergenceNodes.slice(0, 6).map((n) => (
              <GeneBadge key={n} name={n} tone="cyan" />
            ))}
          </div>
        ) : null}

        <Section
          icon={<Sparkles className="h-3 w-3 text-amber-kinase/80" />}
          label="Predicted phenotypic impact"
        >
          {hypothesis.phenotypicImpact}
        </Section>

        <Section
          icon={<FlaskConical className="h-3 w-3 text-emerald-soft/80" />}
          label="Suggested assay"
        >
          {hypothesis.suggestedAssay}
        </Section>
      </div>
    </article>
  )
}

export function HypothesisCardList({
  hypotheses,
  loading,
  emptyHint,
}: {
  hypotheses: CausalHypothesis[]
  loading?: boolean
  emptyHint?: string
}) {
  if (loading && !hypotheses.length) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-cyan-flux/25 bg-[#0a1f28]/60 px-3 py-2.5 text-[11px] text-cyan-flux/80">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span className="vcl-skeleton h-3 w-40 opacity-40" aria-hidden />
        Tracing dual-target causal paths…
      </div>
    )
  }

  if (!hypotheses.length) {
    return emptyHint ? (
      <p className="rounded-lg border border-dashed border-vcl-border px-3 py-2.5 text-[11px] text-vcl-dim">
        {emptyHint}
      </p>
    ) : null
  }

  return (
    <div className="space-y-2.5">
      {hypotheses.map((h) => (
        <HypothesisCard key={h.id} hypothesis={h} />
      ))}
    </div>
  )
}
