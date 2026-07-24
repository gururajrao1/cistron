# Cistron

Research-grade **virtual cellular laboratory** — Hill-cube ODE signalling, multi-omics conditioning, spatial reaction–diffusion, organelle compartments, synthetic lethality screening, XAI sensitivity, and publication-ready report export.

**Repo:** https://github.com/gururajrao1/cistron

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

## Studio navigation (sidebar)

| Route | Shortcut | What it does |
| --- | --- | --- |
| `/studio` | `1` | Simulation Studio — Cytoscape cascade, scrubber, perturbations, Dual Screen, spatial mesh toggle |
| `/pathways` | `2` | Disease Pathways — Reactome search + STRING interactome → dynamic graph simulate |
| `/explorer` | `3` | Network Builder — situations / sources catalogue |
| `/xai` | `4` | XAI & Global Sensitivity — Sobol \(S_i / S_{Ti}\), SHAP-force, GAT / server SHAP |
| `/pharmacology` | `5` | Pharmacology Lab |
| `/briefs` | `6` | Research Briefs — AI Scientist + BioReasoner |
| `/combinations` or `/combos` | `7` | Combination Therapy — Bliss synergy heatmap, synthetic lethality |
| `/omics` | `8` | Multi-omics — RNA-seq upload, MaxQuant/FragPipe PTM, metabolomics flux |
| `/biophysics` | `9` | 3D Structure — UniProt/PDB/AlphaFold + PTM residue selection |

Header **Export Report** opens the publication PDF / Markdown assembler.

---

## Features

### 1. Simulation Studio (`/studio`)

**Graph Topology (default)**

- Live Cytoscape cascade (capped node set for performance)
- Scrub \(t_0 \rightarrow t_{60}\) without re-solving ODEs (lerps scrubber keyframes)
- **Target perturbations** — knockout (\(y=0\)) or titration; Shift-click nodes to KO
- **Impact & synergy** — untreated vs treated \(\Delta y_{60}\); **Synthetic Lethality / Dual Screen** button
- **AI Scientist** panel — live brief, \(\Delta y\), attention reroutes
- **Causal Hypothesis Cards** — dual-KO / SL mechanism, phenotype, suggested assay (auto when ≥2 clamps or SL pairs)

**Spatial Microenvironment Mesh** (view toggle)

- Reaction–diffusion PDE on an \(N \times N\) tissue grid (O₂, VEGFA, TNF, DRUG)
- Click to place ligand **sources**, **drug sinks**, tumor, or erase
- **Load Histology Mask** — synthetic Visium / H&E geometry (tumor core, necrotic center, vascular shell, stroma, parenchyma)
- **Blood–Brain Barrier (BBB)** toggle + **MW (Da)** / **logP** sliders — barrier-limited drug exchange from vessels
- **Organelle compartments** (cytoplasm / nucleus / mitochondria) synced to **mesh time**, not the Studio scrubber
- HIF1A hypoxia law: `k_import = base × (1 − localO₂)` → nuclear accumulation

### 2. Disease Pathways (`/pathways`)

- Search Reactome pathways; rank hits; one-click **Build recommended**
- STRING network → Cytoscape-shaped interactome
- `POST /api/v1/simulate-dynamic-graph` runs the Hill-cube pipeline on the live graph
- Provenance badge uses a short disease slug (not the full Reactome title)

### 3. Multi-omics (`/omics`)

| Layer | How to use |
| --- | --- |
| **Transcriptomics (RNA-seq)** | Upload DE CSV (`gene`, `log2FC`, `padj`) or Hypoxia/Control examples → \(y_0 = \mathrm{sigmoid}(\mathrm{log2FC})\) |
| **Proteomics / Phospho-PTM** | Upload PTM table or **MaxQuant / FragPipe CSV**; stoichiometric occupancy \(y_0 = \mathrm{Base} \times \frac{I_\mathrm{phos}}{I_\mathrm{phos}+I_\mathrm{unmod}}\) |
| **Metabolomics** | Live ATP / Lactate / OCR pill from enzyme→metabolite Michaelis–Menten bridge (GLUT1, LDHA, PKM2, …) |
| **Overlay chart** | Transcript abundance vs phospho-active form across \(t_0 \rightarrow t_{60}\) |

Studio canvas shows log2FC **heatmap** (red ↑ / blue ↓) when an omics profile is active; header shows fit %.

Example DE file in repo root: [`hypoxia.csv`](hypoxia.csv).

### 4. 3D Structure (`/biophysics`)

- Resolves UniProt → best PDB (or AlphaFold)
- Click residues or phospho-site chips (e.g. HIF1A Ser643) via `?symbol=HIF1A&resi=643`
- Color by SS / chain / B-factor; optional surface

### 5. Combination Therapy (`/combinations`, `/combos`)

- **Client Dual Screen** — pairwise Hill-cube KOs; Bliss synergy \(S = E_A + E_B - E_{AB}\)
- Heatmap: click a cell → apply dual KO on Studio
- **Server SL scan** — backend topological synthetic-lethality pairs
- Hypothesis cards for top SL / dual-clamp mechanisms

### 6. XAI & Sensitivity (`/xai`)

- **Run Sobol / SHAP-force** — first-order \(S_i\) and total-effect \(S_{Ti}\) vs targets (VEGFA, GLUT1, …)
- Parameter force bars: \(k_\mathrm{cat}\), \(\tau\), transport, degradation
- Influence scatter \(S_i\) vs \(\Delta y\)
- Server SHAP node importance + master regulators (GAT)

### 7. Export Report (header)

Assembles a multi-section PDF/Markdown from live Lab state:

- Abstract, network topology (canvas snapshot), biophysical trajectories
- Target ID / perturbations, provenance, SL findings, causal hypotheses
- Methods citations (Hill cubes, Bliss, Saltelli, spatial RD / BBB)

Uses `jspdf` + `html2canvas` (ASCII-safe PDF fonts).

### 8. Client engines (`frontend/src/engine/`)

| Module | Role |
| --- | --- |
| `compartmentOde.ts` | Multi-compartment Hill-cube (cyto / nuc / mito) + translocation |
| `diffusionGrid.ts` | Finite-difference reaction–diffusion mesh |
| `spatialHistologyLoader.ts` | Visium / H&E-style cell-type masks + IFP / O₂ BCs |
| `barrierKinetics.ts` | BBB permeability from logP, MW, P-gp; vessel↔tissue flux |
| `comboScreen.ts` | Pairwise dual-KO Bliss screen |
| `sensitivityXAI.ts` | Sobol-lite + SHAP-force attributions |
| `metabolicBridge.ts` | Enzyme \(y(t)\) → metabolite fluxes (MM / FBA-style bounds) |

### 9. Services (`frontend/src/services/`)

| Module | Role |
| --- | --- |
| `pathwayApi.ts` | Reactome + STRING interactome builders |
| `ptmIngestion.ts` | Phospho-site CSV + Boltzmann \(y_0\) |
| `massSpecParser.ts` | MaxQuant / FragPipe LC-MS/MS occupancy |
| `aiCausalEngine.ts` | Dual-target causal hypothesis cards + LLM prompt |
| `reportExporter.ts` | Publication PDF/MD assembly |

---

## API surface (`/api/v1`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Liveness (`cistron-api`) |
| `GET` | `/sources` | Knowledge-source catalogue |
| `GET` | `/situations` | Situation catalogue |
| `POST` | `/search-and-simulate` | Query → graph → ODE + prioritization / XAI / topology |
| `POST` | `/simulate-dynamic-graph` | Client interactome → full lab pipeline |
| `POST` | `/omics/upload` | Multipart CSV → `OmicsProfile` |
| `POST` | `/omics/simulate` | Profile → conditioned sim + `alignment_score` |
| `POST` | `/reasoner/brief` | Causal paths + narrative (optional) |

CLI entrypoint: `cistron-api` (see `pyproject.toml`).

Vite proxies API + Reactome/STRING (see `frontend/vite.config.ts`).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CISTRON VIRTUAL CELL LAB                         │
├───────────────────────────────┬─────────────────────────────────────────┤
│  Python (FastAPI + HillCube)  │  React Studio (Vite)                    │
│  search-and-simulate          │  Studio / Pathways / Omics / XAI / 3D   │
│  omics upload + simulate      │  Spatial mesh · Combos · Export Report  │
│  dynamic-graph pipeline       │  Client engines (ODE / RD / Sobol / SL) │
│  topology · GAT · XAI         │  LabContext hub                         │
└───────────────────────────────┴─────────────────────────────────────────┘
```

### Design contracts

| Concern | Choice |
| --- | --- |
| Identity | Stable gene symbols on graph nodes/edges |
| Kinetics | Hill-cube ODE; scrubber keyframes \(t=0\ldots60\) |
| Perturbations | Interactive clamps \(y \in [0,1]\); \(0\) = KO |
| Omics | Sigmoid / Boltzmann log2FC → \(y_0\); PTM occupancy multipliers |
| Spatial | Mesh clock drives organelles; Lab scrubber drives graph playback |
| PDF | ASCII sanitization for built-in jsPDF fonts |

---

## Typical workflows

**Hypoxia angiogenesis**

1. Pathways → search “hypoxia” / angiogenesis → Build recommended  
2. Studio → scrub trajectories; KO HIF1A or VEGFA  
3. Dual Screen or Combos → Client Dual Screen → apply synergistic pair  
4. Spatial Mesh → Load Histology Mask; lower O₂ bias; watch nuclear HIF1A  
5. Export Report → PDF  

**Omics-conditioned run**

1. Omics → example Hypoxia Core (or upload CSV / MaxQuant) → Apply PTM \(y_0\)  
2. Studio canvas shows log2FC heatmap; header shows fit %  
3. XAI → Run Sobol / SHAP-force on VEGFA/GLUT1 drivers  

**CNS drug penetration**

1. Spatial Mesh → Load Histology Mask  
2. Enable **BBB**; set MW / logP; place DRUG sinks near vessels  
3. Watch barrier-limited drug field vs peripheral mode  

---

## Module map

| Path | Responsibility |
| --- | --- |
| [`cistron/engine/solver.py`](cistron/engine/solver.py) | Kraeutler Hill-cube ODE (server) |
| [`cistron/api/app.py`](cistron/api/app.py) | FastAPI routes |
| [`cistron/models/omics.py`](cistron/models/omics.py) | Omics profile, \(y_0\) map, alignment |
| [`frontend/src/lab/LabContext.tsx`](frontend/src/lab/LabContext.tsx) | Studio state hub |
| [`frontend/src/engine/`](frontend/src/engine/) | Client multi-scale engines |
| [`frontend/src/services/`](frontend/src/services/) | Pathways, PTM, MS, causal AI, reports |
| [`frontend/src/views/`](frontend/src/views/) | Route pages |

---

## Roadmap

1. **Phase 1** — topology, dual sim, perturbations *(shipped)*
2. **Phase 2** — multi-omics, alignment, canvas heatmap *(shipped)*
3. **Phase 3** — spatial RD, histology/BBB, organelle compartments, combos, Sobol XAI, report export *(shipped)*
4. **Next** — full 3D PhysiCell-style PDE, SBML import, stochastic kinetics, clinical benchmarks

---

## License / citation

Research software. Auto-generated reports are **not** peer-reviewed manuscripts. Cite Kraeutler Hill cubes, Bliss independence, Saltelli global sensitivity, and continuum substrate models as appropriate for your paper.
