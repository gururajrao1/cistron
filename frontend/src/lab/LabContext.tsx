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
  simulateDynamicGraph,
  simulateOmicsProfile,
} from '../api/client'
import type {
  ConditionSuggestion,
  DynamicGraphSimulateRequest,
  LabControls,
  OmicsProfile,
  OmicsSimulateParams,
  PresetDetail,
  PreviousStateSummary,
  PrioritizationResult,
  ReasonResponse,
  ScientistReasoning,
  ScrubberPayload,
  SearchAndSimulateResponse,
  TopologicalAnalysis,
  XAIAttributionResult,
} from '../api/types'
import { DEFAULT_SELECTED_SOURCES, withOmicsProvenance } from '../api/types'
import {
  buildDynamicInteractome,
  resolveDiseaseInteractome,
  type ReactomePathwayHit,
} from '../services/pathwayApi'
import {
  generateHypothesesFromLab,
  type CausalHypothesis,
} from '../services/aiCausalEngine'

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
  /** Baseline trajectory (no interactive perturbations). */
  untreatedRun: ScrubberPayload | null
  /** Active perturbation trajectory (null when untreated). */
  treatedRun: ScrubberPayload | null
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
  activeOmicsProfile: OmicsProfile | null
  /** Library of uploaded / example profiles for on-the-fly switching. */
  omicsProfiles: OmicsProfile[]
  omicsClamps: Record<string, number>
  /** Last Omics Fit Score (%) from /omics/simulate. */
  omicsAlignmentScore: number | null
  /** Interactive node clamps / titrations y∈[0,1]; 0 = knockout. */
  perturbations: Record<string, number>
  setNodePerturbation: (symbol: string, value: number, opts?: { resim?: boolean }) => void
  clearPerturbation: (symbol: string, opts?: { resim?: boolean }) => void
  clearAllPerturbations: (opts?: { resim?: boolean }) => void
  /** Pairwise synthetic-lethality Dual Screen over selected / focus targets. */
  runDualTargetScreen: () => void
  /**
   * Causal Hypothesis Cards for dual KO / synthetic lethality
   * (auto-built when ≥2 clamps or Dual Screen returns SL pairs).
   */
  causalHypotheses: CausalHypothesis[]
  /** Aggregated LLM prompt for the active hypothesis set. */
  causalHypothesisPrompt: string | null
  runSimulation: (
    override?: Partial<LabControls> & {
      query?: string
      includeSyntheticLethality?: boolean
    },
  ) => void
  runQuery: (query: string, opts?: { selectedSources?: string[] }) => void
  /**
   * Live Reactome + STRING interactome → Hill-cube t₀→t₆₀.
   * Pass a pathway hit from autocomplete, or a free-text disease query.
   * `opts.query` is the short disease label used for provenance (e.g. "Alzheimer Disease").
   */
  runDynamicDisease: (
    input: string | ReactomePathwayHit,
    opts?: { query?: string },
  ) => void
  /** Upload/example → simulate omics profile and hydrate Studio canvas. */
  runOmicsProfile: (profile: OmicsProfile, params?: OmicsSimulateParams) => void
  /** Switch active library profile and re-simulate. */
  selectOmicsProfile: (profileId: string) => void
}

const LabContext = createContext<LabContextValue | null>(null)

export function LabProvider({ children }: { children: ReactNode }) {
  const [controls, setControls] = useState<LabControls>(initialControls)
  const [scrubT, setScrubT] = useState(0)
  const [payload, setPayload] = useState<ScrubberPayload | null>(null)
  const [untreatedRun, setUntreatedRun] = useState<ScrubberPayload | null>(null)
  const [treatedRun, setTreatedRun] = useState<ScrubberPayload | null>(null)
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
  const [activeOmicsProfile, setActiveOmicsProfile] = useState<OmicsProfile | null>(null)
  const [omicsProfiles, setOmicsProfiles] = useState<OmicsProfile[]>([])
  const [omicsClamps, setOmicsClamps] = useState<Record<string, number>>({})
  const [omicsAlignmentScore, setOmicsAlignmentScore] = useState<number | null>(null)
  const [perturbations, setPerturbations] = useState<Record<string, number>>({})

  const stageTimer = useRef<number | null>(null)
  const controlsRef = useRef(controls)
  controlsRef.current = controls
  const stateSummaryRef = useRef(stateSummary)
  stateSummaryRef.current = stateSummary
  const perturbationsRef = useRef(perturbations)
  perturbationsRef.current = perturbations
  const activeOmicsProfileRef = useRef(activeOmicsProfile)
  activeOmicsProfileRef.current = activeOmicsProfile
  const simBusyRef = useRef(false)
  const dynamicBusyRef = useRef(false)
  const [dynamicPending, setDynamicPending] = useState(false)
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
    const raw = reason?.context?.extracted_paths?.[0]?.nodes
    return Array.isArray(raw) && raw.length > 0 ? raw.map(String) : EMPTY_PATH
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
  const applySearchResult = useCallback((body: SearchAndSimulateResponse) => {
    setPayload(body.scrubber_payload)
    const hasPert = Object.keys(perturbationsRef.current).length > 0
    if (hasPert) {
      setTreatedRun(body.scrubber_payload)
    } else {
      setUntreatedRun(body.scrubber_payload)
      setTreatedRun(null)
    }
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
    setOmicsClamps(clamps)
    const clampNode =
      controlsRef.current.clampNode in clamps
        ? controlsRef.current.clampNode
        : (Object.keys(clamps)[0] ?? body.source_node)
    setControls((prev) => ({
      ...prev,
      conditionQuery: body.query.startsWith('omics:')
        ? prev.conditionQuery
        : body.query,
      clampNode:
        clampNode && clampNode in (body.resolved_graph.nodes ?? {})
          ? clampNode
          : (Object.keys(clamps)[0] ?? body.source_node),
      clampValue: clamps[clampNode] ?? clamps[body.source_node] ?? prev.clampValue,
      sourceNode: body.source_node,
      targetNode: body.target_node,
      drugTarget:
        prev.drugTarget in (body.resolved_graph.nodes ?? {})
          ? prev.drugTarget
          : body.target_node,
      knockouts: prev.knockouts.filter((k) => k in (body.resolved_graph.nodes ?? {})),
    }))
    // Drop interactive clamps that vanished with the new topology.
    setPerturbations((prev) => {
      const next: Record<string, number> = {}
      for (const [k, v] of Object.entries(prev)) {
        if (k in (body.resolved_graph.nodes ?? {})) next[k] = v
      }
      perturbationsRef.current = next
      return next
    })
  }, [])

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
      const pert = perturbationsRef.current
      const pertKos = Object.entries(pert)
        .filter(([, v]) => v <= 1e-6)
        .map(([k]) => k)
      const knockouts = Array.from(new Set([...c.knockouts, ...pertKos]))
      // Avoid pinning O2/VEGFA when switching to p53 / MAPK / etc.
      const source = (c.sourceNode || '').trim() || undefined
      const target = (c.targetNode || '').trim() || undefined
      const clamps: Record<string, number> = { ...pert }
      if (c.clampNode && Number.isFinite(c.clampValue)) {
        clamps[c.clampNode] = c.clampValue
      }
      return await searchAndSimulate({
        condition_query: q,
        custom_knockouts: knockouts,
        custom_clamps: clamps,
        drugs: c.drugEnabled
          ? [{ target: c.drugTarget, c_drug: c.cDrug, ki: c.ki }]
          : [],
        previous_state_summary: stateSummaryRef.current,
        source_node: source,
        target_node: target,
        simulation_id: `search_${Date.now().toString(36)}`,
        use_omnipath: useOmni,
        selected_sources: sources,
        dense_output_points: 61,
        ...(override?.includeSyntheticLethality
          ? {
              include_synthetic_lethality: true,
              sl_candidate_nodes: Object.keys(pert),
            }
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

  const omicsMutation = useMutation({
    mutationFn: async ({
      profile,
      params,
    }: {
      profile: OmicsProfile
      params?: OmicsSimulateParams
    }) => {
      const c = controlsRef.current
      const pert = perturbationsRef.current
      const pertKos = Object.entries(pert)
        .filter(([, v]) => v <= 1e-6)
        .map(([k]) => k)
      const knockouts = Array.from(new Set([...c.knockouts, ...pertKos]))
      return await simulateOmicsProfile(profile, {
        t_end: 60,
        knockouts,
        perturbations: pert,
        drugs: c.drugEnabled
          ? [{ target: c.drugTarget, c_drug: c.cDrug, ki: c.ki }]
          : [],
        source_node: c.sourceNode || undefined,
        target_node: c.targetNode || undefined,
        simulation_id: `omics_${Date.now().toString(36)}`,
        previous_state_summary: stateSummaryRef.current,
        ...params,
      })
    },
    onMutate: () => {
      simBusyRef.current = true
      startStageTicker()
    },
    onSuccess: (body, vars) => {
      const provenanced = withOmicsProvenance({
        ...vars.profile,
        provenance:
          (typeof body.omics_provenance === 'string' && body.omics_provenance) ||
          (typeof body.metadata?.omics_provenance === 'string'
            ? (body.metadata.omics_provenance as string)
            : vars.profile.provenance),
      })
      setActiveOmicsProfile(provenanced)
      setOmicsProfiles((prev) => {
        const without = prev.filter((p) => p.profile_id !== provenanced.profile_id)
        return [...without, provenanced]
      })
      const score =
        typeof body.alignment_score === 'number'
          ? body.alignment_score
          : typeof body.metadata?.alignment_score === 'number'
            ? (body.metadata.alignment_score as number)
            : null
      setOmicsAlignmentScore(score)
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
    (query: string, opts?: { selectedSources?: string[] }) => {
      if (simBusyRef.current || runMutation.isPending) return
      const q = query.trim()
      if (!q) return
      // Scenario switch: drop prior topology KOs / omics so the new cascade hydrates cleanly.
      setPerturbations({})
      perturbationsRef.current = {}
      setActiveOmicsProfile(null)
      setOmicsAlignmentScore(null)
      setTreatedRun(null)
      setSelectedNode(null)
      const sources =
        opts?.selectedSources && opts.selectedSources.length > 0
          ? opts.selectedSources
          : undefined
      patchControls({
        conditionQuery: q,
        knockouts: [],
        sourceNode: '',
        targetNode: '',
        clampNode: '',
        ...(sources ? { selectedSources: sources } : {}),
      })
      // Keep controlsRef in sync before mutate (patchControls is async).
      if (sources) {
        controlsRef.current = {
          ...controlsRef.current,
          conditionQuery: q,
          selectedSources: sources,
          knockouts: [],
          sourceNode: '',
          targetNode: '',
          clampNode: '',
        }
      } else {
        controlsRef.current = {
          ...controlsRef.current,
          conditionQuery: q,
          knockouts: [],
          sourceNode: '',
          targetNode: '',
          clampNode: '',
        }
      }
      runMutation.mutate({
        query: q,
        conditionQuery: q,
        knockouts: [],
        sourceNode: '',
        targetNode: '',
        clampNode: '',
        ...(sources ? { selectedSources: sources } : {}),
      })
    },
    [patchControls, runMutation],
  )

  const runDynamicDisease = useCallback(
    (input: string | ReactomePathwayHit, opts?: { query?: string }) => {
      if (simBusyRef.current || runMutation.isPending || dynamicBusyRef.current) return

      const shortQuery = (opts?.query || '').trim()
      const label =
        typeof input === 'string'
          ? input.trim()
          : (shortQuery ||
              controlsRef.current.conditionQuery ||
              input.name ||
              input.pathwayId
            ).trim()
      if (!label) return

      // Short display / provenance seed — disease query, not the full Reactome title.
      const provenanceQuery =
        typeof input === 'string'
          ? label
          : (
              shortQuery ||
              controlsRef.current.conditionQuery.trim() ||
              label
            ).slice(0, 80)

      // Scenario switch — clear prior lab state.
      setPerturbations({})
      perturbationsRef.current = {}
      setActiveOmicsProfile(null)
      setOmicsAlignmentScore(null)
      setTreatedRun(null)
      setSelectedNode(null)
      patchControls({
        conditionQuery: provenanceQuery || label,
        knockouts: [],
        sourceNode: '',
        targetNode: '',
        clampNode: '',
        selectedSources: ['reactome', 'string'],
      })
      controlsRef.current = {
        ...controlsRef.current,
        conditionQuery: provenanceQuery || label,
        knockouts: [],
        sourceNode: '',
        targetNode: '',
        clampNode: '',
        selectedSources: ['reactome', 'string'],
      }

      dynamicBusyRef.current = true
      simBusyRef.current = true
      setDynamicPending(true)
      setStatusStage('Constructing dynamic interactome from Reactome & STRING-DB…')

      void (async () => {
        try {
          const interactome =
            typeof input === 'string'
              ? await resolveDiseaseInteractome(input)
              : await buildDynamicInteractome(input, { query: provenanceQuery })

          setStatusStage('Solving Hill-cube ODEs (t₀→t₆₀)…')
          const bodyReq: DynamicGraphSimulateRequest = {
            query: interactome.query,
            pathway_id: interactome.pathwayId,
            pathway_name: interactome.pathwayName,
            profile_id: interactome.provenance,
            nodes: interactome.nodes,
            edges: interactome.edges,
            dense_output_points: 61,
            t_end: 60,
            simulation_id: `dyn_${Date.now().toString(36)}`,
            previous_state_summary: stateSummaryRef.current,
          }
          const body = await simulateDynamicGraph(bodyReq)
          applySearchResult(body)
          setStatusStage(null)
          dynamicBusyRef.current = false
          setDynamicPending(false)
          simBusyRef.current = false
        } catch (err) {
          console.warn('Dynamic Reactome/STRING load failed — falling back to local resolve', err)
          dynamicBusyRef.current = false
          setDynamicPending(false)
          // runMutation.onMutate / onSettled own simBusyRef for the fallback path.
          runMutation.mutate({
            query: label,
            conditionQuery: label,
            knockouts: [],
            sourceNode: '',
            targetNode: '',
            clampNode: '',
            selectedSources: ['local'],
          })
        }
      })()
    },
    [applySearchResult, patchControls, runMutation],
  )

  const runOmicsProfile = useCallback(
    (profile: OmicsProfile, params?: OmicsSimulateParams) => {
      // Prefer omics over a stale boot lock — clear search busy so upload always runs.
      if (omicsMutation.isPending) return
      if (runMutation.isPending) {
        runMutation.reset()
      }
      simBusyRef.current = false
      const provenanced = withOmicsProvenance(profile)
      // Upsert into library + set active instantly so provenance badge updates on switch.
      setOmicsProfiles((prev) => {
        const without = prev.filter((p) => p.profile_id !== provenanced.profile_id)
        return [...without, provenanced]
      })
      setActiveOmicsProfile(provenanced)
      omicsMutation.mutate({ profile: provenanced, params })
    },
    [runMutation, omicsMutation],
  )

  const selectOmicsProfile = useCallback(
    (profileId: string) => {
      const profile = omicsProfiles.find((p) => p.profile_id === profileId)
      if (!profile) return
      // Instant active swap with full metadata (condition + provenance), then re-sim.
      const provenanced = withOmicsProvenance(profile)
      setActiveOmicsProfile(provenanced)
      runOmicsProfile(provenanced)
    },
    [omicsProfiles, runOmicsProfile],
  )

  const resimWithPerturbations = useCallback(() => {
    const omics = activeOmicsProfileRef.current
    if (omics) {
      runOmicsProfile(omics)
      return
    }
    runSimulation()
  }, [runOmicsProfile, runSimulation])

  const setNodePerturbation = useCallback(
    (symbol: string, value: number, opts?: { resim?: boolean }) => {
      const sym = symbol.trim().toUpperCase()
      if (!sym) return
      const v = Math.max(0, Math.min(1, Number(value)))
      setPerturbations((prev) => ({ ...prev, [sym]: v }))
      setControls((prev) => {
        const kos = new Set(prev.knockouts)
        if (v <= 1e-6) kos.add(sym)
        else kos.delete(sym)
        return { ...prev, knockouts: Array.from(kos) }
      })
      if (opts?.resim !== false) {
        // Defer so ref sees the updated perturbations map.
        queueMicrotask(() => {
          perturbationsRef.current = {
            ...perturbationsRef.current,
            [sym]: v,
          }
          resimWithPerturbations()
        })
      }
    },
    [resimWithPerturbations],
  )

  const clearPerturbation = useCallback(
    (symbol: string, opts?: { resim?: boolean }) => {
      const sym = symbol.trim().toUpperCase()
      if (!sym) return
      setPerturbations((prev) => {
        if (!(sym in prev)) return prev
        const next = { ...prev }
        delete next[sym]
        return next
      })
      setControls((prev) => ({
        ...prev,
        knockouts: prev.knockouts.filter((k) => k !== sym),
      }))
      if (opts?.resim !== false) {
        queueMicrotask(() => {
          const next = { ...perturbationsRef.current }
          delete next[sym]
          perturbationsRef.current = next
          resimWithPerturbations()
        })
      }
    },
    [resimWithPerturbations],
  )

  const clearAllPerturbations = useCallback(
    (opts?: { resim?: boolean }) => {
      setPerturbations({})
      setControls((prev) => ({ ...prev, knockouts: [] }))
      if (opts?.resim !== false) {
        queueMicrotask(() => {
          perturbationsRef.current = {}
          resimWithPerturbations()
        })
      }
    },
    [resimWithPerturbations],
  )

  const runDualTargetScreen = useCallback(() => {
    const focus = Object.keys(perturbationsRef.current)
    const omics = activeOmicsProfileRef.current
    if (omics) {
      if (omicsMutation.isPending) return
      if (runMutation.isPending) runMutation.reset()
      simBusyRef.current = false
      omicsMutation.mutate({
        profile: withOmicsProvenance(omics),
        params: {
          include_synthetic_lethality: true,
          sl_candidate_nodes: focus,
        },
      })
      return
    }
    runSimulation({ includeSyntheticLethality: true })
  }, [omicsMutation, runMutation, runSimulation])

  const engineLive = healthQ.isSuccess && healthQ.data?.status === 'ok'
  const busy = runMutation.isPending || omicsMutation.isPending || dynamicPending
  const initializing = engineLive && !payload && !runMutation.isError && busy
  const offlineMessage = healthQ.isError
    ? formatApiError(healthQ.error)
    : runMutation.isError
      ? formatApiError(runMutation.error)
      : omicsMutation.isError
        ? formatApiError(omicsMutation.error)
        : null

  /** Auto-trigger causal hypothesis cards: Dual Screen SL pairs or ≥2 simultaneous clamps. */
  const causalBundle = useMemo(() => {
    const clampCount = Object.keys(perturbations).length
    const slCount = topologicalAnalysis?.synthetic_lethal_pairs?.length ?? 0
    if (!graph || (clampCount < 2 && slCount < 1)) {
      return { hypotheses: [] as CausalHypothesis[], llmPrompt: null as string | null }
    }
    const bundle = generateHypothesesFromLab({
      graph,
      perturbations,
      treated: treatedRun ?? payload,
      untreated: untreatedRun,
      topologicalAnalysis,
    })
    return {
      hypotheses: bundle.hypotheses,
      llmPrompt: bundle.hypotheses.length ? bundle.llmPrompt : null,
    }
  }, [graph, perturbations, treatedRun, untreatedRun, payload, topologicalAnalysis])

  const value = useMemo<LabContextValue>(
    () => ({
      controls,
      setControls,
      patchControls,
      scrubT,
      setScrubT,
      payload,
      untreatedRun,
      treatedRun,
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
      activeOmicsProfile,
      omicsProfiles,
      omicsClamps,
      omicsAlignmentScore,
      perturbations,
      setNodePerturbation,
      clearPerturbation,
      clearAllPerturbations,
      runDualTargetScreen,
      causalHypotheses: causalBundle.hypotheses,
      causalHypothesisPrompt: causalBundle.llmPrompt,
      runSimulation,
      runQuery,
      runDynamicDisease,
      runOmicsProfile,
      selectOmicsProfile,
    }),
    [
      controls,
      patchControls,
      scrubT,
      payload,
      untreatedRun,
      treatedRun,
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
      activeOmicsProfile,
      omicsProfiles,
      omicsClamps,
      omicsAlignmentScore,
      perturbations,
      setNodePerturbation,
      clearPerturbation,
      clearAllPerturbations,
      runDualTargetScreen,
      causalBundle,
      runSimulation,
      runQuery,
      runDynamicDisease,
      runOmicsProfile,
      selectOmicsProfile,
    ],
  )

  return <LabContext.Provider value={value}>{children}</LabContext.Provider>
}

export function useLab(): LabContextValue {
  const ctx = useContext(LabContext)
  if (!ctx) throw new Error('useLab must be used within LabProvider')
  return ctx
}
