import type { LabControls } from '../api/types'

const STORAGE_KEY = 'cistron.experiment.snapshots.v1'
const MAX_SNAPSHOTS = 12

export type ExperimentSnapshot = {
  id: string
  name: string
  savedAt: string
  conditionQuery: string
  profileId: string
  scrubT: number
  perturbations: Record<string, number>
  knockouts: string[]
  controls: Pick<
    LabControls,
    | 'clampNode'
    | 'clampValue'
    | 'drugEnabled'
    | 'drugTarget'
    | 'cDrug'
    | 'ki'
    | 'sourceNode'
    | 'targetNode'
    | 'selectedSources'
  >
  notes?: string
}

export function listSnapshots(): ExperimentSnapshot[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as ExperimentSnapshot[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveSnapshot(
  snap: Omit<ExperimentSnapshot, 'id' | 'savedAt'> & { id?: string },
): ExperimentSnapshot {
  const next: ExperimentSnapshot = {
    ...snap,
    id: snap.id ?? `snap-${Date.now()}`,
    savedAt: new Date().toISOString(),
  }
  const all = [next, ...listSnapshots().filter((s) => s.id !== next.id)].slice(
    0,
    MAX_SNAPSHOTS,
  )
  localStorage.setItem(STORAGE_KEY, JSON.stringify(all))
  return next
}

export function deleteSnapshot(id: string): void {
  const all = listSnapshots().filter((s) => s.id !== id)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(all))
}

export function exportSnapshotJson(snap: ExperimentSnapshot): void {
  const blob = new Blob([JSON.stringify(snap, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `cistron_${snap.name.replace(/\W+/g, '_')}.json`
  a.click()
  URL.revokeObjectURL(url)
}
