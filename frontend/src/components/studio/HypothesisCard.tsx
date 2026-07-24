import type { ReactNode } from 'react'
import { Beaker, GitBranch, FlaskConical, Sparkles, Loader2 } from 'lucide-react'
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
      <div className="flex items-center gap-1.5 text-[0.62rem] font-semibold uppercase tracking-[0.08em] text-slate-500">
        {icon}
        {label}
      </div>
      <p className="text-[11px] leading-relaxed text-slate-300">{children}</p>
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
    <article className="overflow-hidden rounded-xl border border-violet-hub/35 bg-gradient-to-b from-violet-950/40 via-slate-950/60 to-slate-950/80 shadow-[0_0_20px_rgba(139,92,246,0.12)]">
      <header className="border-b border-violet-hub/25 bg-violet-950/30 px-3 py-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <MetaLabel className="!text-violet-300/90">Hypothesis</MetaLabel>
            <h3 className="mt-0.5 text-[12.5px] font-extrabold leading-snug tracking-tight text-violet-50">
              {hypothesis.title}
            </h3>
            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              <GeneBadge name={a} tone="coral" />
              <span className="text-[10px] font-bold text-violet-300/80">+</span>
              <GeneBadge name={b} tone="coral" />
              {hypothesis.source === 'synthetic_lethality' || hypothesis.source === 'screen' ? (
                <span className="rounded-md border border-violet-400/30 bg-violet-500/15 px-1.5 py-0.5 text-[0.58rem] font-semibold uppercase tracking-wide text-violet-200">
                  SL
                </span>
              ) : (
                <span className="rounded-md border border-slate-600/50 bg-slate-800/60 px-1.5 py-0.5 text-[0.58rem] font-semibold uppercase tracking-wide text-slate-400">
                  Dual KO
                </span>
              )}
            </div>
          </div>
          {syn != null ? (
            <div className="shrink-0 rounded-lg border border-violet-500/30 bg-violet-950/50 px-2 py-1 text-right">
              <div className="text-[0.55rem] font-semibold uppercase tracking-wider text-violet-400/80">
                Synergy
              </div>
              <div className="lab-mono text-[12px] font-bold text-violet-100">{syn.toFixed(2)}</div>
            </div>
          ) : null}
        </div>
      </header>

      <div className="space-y-2.5 px-3 py-2.5">
        <Section
          icon={<GitBranch className="h-3 w-3 text-violet-300/80" />}
          label="Pathway collapse mechanism"
        >
          {hypothesis.pathwayCollapse}
        </Section>

        {hypothesis.convergenceNodes.length ? (
          <div className="flex flex-wrap gap-1">
            {hypothesis.convergenceNodes.slice(0, 6).map((n) => (
              <GeneBadge key={n} name={n} tone="violet" />
            ))}
          </div>
        ) : null}

        <Section
          icon={<Sparkles className="h-3 w-3 text-amber-300/80" />}
          label="Predicted phenotypic impact"
        >
          {hypothesis.phenotypicImpact}
        </Section>

        <Section
          icon={<FlaskConical className="h-3 w-3 text-cyan-300/80" />}
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
      <div className="flex items-center gap-2 rounded-xl border border-violet-hub/25 bg-violet-950/20 px-3 py-2.5 text-[11px] text-violet-200/80">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Tracing dual-target causal paths…
      </div>
    )
  }

  if (!hypotheses.length) {
    return (
      <p className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 px-3 py-2.5 text-[10.5px] leading-relaxed text-slate-600">
        {emptyHint ??
          'Apply two simultaneous clamps or run Synthetic Lethality / Dual Screen to generate hypothesis cards.'}
      </p>
    )
  }

  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-1.5 px-0.5">
        <Beaker className="h-3.5 w-3.5 text-violet-300" />
        <span className="text-[0.65rem] font-bold uppercase tracking-[0.1em] text-violet-200/90">
          Causal hypotheses
        </span>
        <span className="lab-mono text-[0.6rem] text-slate-500">{hypotheses.length}</span>
      </div>
      {hypotheses.map((h) => (
        <HypothesisCard key={h.id} hypothesis={h} />
      ))}
    </div>
  )
}
