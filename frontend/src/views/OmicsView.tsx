import { OmicsUploader } from '../components/studio/OmicsUploader'
import { MultiOmicsDrawer } from '../components/studio/MultiOmicsDrawer'

/** Differential omics upload + multi-omics (PTM / metabolomics) inspector. */
export function OmicsView() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-hidden p-4 lg:flex-row">
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <OmicsUploader />
      </div>
      <aside className="max-h-full w-full shrink-0 overflow-y-auto lg:w-[360px]">
        <MultiOmicsDrawer />
      </aside>
    </div>
  )
}
