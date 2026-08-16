/** Studio chrome preferences — keep the stage uncluttered (Benchling-style). */

const RIGHT_KEY = 'cistron.studio.rightPinned'
const BOTTOM_KEY = 'cistron.studio.bottomOpen'
const SIDEBAR_KEY = 'cistron.sidebar.expanded'
const PHENO_KEY = 'cistron.studio.phenotypeOpen'

function readBool(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    if (raw == null) return fallback
    return raw === '1' || raw === 'true'
  } catch {
    return fallback
  }
}

function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function loadRightPinned(): boolean {
  return readBool(RIGHT_KEY, false)
}

export function persistRightPinned(v: boolean) {
  writeBool(RIGHT_KEY, v)
}

export function loadBottomOpen(): boolean {
  return readBool(BOTTOM_KEY, false)
}

export function persistBottomOpen(v: boolean) {
  writeBool(BOTTOM_KEY, v)
}

export function loadSidebarExpanded(): boolean {
  return readBool(SIDEBAR_KEY, true)
}

export function persistSidebarExpanded(v: boolean) {
  writeBool(SIDEBAR_KEY, v)
}

export function loadPhenotypeOpen(): boolean {
  return readBool(PHENO_KEY, false)
}

export function persistPhenotypeOpen(v: boolean) {
  writeBool(PHENO_KEY, v)
}
