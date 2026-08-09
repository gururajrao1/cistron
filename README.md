# Cistron

**Research-grade virtual cellular laboratory** — Hill-cube ODE signalling, disease pathway graphs, multi-omics conditioning, spatial reaction–diffusion, organelle compartments, synthetic lethality screening, XAI sensitivity, plain-language protein explainers, and publication-ready report export.

| | |
| --- | --- |
| **Live demo** | [https://cistron.onrender.com](https://cistron.onrender.com) |
| **Repository** | [https://github.com/gururajrao1/cistron](https://github.com/gururajrao1/cistron) |
| **Stack** | Python 3.10+ (FastAPI + NumPy/SciPy Hill-cube) · React 19 / Vite / Tailwind (VCL Studio) |
| **License** | MIT |

**UI shell:** Cistron VCL Systems Biology IDE — dense clinical chrome (IBM Plex, 54px code rail, docks, ⌘K palette).

> Free Render instances **sleep after ~15 minutes** idle. The first request after sleep can take ~30–60s.

---

## What Cistron does

Cistron lets you ask *what if* questions on disease signalling networks:

1. **Build** a pathway from Reactome / STRING (or curated hypoxia / MAPK presets)
2. **Simulate** activity over time with a Kraeutler-style Hill-cube ODE engine
3. **Perturb** — knockout, clamp, dose a drug, dual-target combo screens
4. **Condition** the run on RNA-seq / PTM / metabolomics profiles
5. **Explain** — Sobol / SHAP-style sensitivity, AI Scientist briefs, and retrieve-grounded protein cards (including “if this protein changes…” for any Pathways disease)

It is a research sandbox, not a clinical decision system. Auto-generated reports are **not** peer-reviewed manuscripts.

---

## Table of contents

1. [Quick start](#quick-start)
2. [Studio navigation](#studio-navigation)
3. [Features](#features)
4. [Gene / protein explainers](#gene--protein-explainers)
5. [API surface](#api-surface)
6. [Architecture](#architecture)
7. [Python library map](#python-library-map)
8. [Deploy (free Render)](#deploy-free-render)
9. [Environment variables](#environment-variables)
10. [Typical workflows](#typical-workflows)
11. [Tech stack](#tech-stack)
12. [Roadmap](#roadmap)
13. [Citation & license](#citation--license)

---

## Quick start

### Development (API + Vite)

Prefer API on **8001** so an old process on `:8000` does not confuse the Studio health probe.

```bash
# Terminal 1 — API
pip install -e ".[dev]"
python -m uvicorn cistron.api.app:app --host 127.0.0.1 --port 8001
```

Health: http://127.0.0.1:8001/api/v1/health

```bash
# Terminal 2 — Studio
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173 — Vite proxies `/api` and Reactome/STRING proxies to the API.

### Production-like (single process)

```bash
cd frontend && npm ci && set VITE_API_BASE=&& npm run build && cd ..
pip install -e ".[api]"
python -m uvicorn cistron.api.app:app --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000 — FastAPI serves `/api/v1/*` and the built SPA from `frontend/dist`.

### Docker

```bash
docker build -t cistron .
docker run -p 8000:8000 -e PORT=8000 cistron
```

(`Dockerfile` is for local Docker / Fly / HF Spaces — **not** Render Free, which forbids Docker web services.)

### Smoke tests

```bash
python examples/mapk_demo.py
pytest
```

CLI entrypoints (see `pyproject.toml`): `cistron-api`, `cistron-run`, `cistron-lab`.

---

## Studio navigation

Letter codes match the VCL rail. Shortcuts: `Ctrl/⌘` + number.

| Code | Route | What it does |
| --- | --- | --- |
| **ST** | `/studio` | Simulation Studio — SVG network, spatial mesh, docks |
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
  - **Node Biophysics Inspector** — protein card, disease impact, IDs, 5D feature vector, KO / Clamp
- **Bottom analysis dock** (Studio): time-series · Scenario A/B · organelle translocation · metabolic flux
- **⌘K command palette** · **First-run checklist** · **Experiment snapshots** (`localStorage`)
- Consistent **Apply → Studio** CTA on Pathways, Explorer, Pharma, XAI, Combos, Omics

### 2. Simulation Studio (`/studio`)

**Network graph**

- SVG topology (zoom / pan / node drag)
- Scrub \(t_0 \rightarrow t_{60}\) without re-solving ODEs
- Knockout (\(y=0\)) or titration; Shift-click KO
- Impact & synergy · **Synthetic Lethality / Dual Screen**
- Node inspector: Knockout · Clamp · **Open 3D** · **Add to Combos**

**Spatial microenvironment mesh**

- Reaction–diffusion PDE on an \(N \times N\) tissue grid (O₂, VEGFA, TNF, DRUG)
- Click sources / drug sinks / tumor / erase
- **Load Histology Mask** — Visium / H&E-style geometry
- **BBB** toggle + MW / logP — barrier-limited drug exchange
- Organelle compartments synced to mesh time; HIF1A hypoxia import law

### 3. Disease Pathways (`/pathways`)

- Reactome search + ranked hits; one-click **Build**
- STRING interactome → `POST /api/v1/simulate-dynamic-graph`
- Provenance uses a short disease slug
- **Apply → Studio** after build
- Same protein impact explainers work for **any** disease you build — not only hypoxia

Same-origin proxies (hosted + local): `/proxy/reactome`, `/proxy/string-db`, and `/reactome` aliases (identity encoding so browsers do not choke on brotli).

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

### 12. Frontend services (`frontend/src/services/`)

| Module | Role |
| --- | --- |
| `pathwayApi.ts` | Reactome + STRING builders |
| `ptmIngestion.ts` / `massSpecParser.ts` | PTM + MaxQuant / FragPipe |
| `aiCausalEngine.ts` | Dual-target hypothesis cards |
| `reportExporter.ts` | Publication PDF/MD |
| `experimentSnapshots.ts` | Local experiment save / restore |

---

## Gene / protein explainers

Click any graph node → **Node Biophysics Inspector** → cards from `GET /api/v1/proteins/{symbol}`.

### Retrieve → explain (BioIE-style)

This follows the same *retrieve facts → explain in context* pattern as tools catalogued in [awesome-bioie](https://github.com/caufieldjh/awesome-bioie). We do **not** vendor that repo or load BioBERT/BioGPT weights on the free Render dyno (OOM).

Pipeline:

1. **Retrieve** facts from MyGene.info + UniProt (cached) — works for arbitrary human genes with **no API key**
2. Build a plain-English card: **what** / **why it matters** / **in this network**
3. Add a disease-agnostic **“If this protein changes…”** block:
   - Activity **up**
   - Activity **down / knockout**
   - **Structure / interaction** changes (mutation, binding, PTM) as edge rewiring
4. Optionally polish narratives via **Hugging Face Inference Providers** chat when `HF_TOKEN` is set  
   (`microsoft/biogpt` is **not** on HF serverless — default model is a small instruct chat model)

Hypoxia is only one Pathways scenario. Any Reactome/STRING disease you build gets the same impact reading, grounded in the current condition query + upstream/downstream neighbors.

In the inspector:

- Purple badge → **HF LLM narrative** / **HF LLM impact**
- Green badge → curated or network **template** (always available without a token)

---

## API surface

Base path: `/api/v1`

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Liveness (`cistron-api`) |
| `GET` | `/sources` | Knowledge-source catalogue (local, OmniPath, SIGNOR, KEGG, Reactome, STRING, BioGRID, UniProt, …) |
| `GET` | `/situations` | Curated situations for Explorer |
| `GET` | `/conditions/suggestions` | Condition query suggestions |
| `GET` | `/proteins/{symbol}` | Retrieve-grounded protein card + disease impact (`condition`, `upstream`, `downstream`, `delta_y`, `use_llm`) |
| `POST` | `/search-and-simulate` | Query → graph → Hill-cube ODE + XAI / topology |
| `POST` | `/simulate-dynamic-graph` | Browser-built Reactome+STRING interactome → full lab pipeline |
| `POST` | `/omics/upload` | Multipart CSV → `OmicsProfile` |
| `POST` | `/omics/simulate` | Profile → conditioned sim + alignment |

**Proxies (same origin)**

| Path | Upstream |
| --- | --- |
| `/proxy/reactome/{path}` | `https://reactome.org/` |
| `/proxy/string-db/{path}` | STRING API |
| `/reactome/{path}` | Reactome alias |

When `frontend/dist` exists, unmatched routes serve the Studio SPA.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        CISTRON VIRTUAL CELL LAB                          │
├────────────────────────────────┬─────────────────────────────────────────┤
│  Python (FastAPI + HillCube)   │  React VCL Studio (Vite)                │
│  search-and-simulate           │  Code rail · docks · SVG graph · spatial│
│  simulate-dynamic-graph        │  Combos · XAI · Omics · 3D · Snapshots  │
│  omics upload + simulate       │  Client engines + LabContext hub        │
│  proteins + disease impact     │  Apply → Studio workflows               │
│  topology · GAT · XAI          │  Node inspector · HF LLM polish (opt.)  │
│  Reactome / STRING proxies     │  Same-origin API when hosted            │
└────────────────────────────────┴─────────────────────────────────────────┘
```

**Hosted shape (Render Free):** one Python web service builds the Vite app in `scripts/render-build.sh`, then `uvicorn` serves API **and** `frontend/dist`.

---

## Python library map

The `cistron` package is a full computational-biology toolkit; the Studio API is the primary product surface.

| Path | Responsibility |
| --- | --- |
| [`cistron/engine/solver.py`](cistron/engine/solver.py) | Kraeutler Hill-cube ODE (server) |
| [`cistron/api/app.py`](cistron/api/app.py) | FastAPI gateway + SPA + proxies |
| [`cistron/api/gene_knowledge.py`](cistron/api/gene_knowledge.py) | MyGene + UniProt merge + cache |
| [`cistron/api/protein_explainer.py`](cistron/api/protein_explainer.py) | Fact-grounded protein cards |
| [`cistron/api/disease_impact.py`](cistron/api/disease_impact.py) | Activity / structure / PPI what-if text |
| [`cistron/api/biomed_llm.py`](cistron/api/biomed_llm.py) | Optional HF Inference Providers chat |
| [`cistron/data/`](cistron/data/) | Presets, resolver, multisource, omics parser |
| [`cistron/ai/`](cistron/ai/) | Prioritizer, scientist, XAI attributions |
| [`cistron/reasoner/`](cistron/reasoner/) | Causal BioReasoner briefs |
| [`cistron/integrations/`](cistron/integrations/) | UniProt, Reactome, STRING, cache, HTTP |
| [`cistron/omics/`](cistron/omics/) | PTM, metabolomics, FBA bridge, splicing, epigenomics |
| [`cistron/immuno/`](cistron/immuno/) | Checkpoints, neoantigens, TME kinetics |
| [`cistron/docking/`](cistron/docking/) | Structure parse + kinetics bridge |
| [`cistron/agent/`](cistron/agent/) | Planner, literature / causal reasoners, reports |
| [`frontend/src/lab/LabContext.tsx`](frontend/src/lab/LabContext.tsx) | Studio state hub |
| [`frontend/src/layout/`](frontend/src/layout/) | VCL shell, docks, palette |
| [`frontend/src/engine/`](frontend/src/engine/) | Client multi-scale engines |
| [`frontend/src/services/`](frontend/src/services/) | Pathways, PTM, causal AI, reports, snapshots |
| [`frontend/src/views/`](frontend/src/views/) | Route pages |
| [`docs/design/`](docs/design/) | VCL mockup HTML / assets |

Broader library modules (usable from Python even when not exposed as REST): Boolean + mass-action dual sim, compartments, pharmacology / toxicology, sensitivity (Sobol / Morris), optimization, graph ML, patient profiles, clinical benchmarks, HPC ensemble runner, Streamlit UI (`cistron-lab`).

---

## Deploy (free Render)

### Current blueprint (`render.yaml`)

**One** Free Python web service named `cistron`:

1. Build installs Node, runs `frontend` Vite build with same-origin `VITE_API_BASE=`
2. Installs the Python package (`scripts/render-build.sh`)
3. `uvicorn` serves API **and** the built Studio

**Steps**

1. In Render → **Services**, delete leftover `cistron*` rows from failed experiments  
   (Docker / split API+UI services stay Git-linked and redeploy on every push).
2. **New → Blueprint** → `gururajrao1/cistron` → apply `render.yaml` (only service: **`cistron`**).
3. Wait for build; open the single `*.onrender.com` URL (e.g. https://cistron.onrender.com).
4. Optional: set `HF_TOKEN` under **Environment** for LLM-polished protein narratives.

### Why earlier Blueprints failed

| Attempt | Why it failed |
| --- | --- |
| Docker web service | **Paid** on Render Free |
| Python API + static UI + `fromService` / `sync:false` | Blueprint validation / create-time env wiring |

---

## Environment variables

| Env var | Required? | Purpose |
| --- | --- | --- |
| `PORT` | Host-set | Listen port (Render injects this) |
| `PYTHON_VERSION` | Render | `3.11.11` in `render.yaml` |
| `NODE_VERSION` | Render build | `22.16.0` for Vite build |
| `HF_TOKEN` | No | Hugging Face token with **Inference** permission |
| `HF_BIOMED_MODEL` | No | Default `HuggingFaceTB/SmolLM3-3B-Instruct` |
| `HF_CHAT_URL` | No | Default `https://router.huggingface.co/v1/chat/completions` |
| `BIOMED_LLM_URL` | No | Your own TGI / vLLM / OpenAI-compatible GPU host |
| `BIOMED_LLM_MODEL` | No | Model id for custom endpoint |
| `VITE_API_BASE` | Frontend build | Empty string for same-origin hosted builds |

```bash
# Render → cistron → Environment
HF_TOKEN=hf_xxx
```

Do **not** load BioGPT/BioBERT weights inside the free Render web dyno.

---

## Typical workflows

**Hypoxia angiogenesis**

1. Pathways → search hypoxia → Build → **Apply → Studio**
2. Click HIF1A / EGLN1 / VEGFA → read protein + **If this protein changes…**
3. Right dock **Targets** → KO; scrub bottom dock; Scenario A/B for Δy
4. Combos → Dual Screen → apply pair; Spatial Mesh → histology + BBB; Export Report

**Any other disease pathway**

1. Pathways → search e.g. colorectal cancer / EGFR signalling → Build → Studio
2. Click a hub node — impact text uses **that** disease query + neighbors
3. Clamp / Knockout to simulate activity or loss-of-function

**Omics-conditioned run**

1. Omics → upload / example → Apply PTM \(y_0\) → **Apply → Studio**
2. Right dock **Omics** · header fit % · XAI Sobol

**First-time user**

1. Floating **First run** checklist (or Guide chip)
2. Header **Snap** before refreshing

---

## Tech stack

| Layer | Choices |
| --- | --- |
| API | FastAPI, Pydantic v2, Uvicorn, httpx / aiohttp |
| Numerics | NumPy, SciPy |
| Studio | React 19, Vite 8, TypeScript, Tailwind 4, Framer Motion |
| Viz | Recharts, Cytoscape, 3Dmol.js, jsPDF + html2canvas |
| Knowledge | MyGene.info, UniProt, Reactome, STRING (+ offline caches) |
| Optional LLM | HF Inference Providers chat (`router.huggingface.co`) |
| Hosting | Render Free (native Python) · Docker elsewhere |

---

## Roadmap

1. **Phase 1** — topology, dual sim, perturbations *(shipped)*
2. **Phase 2** — multi-omics, alignment, canvas heatmap *(shipped)*
3. **Phase 3** — spatial RD, histology/BBB, combos, Sobol XAI, report export *(shipped)*
4. **Phase 4** — VCL IDE shell, SVG graph, docks, snapshots, first-run guide *(shipped)*
5. **Phase 5** — universal protein explainers + disease-agnostic impact + HF LLM polish *(shipped)*
6. **Next** — full 3D PhysiCell-style PDE, SBML import, stochastic kinetics, clinical benchmarks

---

## Citation & license

Research software under **MIT**. Cite as appropriate for your paper:

- Kraeutler / Hill-cube continuous Boolean dynamics
- Bliss independence (combination synergy)
- Saltelli-style global sensitivity (Sobol)
- Continuum substrate / reaction–diffusion tissue models
- Upstream databases: Reactome, STRING, UniProt, MyGene.info

Reports and LLM narratives are assistive explanations grounded in retrieved or simulated context — verify before publication or clinical use.
