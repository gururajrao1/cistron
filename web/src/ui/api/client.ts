/**
 * Typed REST / WebSocket client for VOIDSIGNAL backend.
 * Defaults to in-browser mock adapters; set VITE_API_BASE to hit FastAPI.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_DOSES,
  MOCK_DOCKING,
  MOCK_HEALTH,
  MOCK_PATIENT,
  lookupEncyclopedia,
  mockAgentPlan,
  mockSimulation,
  networkForPathway,
} from "./mockData";
import type {
  AgentPlanRequest,
  AgentPlanResult,
  DoseParams,
  DockingPose,
  EncyclopediaCard,
  PatientBadge,
  PatientNetwork,
  SimulationRequest,
  SimulationRun,
  SystemHealth,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";
const USE_MOCK = !API_BASE || import.meta.env.VITE_USE_MOCK === "true";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return (await res.json()) as T;
}

export const api = {
  async getHealth(): Promise<SystemHealth> {
    if (USE_MOCK) {
      await delay(80);
      return { ...MOCK_HEALTH, uptimeSec: MOCK_HEALTH.uptimeSec + Math.floor(Math.random() * 3) };
    }
    return http<SystemHealth>("/api/v1/health");
  },

  async getPatient(patientId: string): Promise<PatientBadge> {
    if (USE_MOCK) {
      await delay(60);
      return { ...MOCK_PATIENT, patientId: patientId || MOCK_PATIENT.patientId };
    }
    return http<PatientBadge>(`/api/v1/patients/${encodeURIComponent(patientId)}`);
  },

  async getPatientNetwork(patientId: string, pathwayId = "hsa04010"): Promise<PatientNetwork> {
    if (USE_MOCK) {
      await delay(100);
      return networkForPathway(pathwayId, patientId);
    }
    return http<PatientNetwork>(
      `/api/v1/patients/${encodeURIComponent(patientId)}/network?pathwayId=${encodeURIComponent(pathwayId)}`,
    );
  },

  async getEncyclopediaCard(nodeId: string): Promise<EncyclopediaCard | null> {
    if (USE_MOCK) {
      await delay(40);
      return lookupEncyclopedia(nodeId);
    }
    return http<EncyclopediaCard>(`/api/v1/encyclopedia/${encodeURIComponent(nodeId)}`);
  },

  async runSimulation(request: SimulationRequest): Promise<SimulationRun> {
    if (USE_MOCK) {
      await delay(280);
      return mockSimulation(request);
    }
    return http<SimulationRun>("/api/v1/simulate", {
      method: "POST",
      body: JSON.stringify(request),
    });
  },

  async runAgent(request: AgentPlanRequest): Promise<AgentPlanResult> {
    if (USE_MOCK) {
      await delay(600);
      return mockAgentPlan(request);
    }
    return http<AgentPlanResult>("/api/v1/agent/plan", {
      method: "POST",
      body: JSON.stringify(request),
    });
  },

  async getDockingPose(ligandId: string): Promise<DockingPose> {
    if (USE_MOCK) {
      await delay(90);
      return { ...MOCK_DOCKING, ligandId };
    }
    return http<DockingPose>(`/api/v1/docking/${encodeURIComponent(ligandId)}`);
  },

  /** Optional live agent stream (mock emits log ticks; real uses WS). */
  openAgentStream(
    planId: string,
    onEvent: (chunk: AgentPlanResult) => void,
  ): () => void {
    if (USE_MOCK) {
      let cancelled = false;
      const result = mockAgentPlan({
        patientId: MOCK_PATIENT.patientId,
        goal: "stream",
        readout: "ERK",
        maxDrugs: 2,
      });
      result.planId = planId;
      result.status = "running";
      let i = 0;
      const id = window.setInterval(() => {
        if (cancelled) return;
        i += 1;
        const slice = {
          ...result,
          logs: result.logs.slice(0, i),
          status: (i >= result.logs.length ? "complete" : "running") as AgentPlanResult["status"],
        };
        onEvent(slice);
        if (i >= result.logs.length) window.clearInterval(id);
      }, 350);
      return () => {
        cancelled = true;
        window.clearInterval(id);
      };
    }

    const wsBase = API_BASE.replace(/^http/, "ws");
    const ws = new WebSocket(`${wsBase}/api/v1/agent/stream?planId=${encodeURIComponent(planId)}`);
    ws.onmessage = (ev) => {
      try {
        onEvent(JSON.parse(ev.data as string) as AgentPlanResult);
      } catch {
        /* ignore malformed frames */
      }
    };
    return () => ws.close();
  },
};

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export type AsyncState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
};

export function useSimulationRun() {
  const [state, setState] = useState<AsyncState<SimulationRun>>({
    data: null,
    error: null,
    loading: false,
  });

  const run = useCallback(async (request: SimulationRequest) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await api.runSimulation(request);
      setState({ data, error: null, loading: false });
      return data;
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e);
      setState({ data: null, error, loading: false });
      throw e;
    }
  }, []);

  return { ...state, run };
}

export function usePatientNetwork(patientId: string, pathwayId = "hsa04010") {
  const [state, setState] = useState<AsyncState<PatientNetwork>>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    api
      .getPatientNetwork(patientId, pathwayId)
      .then((data) => {
        if (alive) setState({ data, error: null, loading: false });
      })
      .catch((e: unknown) => {
        if (alive)
          setState({
            data: null,
            error: e instanceof Error ? e.message : String(e),
            loading: false,
          });
      });
    return () => {
      alive = false;
    };
  }, [patientId, pathwayId]);

  return state;
}

export function useAgentPlanner() {
  const [state, setState] = useState<AsyncState<AgentPlanResult>>({
    data: null,
    error: null,
    loading: false,
  });
  const stopRef = useRef<(() => void) | null>(null);

  useEffect(() => () => stopRef.current?.(), []);

  const launch = useCallback(async (request: AgentPlanRequest) => {
    stopRef.current?.();
    setState({ data: null, error: null, loading: true });
    try {
      const planId = `plan_${Date.now().toString(36)}`;
      stopRef.current = api.openAgentStream(planId, (chunk) => {
        setState({ data: chunk, error: null, loading: chunk.status === "running" });
      });
      const data = await api.runAgent(request);
      stopRef.current?.();
      stopRef.current = null;
      setState({ data, error: null, loading: false });
      return data;
    } catch (e) {
      stopRef.current?.();
      stopRef.current = null;
      const error = e instanceof Error ? e.message : String(e);
      setState({ data: null, error, loading: false });
      throw e;
    }
  }, []);

  return { ...state, launch };
}

export function useSystemBootstrap() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [patient, setPatient] = useState<PatientBadge | null>(null);
  const [doses, setDoses] = useState<DoseParams[]>(DEFAULT_DOSES);
  const [docking, setDocking] = useState<DockingPose | null>(null);

  useEffect(() => {
    void api.getHealth().then(setHealth);
    void api.getPatient(MOCK_PATIENT.patientId).then(setPatient);
    void api.getDockingPose(MOCK_DOCKING.ligandId).then(setDocking);
    const id = window.setInterval(() => {
      void api.getHealth().then(setHealth);
    }, 8000);
    return () => window.clearInterval(id);
  }, []);

  return { health, patient, doses, setDoses, docking };
}

export { DEFAULT_DOSES, MOCK_PATIENT };
