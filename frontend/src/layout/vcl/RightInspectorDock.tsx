import { PerturbationPanel } from '../../components/studio/PerturbationPanel'
import { EfficacyCard } from '../../components/studio/EfficacyCard'

/**
 * Right inspector — TARGET PERTURBATIONS + IMPACT / SYNERGY (mockup dock).
 */
export function RightInspectorDock() {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-[1.15] overflow-y-auto border-b border-vcl-border">
        <PerturbationPanel variant="dock" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <EfficacyCard variant="dock" />
      </div>
    </div>
  )
}
