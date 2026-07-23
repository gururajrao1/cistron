# Cistron Laboratory Frontend

Visualization shell for the Cistron FastAPI backend. **No ODE, GAT, or BioReasoner math runs in the browser** — the UI only renders API payloads and lerps scrubber keyframes.

## Run

```bash
# Terminal 1
uvicorn cistron.api.app:app --reload --port 8000

# Terminal 2
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Components

| Component | Role |
|-----------|------|
| `ControlDock` | Preset / KO / clamp / PK-PD → `POST /api/v1/simulate` |
| `StudioCanvas` | Cytoscape topology + scrubber lerp + Recharts trajectories |
| `IntelligenceDrawer` | 5D `hᵢ` table, GAT `Sᵢ` ranks, BioReasoner brief + Dijkstra paths |

## API

All requests go to `http://localhost:8000/api/v1` (Vite proxies `/api` in dev). Offline / timeout errors surface in the navbar status and a banner with recovery instructions.
