import axios, { AxiosError } from 'axios'
import type {
  HealthResponse,
  PresetDetail,
  PresetSummary,
  PrioritizeResponse,
  ReasonRequest,
  ReasonResponse,
  SimulateRequest,
  SimulateResponse,
  ScrubberPayload,
} from './types'

/**
 * Visualization-only API client.
 * All ODE / GAT / BioReasoner math stays on FastAPI (`cistron.api.app`).
 *
 * Prefer direct backend URL so the Vite UI works even if the proxy is misconfigured.
 * Override with VITE_API_BASE (e.g. empty string to use the Vite /api proxy).
 */
const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000'

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 60_000,
})

const v1 = '/api/v1'

export class ApiOfflineError extends Error {
  constructor(message = 'Cistron API is offline') {
    super(message)
    this.name = 'ApiOfflineError'
  }
}

/** Human-readable errors when FastAPI is down or returns 4xx/5xx. */
export function formatApiError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError<{ detail?: string | { msg?: string }[] }>
    if (!ax.response) {
      if (ax.code === 'ECONNABORTED') {
        return 'API request timed out. Is uvicorn running on http://127.0.0.1:8000?'
      }
      return (
        'Cannot reach Cistron API at http://127.0.0.1:8000. ' +
        'Start the backend with: uvicorn cistron.api.app:app --reload --port 8000'
      )
    }
    const detail = ax.response.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d) => d.msg ?? JSON.stringify(d)).join('; ')
    }
    return `API error ${ax.response.status}: ${ax.message}`
  }
  if (err instanceof Error) return err.message
  return 'Unexpected client error'
}

async function withApiErrors<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (err) {
    throw new Error(formatApiError(err))
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  return withApiErrors(async () => {
    const { data } = await api.get<HealthResponse>(`${v1}/health`)
    return data
  })
}

export async function fetchPresets(): Promise<PresetSummary[]> {
  return withApiErrors(async () => {
    const { data } = await api.get<PresetSummary[]>(`${v1}/presets`)
    return data
  })
}

export async function fetchPreset(presetId: string): Promise<PresetDetail> {
  return withApiErrors(async () => {
    const { data } = await api.get<PresetDetail>(`${v1}/presets/${presetId}`)
    return data
  })
}

/** POST /api/v1/simulate — returns backend ScrubberPayload (61 keyframes). */
export async function runSimulate(body: SimulateRequest): Promise<SimulateResponse> {
  return withApiErrors(async () => {
    const { data } = await api.post<SimulateResponse>(`${v1}/simulate`, body)
    return data
  })
}

/** POST /api/v1/prioritize — GAT attention + 5D vectors computed server-side. */
export async function runPrioritize(
  preset: string,
  payload: ScrubberPayload,
): Promise<PrioritizeResponse> {
  return withApiErrors(async () => {
    const { data } = await api.post<PrioritizeResponse>(`${v1}/prioritize`, {
      preset,
      payload,
    })
    return data
  })
}

/** POST /api/v1/reasoner/brief — Dijkstra paths + grounded narrative from backend. */
export async function runReasonerBrief(body: ReasonRequest): Promise<ReasonResponse> {
  return withApiErrors(async () => {
    const { data } = await api.post<ReasonResponse>(`${v1}/reasoner/brief`, body)
    return data
  })
}

export async function fetchConditionSuggestions(): Promise<
  import('./types').ConditionSuggestion[]
> {
  return withApiErrors(async () => {
    const { data } = await api.get(`${v1}/conditions/suggestions`)
    return data
  })
}

/** POST /api/v1/search-and-simulate — dynamic condition → full lab pipeline. */
export async function searchAndSimulate(
  body: import('./types').SearchAndSimulateRequest,
): Promise<import('./types').SearchAndSimulateResponse> {
  return withApiErrors(async () => {
    const { data } = await api.post(`${v1}/search-and-simulate`, body)
    return data
  })
}

export async function fetchKnowledgeSources(): Promise<
  import('./types').KnowledgeSource[]
> {
  return withApiErrors(async () => {
    const { data } = await api.get(`${v1}/sources`)
    return data
  })
}

export async function fetchSourceSituations(
  sources?: string[],
): Promise<import('./types').SourceSituation[]> {
  return withApiErrors(async () => {
    const params =
      sources && sources.length
        ? { sources: sources.join(',') }
        : undefined
    const { data } = await api.get(`${v1}/situations`, { params })
    return data
  })
}

export async function fetchProteinMeta(
  symbol: string,
): Promise<import('./types').ProteinMeta> {
  return withApiErrors(async () => {
    const { data } = await api.get(`${v1}/proteins/${encodeURIComponent(symbol)}`)
    return data
  })
}

/** POST /api/v1/omics/upload — multipart CSV → OmicsProfile. */
export async function uploadOmicsCsv(
  file: File,
  sampleName: string,
  condition: string,
): Promise<import('./types').OmicsProfile> {
  return withApiErrors(async () => {
    const form = new FormData()
    form.append('file', file)
    form.append('sample_name', sampleName)
    form.append('condition', condition)
    const { data } = await api.post(`${v1}/omics/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 30_000,
    })
    return data
  })
}

/** POST /api/v1/omics/simulate — omics-conditioned lab pipeline. */
export async function simulateOmicsProfile(
  profile: import('./types').OmicsProfile,
  params: import('./types').OmicsSimulateParams = {},
): Promise<import('./types').SearchAndSimulateResponse> {
  return withApiErrors(async () => {
    const { data } = await api.post(`${v1}/omics/simulate`, {
      profile,
      t_end: params.t_end ?? 60,
      knockouts: params.knockouts ?? [],
      drugs: params.drugs ?? [],
      dense_output_points: params.dense_output_points ?? 61,
      source_node: params.source_node,
      target_node: params.target_node,
      simulation_id: params.simulation_id,
      scaling_factor: params.scaling_factor ?? 1.0,
      baseline_y0: params.baseline_y0 ?? 0.5,
      previous_state_summary: params.previous_state_summary ?? null,
    })
    return data
  })
}

export function lerpAtTime(
  payload: ScrubberPayload,
  t: number,
): { nodes: Record<string, number>; edges: Record<string, number> } {
  const times = payload.time_steps
  if (!times.length) return { nodes: {}, edges: {} }

  const sample = (series: number[], i0: number, i1: number, w: number) =>
    series[i0]! + w * (series[i1]! - series[i0]!)

  if (t <= times[0]!) {
    return {
      nodes: Object.fromEntries(Object.entries(payload.nodes).map(([k, v]) => [k, v[0] ?? 0])),
      edges: Object.fromEntries(Object.entries(payload.edges).map(([k, v]) => [k, v[0] ?? 0])),
    }
  }
  if (t >= times[times.length - 1]!) {
    return {
      nodes: Object.fromEntries(
        Object.entries(payload.nodes).map(([k, v]) => [k, v[v.length - 1] ?? 0]),
      ),
      edges: Object.fromEntries(
        Object.entries(payload.edges).map(([k, v]) => [k, v[v.length - 1] ?? 0]),
      ),
    }
  }

  let i1 = 1
  while (i1 < times.length && times[i1]! < t) i1 += 1
  const i0 = i1 - 1
  const t0 = times[i0]!
  const t1 = times[i1]!
  const w = t1 <= t0 ? 0 : (t - t0) / (t1 - t0)

  return {
    nodes: Object.fromEntries(
      Object.entries(payload.nodes).map(([k, v]) => [k, sample(v, i0, i1, w)]),
    ),
    edges: Object.fromEntries(
      Object.entries(payload.edges).map(([k, v]) => [k, sample(v, i0, i1, w)]),
    ),
  }
}
