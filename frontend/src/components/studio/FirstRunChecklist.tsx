import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { CheckCircle2, Circle, ListChecks, X } from 'lucide-react'
import { clsx } from 'clsx'
import { useLab } from '../../lab/LabContext'

const STORAGE_KEY = 'cistron.firstRun.v1'

type StepId = 'pathways' | 'build' | 'knockout' | 'scrub' | 'export'

type Step = {
  id: StepId
  title: string
  hint: string
  path?: string
}

const STEPS: Step[] = [
  {
    id: 'pathways',
    title: 'Open Pathways',
    hint: 'Search a disease (e.g. Glioblastoma)',
    path: '/pathways',
  },
  {
    id: 'build',
    title: 'Build a network',
    hint: 'Click Build / load → to hydrate Studio',
    path: '/pathways',
  },
  {
    id: 'knockout',
    title: 'Knock out a target',
    hint: 'Studio · pick a node or use Target Perturbations',
    path: '/studio',
  },
  {
    id: 'scrub',
    title: 'Scrub the timeline',
    hint: 'Bottom dock · drag t₀ → t₆₀',
    path: '/studio',
  },
  {
    id: 'export',
    title: 'Export a report',
    hint: 'Header · Export Report (PDF)',
    path: '/studio',
  },
]

type Persisted = {
  dismissed: boolean
  done: Partial<Record<StepId, boolean>>
}

function load(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { dismissed: false, done: {} }
    return JSON.parse(raw) as Persisted
  } catch {
    return { dismissed: false, done: {} }
  }
}

function save(p: Persisted) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p))
}

/**
 * Lightweight guided checklist for first-time Studio users.
 */
export function FirstRunChecklist() {
  const lab = useLab()
  const navigate = useNavigate()
  const location = useLocation()
  const [state, setState] = useState<Persisted>(() => load())
  const [open, setOpen] = useState(() => !load().dismissed)

  // Auto-detect progress from live lab state.
  useEffect(() => {
    setState((prev) => {
      const done = { ...prev.done }
      if (location.pathname.includes('pathways')) done.pathways = true
      if (lab.graph && Object.keys(lab.graph.nodes ?? {}).length > 0) done.build = true
      if (Object.keys(lab.perturbations).length > 0 || lab.controls.knockouts.length > 0) {
        done.knockout = true
      }
      if (lab.scrubT > 0) done.scrub = true
      const next = { ...prev, done }
      save(next)
      return next
    })
  }, [
    location.pathname,
    lab.graph,
    lab.perturbations,
    lab.controls.knockouts,
    lab.scrubT,
  ])

  const completed = useMemo(
    () => STEPS.filter((s) => state.done[s.id]).length,
    [state.done],
  )

  if (state.dismissed || !open) {
    if (state.dismissed) return null
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-3 left-[66px] z-30 inline-flex items-center gap-1.5 rounded-md border border-vcl-border bg-obsidian-panel px-2.5 py-1.5 font-mono text-[10px] text-vcl-soft shadow-lg hover:border-vcl-border-strong"
        title="First-run checklist"
      >
        <ListChecks className="h-3.5 w-3.5 text-emerald-active" />
        Guide {completed}/{STEPS.length}
      </button>
    )
  }

  return (
    <div className="fixed bottom-3 left-[66px] z-30 w-[280px] rounded-lg border border-vcl-border bg-obsidian-panel shadow-2xl">
      <div className="flex items-center gap-2 border-b border-vcl-border px-3 py-2">
        <ListChecks className="h-3.5 w-3.5 text-emerald-active" />
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold text-vcl-text">First run</div>
          <div className="font-mono text-[10px] text-vcl-dim">
            {completed}/{STEPS.length} complete
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            setOpen(false)
          }}
          className="text-vcl-dim hover:text-vcl-text"
          aria-label="Minimize"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <ul className="max-h-[240px] space-y-1 overflow-y-auto p-2">
        {STEPS.map((step) => {
          const ok = Boolean(state.done[step.id])
          return (
            <li key={step.id}>
              <button
                type="button"
                onClick={() => {
                  if (step.path) navigate(step.path)
                  setState((prev) => {
                    const next = {
                      ...prev,
                      done: { ...prev.done, [step.id]: true },
                    }
                    save(next)
                    return next
                  })
                }}
                className={clsx(
                  'flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-vcl-surface',
                  ok && 'opacity-70',
                )}
              >
                {ok ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-active" />
                ) : (
                  <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-vcl-dim" />
                )}
                <span>
                  <span className="block text-[11px] font-medium text-vcl-text">
                    {step.title}
                  </span>
                  <span className="block text-[10px] text-vcl-muted">{step.hint}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="border-t border-vcl-border px-3 py-2">
        <button
          type="button"
          onClick={() => {
            const next = { ...state, dismissed: true }
            save(next)
            setState(next)
            setOpen(false)
          }}
          className="font-mono text-[10px] text-vcl-dim hover:text-vcl-muted"
        >
          Dismiss guide
        </button>
      </div>
    </div>
  )
}

/** Call when user opens Export Report successfully. */
export function markFirstRunExportDone() {
  const prev = load()
  const next = { ...prev, done: { ...prev.done, export: true } }
  save(next)
}
