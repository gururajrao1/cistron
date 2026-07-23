import { Component, useState, type ErrorInfo, type ReactNode } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { SidebarNav } from './SidebarNav'
import { HeaderBar } from './HeaderBar'
import { NodeBiophysicsInspector } from '../components/NodeBiophysicsInspector'
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
        <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-sm text-red-200">
          <div>Studio render error: {this.state.error.message}</div>
          <button
            type="button"
            className="rounded-lg border border-slate-700 px-3 py-1 text-slate-300 hover:bg-slate-800"
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

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const lab = useLab()

  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-obsidian">
      <SidebarNav collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <HeaderBar />
        <main className="relative min-h-0 flex-1 overflow-hidden">
          <div className="pointer-events-none absolute inset-0 lab-grid-panel opacity-40" />
          {/* No opacity animation — framer initial:0 was blanking Studio after load. */}
          <div key={location.pathname} className="relative h-full min-h-0 overflow-y-auto">
            <StudioErrorBoundary>
              <Outlet />
            </StudioErrorBoundary>
          </div>
        </main>
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
    </div>
  )
}
