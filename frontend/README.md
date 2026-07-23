# Cistron Laboratory Frontend

Visualization shell for the Cistron FastAPI backend. **No ODE, GAT, or BioReasoner math runs in the browser** — the UI renders API payloads and lerps scrubber keyframes.

## Run

```bash
# Terminal 1 — API (prefer 8001; avoid stale VoidSignal on :8000)
python -m uvicorn cistron.api.app:app --host 127.0.0.1 --port 8001

# Terminal 2
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173

## Routes

| Path | Role |
|------|------|
| `/studio` | Cytoscape topology, scrubber, trajectories, omics heatmap |
| `/omics` | CSV upload, multi-sample profile switcher, Omics Fit Score |
| `/explorer` | Sources / situations catalogue |

## Components

| Component | Role |
|-----------|------|
| `StudioCanvas` | Cytoscape topology + log2FC heatmap + scrubber lerp + Recharts |
| `OmicsUploader` | Profile library dropdown · upload / example DE tables |
| `HeaderBar` | Health, latency, Omics-Conditioned + fit % |
| `LabContext` | Shared lab state · `omicsProfiles` · `selectOmicsProfile` |

## Omics overlay

When `activeOmicsProfile` is set:

- Mapped nodes: red ↑ / blue ↓ scaled by \|log2FC\| (±3)
- Unmapped nodes: slate `#64748b`
- Floating legend with active condition badge

## API

Client probes for `cistron-api` (default **8001**). Key routes:

- `POST /api/v1/search-and-simulate`
- `POST /api/v1/omics/upload`
- `POST /api/v1/omics/simulate` → includes `alignment_score`
