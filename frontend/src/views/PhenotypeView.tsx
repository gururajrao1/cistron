import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, VclButton } from '../components/PageHeader'
import { PhenotypeSummaryCard } from '../components/studio/PhenotypeSummaryCard'
import { WetLabProtocolCard } from '../components/studio/WetLabProtocolCard'
import { AcidMeter, BatteryGauge } from '../components/widgets'
import {
  buildPhenotypeSummary,
  buildWetLabProtocol,
} from '../engine/phenotypeSummary'
import { useLab } from '../lab/LabContext'

/**
 * Evidence destination for executive phenotype + wet-lab protocol.
 * Kept off Studio so the map page stays map-first.
 */
export function PhenotypeView() {
  const lab = useLab()
  const navigate = useNavigate()

  const summary = useMemo(
    () =>
      buildPhenotypeSummary({
        active: lab.payload,
        untreated: lab.untreatedRun,
        scrubT: lab.scrubT,
        profileId: lab.profileId,
        topo: lab.topologicalAnalysis,
      }),
    [
      lab.payload,
      lab.untreatedRun,
      lab.scrubT,
      lab.profileId,
      lab.topologicalAnalysis,
    ],
  )

  const protocol = useMemo(
    () => buildWetLabProtocol(summary, lab.profileId),
    [summary, lab.profileId],
  )

  return (
    <div className="mx-auto flex h-full min-h-0 max-w-4xl flex-col gap-4 overflow-y-auto p-4 md:p-6">
      <PageHeader
        code="PT · Evidence"
        title="Phenotype"
        description="Executive summary, metabolic gauges, and wet-lab protocol from the current scrubber state. Run or scrub in Studio, then return here to read out."
        actions={
          <VclButton variant="secondary" onClick={() => navigate('/studio')}>
            ST · back to map
          </VclButton>
        }
      />

      {!lab.payload ? (
        <p className="rounded-lg border border-vcl-border bg-vcl-surface px-4 py-3 text-[13px] text-vcl-muted">
          No active simulation yet. Open Studio, run a scenario, then revisit Phenotype.
        </p>
      ) : null}

      <PhenotypeSummaryCard summary={summary} />

      <div className="grid gap-4 sm:grid-cols-2">
        <BatteryGauge percentage={summary.atpPercent} />
        <AcidMeter level={summary.lactateLevel} />
      </div>

      <WetLabProtocolCard protocol={protocol} />
    </div>
  )
}
