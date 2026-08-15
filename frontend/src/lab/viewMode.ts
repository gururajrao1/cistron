/** Workspace depth of detail — controls progressive disclosure across Studio. */

export type ViewMode = 'biologist' | 'researcher' | 'systems'

export const VIEW_MODE_DEFAULT: ViewMode = 'researcher'

export const VIEW_MODE_STORAGE_KEY = 'cistron.viewMode'

export function parseViewMode(raw: unknown): ViewMode {
  if (raw === 'biologist' || raw === 'researcher' || raw === 'systems') return raw
  return VIEW_MODE_DEFAULT
}

export function loadViewMode(): ViewMode {
  try {
    return parseViewMode(localStorage.getItem(VIEW_MODE_STORAGE_KEY))
  } catch {
    return VIEW_MODE_DEFAULT
  }
}

export function persistViewMode(mode: ViewMode): void {
  try {
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
}
