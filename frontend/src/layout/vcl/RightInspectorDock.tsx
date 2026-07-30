import { useState } from 'react'
import { clsx } from 'clsx'
import { PerturbationPanel } from '../../components/studio/PerturbationPanel'
import { EfficacyCard } from '../../components/studio/EfficacyCard'
import { ScientistPanel } from '../../components/ScientistPanel'
import { MultiOmicsRail } from '../../components/studio/MultiOmicsDrawer'
import { useLab } from '../../lab/LabContext'

type RightTab = 'targets' | 'scientist' | 'omics'

/**
 * Right inspector — Targets / AI Scientist / Multi-omics (features restored as dock tabs).
 */
export function RightInspectorDock() {
  const lab = useLab()
  const [tab, setTab] = useState<RightTab>('targets')

  const tabs: { id: RightTab; label: string }[] = [
    { id: 'targets', label: 'Targets' },
    { id: 'scientist', label: 'Scientist' },
    { id: 'omics', label: 'Omics' },
  ]

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex h-8 shrink-0 items-center gap-0.5 border-b border-vcl-border px-1.5">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={clsx(
              'h-full border-b-2 px-2 font-mono text-[10.5px] font-semibold transition',
              tab === t.id
                ? 'border-emerald-active text-vcl-text'
                : 'border-transparent text-vcl-muted hover:text-vcl-text',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'targets' ? (
        <>
          <div className="min-h-0 flex-[1.15] overflow-y-auto border-b border-vcl-border">
            <PerturbationPanel variant="dock" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <EfficacyCard variant="dock" />
          </div>
        </>
      ) : null}

      {tab === 'scientist' ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <ScientistPanel
            scientist={lab.scientist}
            loading={lab.busy && !lab.scientist}
            hypotheses={lab.causalHypotheses}
            hypothesesLoading={lab.busy && lab.causalHypotheses.length === 0}
          />
        </div>
      ) : null}

      {tab === 'omics' ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <MultiOmicsRail />
        </div>
      ) : null}
    </div>
  )
}
