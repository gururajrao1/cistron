import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { LabProvider } from './lab/LabContext'
import { AppShell } from './layout/AppShell'
import { StudioView } from './views/StudioView'
import { ExplorerView } from './views/ExplorerView'
import { XaiView } from './views/XaiView'
import { PharmacologyView } from './views/PharmacologyView'
import { BriefsView } from './views/BriefsView'
import { CombinationsView } from './views/CombinationsView'
import { OmicsView } from './views/OmicsView'
import { StructureView } from './views/StructureView'
import { PathwaysView } from './views/PathwaysView'

export default function App() {
  return (
    <BrowserRouter>
      <LabProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/studio" replace />} />
            <Route path="studio" element={<StudioView />} />
            <Route path="pathways" element={<PathwaysView />} />
            <Route path="explorer" element={<ExplorerView />} />
            <Route path="xai" element={<XaiView />} />
            <Route path="pharmacology" element={<PharmacologyView />} />
            <Route path="briefs" element={<BriefsView />} />
            <Route path="omics" element={<OmicsView />} />
            <Route path="combinations" element={<CombinationsView />} />
            <Route path="combos" element={<CombinationsView />} />
            <Route path="biophysics" element={<StructureView />} />
            <Route path="*" element={<Navigate to="/studio" replace />} />
          </Route>
        </Routes>
      </LabProvider>
    </BrowserRouter>
  )
}
