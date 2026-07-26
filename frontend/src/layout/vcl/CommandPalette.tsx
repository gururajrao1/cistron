import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { PRIMARY_NAV } from '../SidebarNav'
import { useLab } from '../../lab/LabContext'

type Props = {
  open: boolean
  onClose: () => void
}

type PaletteItem = {
  id: string
  label: string
  hint: string
  group: string
  run: () => void
}

/**
 * ⌘K command palette — navigate, focus targets, run / reset / export.
 */
export function CommandPalette({ open, onClose }: Props) {
  const navigate = useNavigate()
  const lab = useLab()
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)

  const items = useMemo(() => {
    const list: PaletteItem[] = [
      ...PRIMARY_NAV.map((n) => ({
        id: `nav-${n.id}`,
        label: n.label,
        hint: n.code,
        group: 'Navigate',
        run: () => navigate(n.path),
      })),
      {
        id: 'run',
        label: 'Run simulation',
        hint: '▶',
        group: 'Actions',
        run: () => lab.runSimulation(),
      },
      {
        id: 'reset',
        label: 'Clear all perturbations',
        hint: 'reset',
        group: 'Actions',
        run: () => lab.clearAllPerturbations(),
      },
      ...lab.nodes.slice(0, 40).map((sym) => ({
        id: `node-${sym}`,
        label: sym,
        hint: 'target',
        group: 'Targets',
        run: () => {
          lab.setSelectedNode(sym)
          navigate('/studio')
        },
      })),
    ]
    const needle = q.trim().toLowerCase()
    if (!needle) return list
    return list.filter(
      (it) =>
        it.label.toLowerCase().includes(needle) ||
        it.hint.toLowerCase().includes(needle) ||
        it.group.toLowerCase().includes(needle),
    )
  }, [lab, navigate, q])

  useEffect(() => {
    if (!open) return
    setQ('')
    setActive(0)
  }, [open])

  useEffect(() => {
    setActive(0)
  }, [q])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActive((i) => Math.min(items.length - 1, i + 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActive((i) => Math.max(0, i - 1))
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const it = items[active]
        if (it) {
          it.run()
          onClose()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, items, active, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/55 pt-[12vh] backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-[604px] overflow-hidden rounded-lg border border-vcl-border bg-obsidian-panel shadow-2xl">
        <div className="flex items-center gap-2 border-b border-vcl-border px-3 py-2">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search targets, pathways, commands…"
            className="h-8 flex-1 bg-transparent font-mono text-[12px] text-vcl-text outline-none placeholder:text-vcl-dim"
          />
          <kbd className="rounded border border-vcl-border bg-vcl-raised px-1.5 py-0.5 font-mono text-[9px] text-vcl-dim">
            ESC
          </kbd>
        </div>
        <ul className="max-h-[360px] overflow-y-auto py-1">
          {items.length === 0 ? (
            <li className="px-3 py-4 text-center text-[11px] text-vcl-dim">No matches</li>
          ) : (
            items.map((it, i) => (
              <li key={it.id}>
                <button
                  type="button"
                  onMouseEnter={() => setActive(i)}
                  onClick={() => {
                    it.run()
                    onClose()
                  }}
                  className={clsx(
                    'flex w-full items-center justify-between gap-3 px-3 py-2 text-left',
                    i === active ? 'bg-vcl-surface' : 'hover:bg-vcl-surface/50',
                  )}
                >
                  <div>
                    <div className="font-mono text-[11.5px] font-semibold text-vcl-text">
                      {it.label}
                    </div>
                    <div className="text-[10px] text-vcl-dim">{it.group}</div>
                  </div>
                  <span className="font-mono text-[10px] text-vcl-muted">{it.hint}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  )
}
