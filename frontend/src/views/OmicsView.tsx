import { OmicsUploader } from '../components/studio/OmicsUploader'
import { MultiOmicsDrawer } from '../components/studio/MultiOmicsDrawer'
import { ApplyToStudioButton } from '../components/studio/ApplyToStudioButton'
import { useLab } from '../lab/LabContext'

/** Differential omics upload + multi-omics (PTM / metabolomics) inspector. */
export function OmicsView() {
  const lab = useLab()
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-4">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-vcl-muted">
          RNA-seq / MaxQuant PTM / metabolomics → condition Studio y₀
        </p>
        <ApplyToStudioButton
          disabled={!lab.graph && !lab.activeOmicsProfile}
          busy={lab.busy}
        />
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden lg:flex-row">
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          <OmicsUploader />
        </div>
        <aside className="max-h-full w-full shrink-0 overflow-y-auto lg:w-[360px]">
          <MultiOmicsDrawer />
        </aside>
      </div>
    </div>
  )
}
