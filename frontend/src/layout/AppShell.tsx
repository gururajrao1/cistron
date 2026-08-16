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
import { PanelBottom, PanelRight } from 'lucide-react'
import { clsx } from 'clsx'
import { SidebarNav, useSidebarExpanded } from './SidebarNav'
import { Header } from '../components/studio/Header'
import { NodeBiophysicsInspector } from '../components/NodeBiophysicsInspector'
import { BottomAnalysisDock } from './vcl/BottomAnalysisDock'
import { RightInspectorDock } from './vcl/RightInspectorDock'
import { CommandPalette } from './vcl/CommandPalette'
import { FirstRunChecklist } from '../components/studio/FirstRunChecklist'
import { useLab } from '../lab/LabContext'
import { StudioChromeProvider, useStudioChrome } from './StudioChromeContext'

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
 * Cistron VCL IDE shell — Benchling-style: destinations in the rail,
 * Studio stage stays map-first; docks are opt-in.
 */
export function AppShell() {
  return (
    <StudioChromeProvider>
      <AppShellInner />
    </StudioChromeProvider>
  )
}

function AppShellInner() {
  const location = useLocation()
  const lab = useLab()
  const isStudio = location.pathname === '/studio' || location.pathname === '/'
  const fillStage =
    isStudio ||
    location.pathname === '/biophysics' ||
    location.pathname.startsWith('/biophysics/')

  const [sidebarExpanded, setSidebarExpanded] = useSidebarExpanded()
  const [bottomH, setBottomH] = useState(240)
  const [dockW, setDockW] = useState(320)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const { bottomOpen, setBottomOpen, rightPinned, toggleBottom, toggleRight } =
    useStudioChrome()

  const mode = lab.viewMode
  const showRight = isStudio && (Boolean(lab.selectedNode) || rightPinned)
  const showBottomPanel = isStudio && bottomOpen

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

  useEffect(() => {
    if (mode === 'biologist') {
      setBottomOpen(false)
    }
  }, [mode, setBottomOpen])

  const bottomDrag = useDragResize('ns', bottomH, setBottomH, 120, 620, true)
  const rightDrag = useDragResize('ew', dockW, setDockW, 248, 560, true)

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-obsidian text-vcl-text">
      <Header onOpenPalette={() => setPaletteOpen(true)} />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <SidebarNav expanded={sidebarExpanded} onExpandedChange={setSidebarExpanded} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {isStudio ? (
            <div className="flex h-8 shrink-0 items-center gap-1.5 border-b border-vcl-border bg-obsidian-panel/80 px-2.5">
              <span className="mr-1 hidden font-mono text-[10px] text-vcl-dim sm:inline">
                Stage chrome
              </span>
              <button
                type="button"
                onClick={toggleBottom}
                className={clsx(
                  'inline-flex h-6 items-center gap-1 rounded-md border px-2 font-mono text-[10px] font-semibold transition',
                  showBottomPanel
                    ? 'border-cyan-flux/40 bg-[#0a2834] text-cyan-flux'
                    : 'border-vcl-border text-vcl-muted hover:text-vcl-text',
                )}
                title="Trajectory · Organelle · Flux analysis dock"
              >
                <PanelBottom className="h-3 w-3" />
                Analysis
              </button>
              <button
                type="button"
                onClick={toggleRight}
                className={clsx(
                  'inline-flex h-6 items-center gap-1 rounded-md border px-2 font-mono text-[10px] font-semibold transition',
                  rightPinned || lab.selectedNode
                    ? 'border-cyan-flux/40 bg-[#0a2834] text-cyan-flux'
                    : 'border-vcl-border text-vcl-muted hover:text-vcl-text',
                )}
                title="Targets · Brief · Omics (or select a node)"
              >
                <PanelRight className="h-3 w-3" />
                Inspect
              </button>
              <span className="ml-auto truncate font-mono text-[9.5px] text-vcl-dim">
                Heavy tools live in the left modules (XA · PH · CB · OM · 3D)
              </span>
            </div>
          ) : null}

          <main
            className={
              fillStage
                ? 'relative min-h-0 flex-1 overflow-hidden'
                : 'relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto'
            }
          >
            {fillStage ? (
              <>
                <div className="pointer-events-none absolute inset-0 lab-grid-panel opacity-35" />
                <div className="pointer-events-none absolute inset-0 vcl-stage-wash" />
                <div className="relative h-full min-h-0 overflow-hidden">
                  <StudioErrorBoundary>
                    <Outlet />
                  </StudioErrorBoundary>
                </div>
              </>
            ) : (
              <div className="relative min-h-full">
                <div className="pointer-events-none absolute inset-0 lab-grid-panel opacity-25" />
                <div className="pointer-events-none absolute inset-0 vcl-stage-wash" />
                <div className="relative pb-8">
                  <StudioErrorBoundary>
                    <Outlet />
                  </StudioErrorBoundary>
                </div>
              </div>
            )}
          </main>

          {isStudio && showBottomPanel ? (
            <>
              <div
                role="separator"
                aria-orientation="horizontal"
                className="group relative z-10 flex h-[5px] shrink-0 cursor-ns-resize items-center justify-center bg-obsidian-panel hover:bg-vcl-raised"
                onPointerDown={bottomDrag.onPointerDown}
                onPointerMove={bottomDrag.onPointerMove}
                onPointerUp={bottomDrag.onPointerUp}
              >
                <span className="h-px w-[34px] rounded bg-vcl-border-strong transition group-hover:bg-cyan-flux/70" />
              </div>
              <div
                className="shrink-0 overflow-hidden border-t border-cyan-flux/20 bg-[#041820]/95"
                style={{ height: bottomH }}
              >
                <BottomAnalysisDock />
              </div>
            </>
          ) : null}
        </div>

        {showRight ? (
          <>
            <div
              role="separator"
              aria-orientation="vertical"
              className="group relative z-10 flex w-[5px] shrink-0 cursor-ew-resize items-center justify-center bg-obsidian-panel hover:bg-vcl-raised"
              onPointerDown={rightDrag.onPointerDown}
              onPointerMove={rightDrag.onPointerMove}
              onPointerUp={rightDrag.onPointerUp}
            >
              <span className="h-[34px] w-px rounded bg-vcl-border-strong transition group-hover:bg-cyan-flux/70" />
            </div>
            <aside
              className="flex shrink-0 flex-col overflow-hidden border-l border-cyan-flux/20 bg-[#041820]/95 backdrop-blur-sm"
              style={{ width: dockW }}
            >
              {lab.selectedNode ? (
                <NodeBiophysicsInspector
                  nodeId={lab.selectedNode}
                  graph={lab.graph}
                  payload={lab.payload}
                  vector={lab.prioritization?.node_vectors?.[lab.selectedNode]}
                  xai={lab.xai}
                  onClose={() => lab.setSelectedNode(null)}
                  onKnockout={(node) => {
                    lab.setSelectedNode(null)
                    lab.setNodePerturbation(node, 0)
                  }}
                  onClamp={(node) => {
                    lab.setSelectedNode(null)
                    lab.setNodePerturbation(node, 1)
                  }}
                />
              ) : (
                <RightInspectorDock />
              )}
            </aside>
          </>
        ) : null}
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      {isStudio ? <FirstRunChecklist /> : null}
    </div>
  )
}
