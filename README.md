# Cistron

Research-grade **virtual cellular laboratory** — Hill-cube ODE signalling, multi-omics conditioning, spatial reaction–diffusion, organelle compartments, synthetic lethality screening, XAI sensitivity, and publication-ready report export.

**Repo:** https://github.com/gururajrao1/cistron

**UI shell:** Cistron VCL Systems Biology IDE — dense clinical chrome (IBM Plex, 54px code rail, docks, ⌘K palette).

---

## Deploy (free)

### Why Render Docker failed

Render’s **Free** plan supports native runtimes (Python, Node, static sites) only.  
**Docker web services require a paid plan** — so a Blueprint with `runtime: docker` will keep failing with “Create web service … (deploy failed)”.

### Free Render blueprint (current `render.yaml`)

| Service | Runtime | Role |
| --- | --- | --- |
| `cistron-api` | Python (Free) | FastAPI + Reactome/STRING proxies |
| `cistron-ui` | Static (Free) | Built Vite Studio |

**Steps**

1. Delete any failed Blueprint (e.g. `cistron2`).
2. Render → **New → Blueprint** → `gururajrao1/cistron` → apply `render.yaml`.
3. Wait until **`cistron-api`** is live → copy its URL  
   (`https://cistron-api-xxxx.onrender.com`).
4. Open **`cistron-ui` → Environment** → set  
   `VITE_API_BASE` = that API URL (**no trailing slash**).
5. **`cistron-ui` → Manual Deploy → Clear build cache & deploy**.
6. Open the **`cistron-ui`** URL.

> Why the manual `VITE_API_BASE` step? Vite bakes the API URL at **build** time.  
> Render Blueprint `fromService` → static site often fails validation / isn’t available at create time (same approach as Render’s official FastAPI + Vite example).

**Notes**

- Free API **sleeps after ~15 min** idle; first request can take ~30–60s.
- Pathways uses `VITE_API_BASE/proxy/reactome` and `/proxy/string-db`.
- `Dockerfile` remains for local Docker / Fly / Hugging Face Spaces, **not** Render Free.

### Local Docker (optional)

```bash
docker build -t cistron .
docker run -p 8000:8000 -e PORT=8000 cistron
```

### Local production-like run

```bash
cd frontend && npm ci && set VITE_API_BASE=&& npm run build && cd ..
pip install -e ".[api]"
python -m uvicorn cistron.api.app:app --host 0.0.0.0 --port 8000
```

Then open http://127.0.0.1:8000

---

## Quick start

### 1. API (prefer port **8001**)

```bash
pip install -e ".[dev]"
python -m uvicorn cistron.api.app:app --host 127.0.0.1 --port 8001
```

Health: http://127.0.0.1:8001/api/v1/health

> Prefer **8001**. An old VoidSignal process on `:8000` will confuse the Studio health probe.

### 2. Frontend (Vite)

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173

### 3. Smoke tests

```bash
python examples/mapk_demo.py
pytest
```

---

## Studio navigation (sidebar rail)

Letter codes match the VCL mockup. Shortcuts: `Ctrl/⌘` + number.

| Code | Route | What it does |
| --- | --- | --- |
| **ST** | `/studio` | Simulation Studio — SVG network graph, spatial mesh, docks |
| **PW** | `/pathways` | Disease Pathways — Reactome + STRING → dynamic graph |
| **EX** | `/explorer` | Network Builder — sources / situations / τ registry |
| **XA** | `/xai` | XAI & Global Sensitivity — Sobol / SHAP-force / GAT |
| **PH** | `/pharmacology` | Pharmacology Lab — dose–response · clamps · KO |
| **BR** | `/briefs` | Research Briefs — AI Scientist + BioReasoner export |
| **CB** | `/combinations` | Combos — Bliss synergy heatmap · synthetic lethality |
| **OM** | `/omics` | Multi-omics — RNA-seq, MaxQuant/FragPipe PTM, metabolomics |
| **3D** | `/biophysics` | 3D Structure — UniProt / PDB / AlphaFold + PTM sites |

Header: scenario select · **Run** · provenance strip · **Snap** (local experiments) · **Export** report · ⌘K command palette.

---

## Features

### 1. VCL IDE shell

- **54px code rail** (`ST`…`3D`) with tooltips + keyboard shortcuts
- **46px header** — CISTRON·VCL, search palette, scenario presets, engine live, provenance badges (profile · sources · omics fit)
- **Right inspector dock** (Studio):
  - **Targets** — perturbations + impact / Dual Screen
  - **Scientist** — AI Scientist brief + causal hypothesis cards
  - **Omics** — multi-omics rail (PTM / metabolomics)
- **Bottom analysis dock** (Studio):
  - Time-series trajectory (untreated vs treated)
  - **Scenario A/B** compare table (Δy / Δ% at scrub time)
  - Organelle translocation
  - Metabolic flux (FBA-style bridge)
- **⌘K command palette** — jump routes / targets / actions
- **First-run checklist** — Pathways → Build → KO → Scrub → Export
- **Experiment snapshots** — save / restore condition + perturbations in `localStorage`
- Consistent **Apply → Studio** CTA on Pathways, Explorer, Pharma, XAI, Combos, Omics

### 2. Simulation Studio (`/studio`)

**Network Graph Topology**

- Mockup-faithful **SVG network graph** (zoom / pan / node drag)
- Scrub \(t_0 \rightarrow t_{60}\) without re-solving ODEs
- Target perturbations — knockout (\(y=0\)) or titration; Shift-click KO
- Impact & synergy · **Synthetic Lethality / Dual Screen**
- Node inspector: Knockout · Clamp · **Open 3D** · **Add to Combos**

**Spatial Microenvironment Mesh**

- Reaction–diffusion PDE on an \(N \times N\) tissue grid (O₂, VEGFA, TNF, DRUG)
- Click sources / drug sinks / tumor / erase
- **Load Histology Mask** — Visium / H&E-style geometry
- **BBB** toggle + MW / logP — barrier-limited drug exchange
- Organelle compartments synced to **mesh time**; HIF1A hypoxia import law

### 3. Disease Pathways (`/pathways`)

- Reactome search + ranked hits; one-click **Build**
- STRING interactome → `POST /api/v1/simulate-dynamic-graph`
- Provenance uses a short disease slug
- **Apply → Studio** after build

### 4. Multi-omics (`/omics`)

| Layer | How to use |
| --- | --- |
| **Transcriptomics** | DE CSV (`gene`, `log2FC`, `padj`) → \(y_0 = \mathrm{sigmoid}(\mathrm{log2FC})\) |
| **Proteomics / PTM** | MaxQuant / FragPipe occupancy → Boltzmann \(y_0\) |
| **Metabolomics** | ATP / Lactate / OCR from enzyme→metabolite bridge |
| **Overlay** | Transcript vs phospho-active form across \(t\) |

Canvas log2FC heatmap when a profile is active; header shows fit %.

### 5. 3D Structure (`/biophysics`)

- UniProt → best PDB (or AlphaFold)
- Residue / phospho chips via `?symbol=HIF1A&resi=643`

### 6. Combination Therapy (`/combinations`)

- Client Dual Screen — Bliss \(S = E_A + E_B - E_{AB}\)
- Heatmap cell → dual KO on Studio
- Server SL scan + hypothesis cards
- **Apply → Studio** for selected pair

### 7. XAI & Sensitivity (`/xai`)

- Sobol \(S_i / S_{Ti}\) · SHAP-force kinetic parameters
- Influence scatter · server SHAP / GAT master regulators
- **Apply → Studio**

### 8. Pharmacology (`/pharmacology`)

- Dose–response \(\theta = C/(C+K_i)\) · clamps · knockouts
- Apply & resimulate · **Apply → Studio**

### 9. Research Briefs (`/briefs`)

- AI Scientist + BioReasoner narratives
- JSON / Markdown / print-friendly export

### 10. Export Report (header)

Publication PDF/Markdown: abstract, topology snapshot, trajectories, perturbations, SL, hypotheses, methods citations (`jspdf` + `html2canvas`, ASCII-safe fonts).

### 11. Client engines (`frontend/src/engine/`)

| Module | Role |
| --- | --- |
| `compartmentOde.ts` | Multi-compartment Hill-cube + translocation |
| `diffusionGrid.ts` | Finite-difference reaction–diffusion mesh |
| `spatialHistologyLoader.ts` | Visium / H&E masks + BCs |
| `barrierKinetics.ts` | BBB permeability (logP, MW, P-gp) |
| `comboScreen.ts` | Pairwise dual-KO Bliss screen |
| `sensitivityXAI.ts` | Sobol-lite + SHAP-force |
| `metabolicBridge.ts` | Enzyme \(y(t)\) → metabolite fluxes |
| `edgeClassification.ts` / `nodeRing.ts` | Graph edge / ring fidelity |

### 12. Services (`frontend/src/services/`)

| Module | Role |
| --- | --- |
| `pathwayApi.ts` | Reactome + STRING builders |
| `ptmIngestion.ts` / `massSpecParser.ts` | PTM + MaxQuant / FragPipe |
| `aiCausalEngine.ts` | Dual-target hypothesis cards |
| `reportExporter.ts` | Publication PDF/MD |
| `experimentSnapshots.ts` | Local experiment save / restore |

---

## API surface (`/api/v1`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Liveness (`cistron-api`) |
| `GET` | `/sources` | Knowledge-source catalogue |
| `GET` | `/situations` | Situation catalogue |
| `POST` | `/search-and-simulate` | Query → graph → ODE + XAI / topology |
| `POST` | `/simulate-dynamic-graph` | Client interactome → full lab pipeline |
| `POST` | `/omics/upload` | Multipart CSV → `OmicsProfile` |
| `POST` | `/omics/simulate` | Profile → conditioned sim + alignment |
| `POST` | `/reasoner/brief` | Causal paths + narrative (optional) |

CLI: `cistron-api` (see `pyproject.toml`). Vite proxies API + Reactome/STRING.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CISTRON VIRTUAL CELL LAB                         │
├───────────────────────────────┬─────────────────────────────────────────┤
│  Python (FastAPI + HillCube)  │  React VCL Studio (Vite)                │
│  search-and-simulate          │  Code rail · docks · SVG graph · spatial│
│  omics upload + simulate      │  Combos · XAI · Omics · 3D · Snapshots  │
│  dynamic-graph pipeline       │  Client engines + LabContext hub        │
│  topology · GAT · XAI         │  Apply → Studio workflows               │
└───────────────────────────────┴─────────────────────────────────────────┘
```

---

## Typical workflows

**Hypoxia angiogenesis**

1. Pathways → search → Build → **Apply → Studio**
2. Right dock **Targets** → KO HIF1A / VEGFA; scrub bottom dock
3. **Scenario A/B** tab for Δy; Combos → Dual Screen → apply pair
4. Spatial Mesh → histology mask + BBB; Export Report

**Omics-conditioned run**

1. Omics → upload / example → Apply PTM \(y_0\) → **Apply → Studio**
2. Right dock **Omics** tab · header fit % · XAI Sobol

**First-time user**

1. Follow the floating **First run** checklist (or reopen via Guide chip)
2. Save progress with header **Snap** before refreshing

---

## Module map

| Path | Responsibility |
| --- | --- |
| [`cistron/engine/solver.py`](cistron/engine/solver.py) | Kraeutler Hill-cube ODE (server) |
| [`cistron/api/app.py`](cistron/api/app.py) | FastAPI routes |
| [`frontend/src/lab/LabContext.tsx`](frontend/src/lab/LabContext.tsx) | Studio state hub |
| [`frontend/src/layout/`](frontend/src/layout/) | VCL shell, docks, palette |
| [`frontend/src/engine/`](frontend/src/engine/) | Client multi-scale engines |
| [`frontend/src/services/`](frontend/src/services/) | Pathways, PTM, causal AI, reports, snapshots |
| [`frontend/src/views/`](frontend/src/views/) | Route pages |
| [`docs/design/`](docs/design/) | VCL mockup HTML / assets |

---

## Roadmap

1. **Phase 1** — topology, dual sim, perturbations *(shipped)*
2. **Phase 2** — multi-omics, alignment, canvas heatmap *(shipped)*
3. **Phase 3** — spatial RD, histology/BBB, combos, Sobol XAI, report export *(shipped)*
4. **Phase 4** — VCL IDE shell, SVG graph, docks, snapshots, first-run guide *(shipped)*
5. **Next** — full 3D PhysiCell-style PDE, SBML import, stochastic kinetics, clinical benchmarks

---

## License / citation

Research software. Auto-generated reports are **not** peer-reviewed manuscripts. Cite Kraeutler Hill cubes, Bliss independence, Saltelli global sensitivity, and continuum substrate models as appropriate for your paper.
