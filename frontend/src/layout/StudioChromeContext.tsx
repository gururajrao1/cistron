import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  loadBottomOpen,
  loadRightPinned,
  persistBottomOpen,
  persistRightPinned,
} from './studioChrome'

type StudioChromeCtx = {
  bottomOpen: boolean
  setBottomOpen: (v: boolean) => void
  rightPinned: boolean
  setRightPinned: (v: boolean) => void
  toggleBottom: () => void
  toggleRight: () => void
}

const Ctx = createContext<StudioChromeCtx | null>(null)

export function StudioChromeProvider({ children }: { children: ReactNode }) {
  const [bottomOpen, setBottomOpenState] = useState(loadBottomOpen)
  const [rightPinned, setRightPinnedState] = useState(loadRightPinned)

  const setBottomOpen = useCallback((v: boolean) => {
    setBottomOpenState(v)
    persistBottomOpen(v)
  }, [])

  const setRightPinned = useCallback((v: boolean) => {
    setRightPinnedState(v)
    persistRightPinned(v)
  }, [])

  const value = useMemo(
    () => ({
      bottomOpen,
      setBottomOpen,
      rightPinned,
      setRightPinned,
      toggleBottom: () => setBottomOpen(!bottomOpen),
      toggleRight: () => setRightPinned(!rightPinned),
    }),
    [bottomOpen, rightPinned, setBottomOpen, setRightPinned],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStudioChrome(): StudioChromeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) {
    return {
      bottomOpen: false,
      setBottomOpen: () => undefined,
      rightPinned: false,
      setRightPinned: () => undefined,
      toggleBottom: () => undefined,
      toggleRight: () => undefined,
    }
  }
  return ctx
}
