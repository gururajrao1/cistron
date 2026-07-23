import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchConditionSuggestions,
  fetchHealth,
  formatApiError,
  searchAndSimulate,
} from '../api/client'
import type {
  ConditionSuggestion,
  LabControls,
  PresetDetail,
  PreviousStateSummary,
  PrioritizationResult,
  ReasonResponse,
  ScientistReasoning,
  ScrubberPayload,
  TopologicalAnalysis,
  XAIAttributionResult,
} from '../api/types'

const STAGE_LABELS = [
  'Fetching multi-source topology',
  'Solving Hill-cube ODEs',
  'Calculating GAT Attention',
  'Computing XAI attributions',
  'Building BioReasoner Brief',
  'AI Scientist reasoning',
  'Topological vulnerability analysis',
]

const EMPTY_PATH: string[] = []
const EMPTY_SUGGESTIONS: ConditionSuggestion[] = []

/** Survives React StrictMode remount — prevents double bootstrap. */
let bootOnce = false

function initialControls(): LabControls {
  return {
    conditionQuery: 'Hypoxia-induced angiogenesis',
    clampNode: 'O2',
    clampValue: 0,
    knockouts: [],
    drugEnabled: false,
    drugTarget: 'HIF1A',
    cDrug: 5,
    ki: 1,
    sourceNode: 'O2',
    targetNode: 'VEGFA',
    // Offline-first: never boot with OmniPath/STRING live sources.
    selectedSources: ['local'],
  }
}

export type LabContextValue = {
  controls: LabControls
  setControls: (next: LabControls | ((prev: LabControls) => LabControls)) => void
  patchControls: (partial: Partial<LabControls>) => void
  scrubT: number
  setScrubT: (t: number) => void
  payload: ScrubberPayload | null
  graph: PresetDetail | null
  prioritization: PrioritizationResult | null
  reason: ReasonResponse | null
  xai: XAIAttributionResult | null
  scientist: ScientistReasoning | null
  stateSummary: PreviousStateSummary | null
  topologicalAnalysis: TopologicalAnalysis | null
  selectedNode: string | null
  setSelectedNode: (id: string | null) => void
  profileId: string
  latencyMs: number | null
  pingMs: number | null
  statusStage: string | null
  nodes: string[]
  clampOptions: string[]
  suggestions: ConditionSuggestion[]
  engineLive: boolean
  initializing: boolean
  busy: boolean
  offlineMessage: string | null
  topRegulator: string | null
  pathNodes: string[]
  runSimulation: (
    override?: Partial<LabControls> & {
      query?: string
      includeSyntheticLethality?: boolean
    },
  ) => void
  runQuery: (query: string) => void
}

const LabContext = createContext<LabContextValue | null>(null)

export function LabProvider({ children }: { children: ReactNode }) {
  const [controls, setControls] = useState<LabControls>(initialControls)
  const [scrubT, setScrubT] = useState(0)
  const [payload, setPayload] = useState<ScrubberPayload | null>(null)
  const [graph, setGraph] = useState<PresetDetail | null>(null)
  const [prioritization, setPrioritization] = useState<PrioritizationResult | null>(null)
  const [reason, setReason] = useState<ReasonResponse | null>(null)
  const [xai, setXai] = useState<XAIAttributionResult | null>(null)
  const [scientist, setScientist] = useState<ScientistReasoning | null>(null)
  const [stateSummary, setStateSummary] = useState<PreviousStateSummary | null>(null)
  const [topologicalAnalysis, setTopologicalAnalysis] =
    useState<TopologicalAnalysis | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [pingMs, setPingMs] = useState<number | null>(null)
  const [profileId, setProfileId] = useState('hypoxia')
  const [statusStage, setStatusStage] = useState<string | null>(null)

  const stageTimer = useRef<number | null>(null)
  const controlsRef = useRef(controls)
  controlsRef.current = controls
  const stateSummaryRef = useRef(stateSummary)
  stateSummaryRef.current = stateSummary
  const simBusyRef = useRef(false)
  const mutateRef = useRef<
    (
      override?: Partial<LabControls> & {
        query?: string
        includeSyntheticLethality?: boolean
      },
    ) => void
  >(() => {})

  const healthQ = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const t0 = performance.now()
      const data = await fetchHealth()
      setPingMs(performance.now() - t0)
      return data
    },
    refetchInterval: () => (simBusyRef.current ? false : 15_000),
    retry: 1,
  })

  const suggestionsQ = useQuery({
    queryKey: ['condition-suggestions'],
    queryFn: fetchConditionSuggestions,
    enabled: healthQ.isSuccess,
    retry: 1,
  })

  const nodes = useMemo(
    () => (graph?.nodes ? Object.keys(graph.nodes).sort() : []),
    [graph],
  )

  const clampOptions = useMemo(() => {
    if (!graph) return controls.clampNode ? [controls.clampNode] : []
    return Object.keys(graph.nodes).sort()
  }, [graph, controls.clampNode])

  const pathNodes = useMemo(() => {
    const raw = reason?.context.extracted_paths?.[0]?.nodes
    return raw?.length ? raw : EMPTY_PATH
  }, [reason])

  const topRegulator = prioritization?.master_regulators?.[0]?.[0] ?? null

  const clearStageTimer = useCallback(() => {
    if (stageTimer.current != null) {
      window.clearInterval(stageTimer.current)
      stageTimer.current = null
    }
  }, [])

  const startStageTicker = useCallback(() => {
    clearStageTimer()
    let i = 0
    setStatusStage(`${STAGE_LABELS[0]}…`)
    stageTimer.current = window.setInterval(() => {
      i = Math.min(i + 1, STAGE_LABELS.length - 1)
      setStatusStage(`${STAGE_LABELS[i]}…`)
    }, 450)
  }, [clearStageTimer])

  /** Apply results synchronously — startTransition was leaving a blank Studio. */
  const applySearchResult = useCallback(
    (body: Awaited<ReturnType<typeof searchAndSimulate>>) => {
      setPayload(body.scrubber_payload)
      setGraph(body.resolved_graph)
      setPrioritization(body.prioritization)
      setReason(body.causal_brief)
      setXai(body.xai_attributions ?? null)
      setScientist(body.scientist_reasoning ?? null)
      setStateSummary(body.state_summary ?? null)
      setTopologicalAnalysis(body.topological_analysis ?? null)
      setLatencyMs(body.elapsed_ms)
      setProfileId(body.profile_id)
      setScrubT(0)
      setStatusStage(null)
      const clamps = body.default_clamps
      const clampNode =
        controlsRef.current.clampNode in clamps
          ? controlsRef.current.clampNode
          : (Object.keys(clamps)[0] ?? body.source_node)
      setControls((prev) => ({
        ...prev,
        conditionQuery: body.query,
        clampNode,
        clampValue: clamps[clampNode] ?? prev.clampValue,
        sourceNode: body.source_node,
        targetNode: body.target_node,
        drugTarget:
          prev.drugTarget in (body.resolved_graph.nodes ?? {})
            ? prev.drugTarget
            : body.target_node,
        knockouts: prev.knockouts.filter(
          (k) => k in (body.resolved_graph.nodes ?? {}),
        ),
      }))
    },
    [],
  )

  const runMutation = useMutation({
    mutationFn: async (
      override?: Partial<LabControls> & {
        query?: string
        includeSyntheticLethality?: boolean
      },
    ) => {
      const c = { ...controlsRef.current, ...override }
      const q = (override?.query ?? c.conditionQuery).trim()
      const sources =
        c.selectedSources?.length > 0
          ? c.selectedSources
          : [...DEFAULT_SELECTED_SOURCES]
      const useOmni =
        sources.includes('omnipath') || sources.includes('signor')
      return await searchAndSimulate({
        condition_query: q,
        custom_knockouts: c.knockouts,
        custom_clamps: { [c.clampNode]: c.clampValue },
        drugs: c.drugEnabled
          ? [{ target: c.drugTarget, c_drug: c.cDrug, ki: c.ki }]
          : [],
        previous_state_summary: stateSummaryRef.current,
        source_node: c.sourceNode || undefined,
        target_node: c.targetNode || undefined,
        simulation_id: `search_${Date.now().toString(36)}`,
        use_omnipath: useOmni,
        selected_sources: sources,
        dense_output_points: 61,
        ...(override?.includeSyntheticLethality
          ? { include_synthetic_lethality: true }
          : {}),
      })
    },
    onMutate: () => {
      simBusyRef.current = true
      startStageTicker()
    },
    onSuccess: (body) => {
      applySearchResult(body)
    },
    onError: () => {
      setStatusStage(null)
    },
    onSettled: () => {
      simBusyRef.current = false
      clearStageTimer()
      setStatusStage(null)
    },
  })

  mutateRef.current = runMutation.mutate

  // Boot once after health is up (module flag beats StrictMode double-mount).
  useEffect(() => {
    if (!healthQ.isSuccess || bootOnce) return
    bootOnce = true
    mutateRef.current({
      query: 'Hypoxia-induced angiogenesis',
      selectedSources: ['local'],
      includeSyntheticLethality: false,
    })
  }, [healthQ.isSuccess])

  useEffect(() => () => clearStageTimer(), [clearStageTimer])

  const patchControls = useCallback((partial: Partial<LabControls>) => {
    setControls((prev) => ({ ...prev, ...partial }))
  }, [])

  const runSimulation = useCallback(
    (
      override?: Partial<LabControls> & {
        query?: string
        includeSyntheticLethality?: boolean
      },
    ) => {
      if (simBusyRef.current || runMutation.isPending) return
      runMutation.mutate(override)
    },
    [runMutation],
  )

  const runQuery = useCallback(
    (query: string) => {
      if (simBusyRef.current || runMutation.isPending) return
      patchControls({ conditionQuery: query })
      runMutation.mutate({ query, conditionQuery: query })
    },
    [patchControls, runMutation],
  )

  const engineLive = healthQ.isSuccess && healthQ.data?.status === 'ok'
  const busy = runMutation.isPending
  const initializing = engineLive && !payload && !runMutation.isError && busy
  const offlineMessage = healthQ.isError
    ? formatApiError(healthQ.error)
    : runMutation.isError
      ? formatApiError(runMutation.error)
      : null

  const value = useMemo<LabContextValue>(
    () => ({
      controls,
      setControls,
      patchControls,
      scrubT,
      setScrubT,
      payload,
      graph,
      prioritization,
      reason,
      xai,
      scientist,
      stateSummary,
      topologicalAnalysis,
      selectedNode,
      setSelectedNode,
      profileId,
      latencyMs,
      pingMs,
      statusStage,
      nodes,
      clampOptions,
      suggestions: suggestionsQ.data ?? EMPTY_SUGGESTIONS,
      engineLive,
      initializing,
      busy,
      offlineMessage,
      topRegulator,
      pathNodes,
      runSimulation,
      runQuery,
    }),
    [
      controls,
      patchControls,
      scrubT,
      payload,
      graph,
      prioritization,
      reason,
      xai,
      scientist,
      stateSummary,
      topologicalAnalysis,
      selectedNode,
      profileId,
      latencyMs,
      pingMs,
      statusStage,
      nodes,
      clampOptions,
      suggestionsQ.data,
      engineLive,
      initializing,
      busy,
      offlineMessage,
      topRegulator,
      pathNodes,
      runSimulation,
      runQuery,
    ],
  )

  return <LabContext.Provider value={value}>{children}</LabContext.Provider>
}

export function useLab(): LabContextValue {
  const ctx = useContext(LabContext)
  if (!ctx) throw new Error('useLab must be used within LabProvider')
  return ctx
}
