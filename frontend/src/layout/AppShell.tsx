import {
  Component,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ErrorInfo,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { SidebarNav } from './SidebarNav'
import { Header } from '../components/studio/Header'
import { NodeBiophysicsInspector } from '../components/NodeBiophysicsInspector'
import { BottomAnalysisDock } from './vcl/BottomAnalysisDock'
import { RightInspectorDock } from './vcl/RightInspectorDock'
import { CommandPalette } from './vcl/CommandPalette'
import { FirstRunChecklist } from '../components/studio/FirstRunChecklist'
import { useLab } from '../lab/LabContext'

/** Catch canvas/runtime errors so Studio never blanks the whole shell. */
class StudioErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Studio render crash', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-sm text-red-200">
          <div className="max-w-lg text-center">
            Studio render error: {this.state.error.message}
          </div>
          <pre className="max-h-40 max-w-lg overflow-auto rounded-lg border border-vcl-border bg-obsidian p-2 text-[10px] text-vcl-muted">
            {this.state.error.stack?.split('\n').slice(0, 8).join('\n')}
          </pre>
          <button
            type="button"
            className="rounded-md border border-vcl-border px-3 py-1 text-vcl-text hover:bg-vcl-surface"
            onClick={() => this.setState({ error: null })}
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function useDragResize(
  axis: 'ns' | 'ew',
  value: number,
  setValue: (n: number) => void,
  min: number,
  max: number,
  invert = false,
) {
  const dragging = useRef(false)
  const start = useRef({ pos: 0, size: 0 })

  const onPointerDown = useCallback(
    (e: ReactPointerEvent) => {
      dragging.current = true
      start.current = {
        pos: axis === 'ns' ? e.clientY : e.clientX,
        size: value,
      }
      ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    },
    [axis, value],
  )

  const onPointerMove = useCallback(
    (e: ReactPointerEvent) => {
      if (!dragging.current) return
      const delta =
        axis === 'ns' ? e.clientY - start.current.pos : e.clientX - start.current.pos
      const next = invert
        ? start.current.size - delta
        : start.current.size + delta
      setValue(Math.max(min, Math.min(max, next)))
    },
    [axis, invert, max, min, setValue],
  )

  const onPointerUp = useCallback(() => {
    dragging.current = false
  }, [])

  return { onPointerDown, onPointerMove, onPointerUp }
}

/**
 * Cistron VCL IDE shell — Systems Biology IDE mockup geometry:
 * full-bleed 46px header → rail | stage(+bottom dock) | right inspector.
 */
export function AppShell() {
  const location = useLocation()
  const lab = useLab()
  const isStudio = location.pathname === '/studio' || location.pathname === '/'

  const [bottomH, setBottomH] = useState(258)
  const [dockW, setDockW] = useState(344)
  const [paletteOpen, setPaletteOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const bottomDrag = useDragResize('ns', bottomH, setBottomH, 46, 620, true)
  const rightDrag = useDragResize('ew', dockW, setDockW, 248, 560, true)

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-obsidian text-vcl-text">
      <Header onOpenPalette={() => setPaletteOpen(true)} />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <SidebarNav collapsed onToggle={() => undefined} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {/* Studio fills the stage; other routes must scroll or the bottom clips. */}
          <main
            className={
              isStudio
                ? 'relative min-h-0 flex-1 overflow-hidden'
                : 'relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto'
            }
          >
            {isStudio ? (
              <>
                <div className="pointer-events-none absolute inset-0 lab-grid-panel opacity-30" />
                <div className="relative h-full min-h-0 overflow-hidden">
                  <StudioErrorBoundary>
                    <Outlet />
                  </StudioErrorBoundary>
                </div>
              </>
            ) : (
              <div className="relative min-h-full bg-obsidian/40">
                <div className="pointer-events-none absolute inset-0 lab-grid-panel opacity-30" />
                <div className="relative pb-8">
                  <StudioErrorBoundary>
                    <Outlet />
                  </StudioErrorBoundary>
                </div>
              </div>
            )}
          </main>

          {isStudio ? (
            <>
              <div
                role="separator"
                aria-orientation="horizontal"
                className="group relative z-10 flex h-[5px] shrink-0 cursor-ns-resize items-center justify-center bg-obsidian-panel hover:bg-vcl-raised"
                onPointerDown={bottomDrag.onPointerDown}
                onPointerMove={bottomDrag.onPointerMove}
                onPointerUp={bottomDrag.onPointerUp}
              >
                <span className="h-px w-[34px] rounded bg-vcl-border-strong group-hover:bg-emerald-active/60" />
              </div>
              <div
                className="shrink-0 overflow-hidden border-t border-vcl-border bg-obsidian-panel"
                style={{ height: bottomH }}
              >
                <BottomAnalysisDock />
              </div>
            </>
          ) : null}
        </div>

        {isStudio ? (
          <>
            <div
              role="separator"
              aria-orientation="vertical"
              className="group relative z-10 flex w-[5px] shrink-0 cursor-ew-resize items-center justify-center bg-obsidian-panel hover:bg-vcl-raised"
              onPointerDown={rightDrag.onPointerDown}
              onPointerMove={rightDrag.onPointerMove}
              onPointerUp={rightDrag.onPointerUp}
            >
              <span className="h-[34px] w-px rounded bg-vcl-border-strong group-hover:bg-emerald-active/60" />
            </div>
            <aside
              className="flex shrink-0 flex-col overflow-hidden border-l border-vcl-border bg-obsidian-panel"
              style={{ width: dockW }}
            >
              <RightInspectorDock />
            </aside>
          </>
        ) : null}
      </div>

      {lab.selectedNode ? (
        <NodeBiophysicsInspector
          nodeId={lab.selectedNode}
          graph={lab.graph}
          payload={lab.payload}
          vector={lab.prioritization?.node_vectors?.[lab.selectedNode]}
          xai={lab.xai}
          onClose={() => lab.setSelectedNode(null)}
          onKnockout={(node) => {
            const nextKos = Array.from(new Set([...lab.controls.knockouts, node]))
            lab.patchControls({ knockouts: nextKos })
            lab.setSelectedNode(null)
            lab.runSimulation({ knockouts: nextKos })
          }}
          onClamp={(node) => {
            lab.patchControls({ clampNode: node, clampValue: 1 })
            lab.setSelectedNode(null)
            lab.runSimulation({ clampNode: node, clampValue: 1 })
          }}
        />
      ) : null}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      {isStudio ? <FirstRunChecklist /> : null}
    </div>
  )
}
