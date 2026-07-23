# Cistron

Research-grade computational biology platform — dual-paradigm signalling (Boolean + continuous ODEs) with a React Research Studio and **Phase 2 multi-omics conditioning**.

---

## What's in the box

| Layer | What you get |
| --- | --- |
| **Core engine** | Typed signalling graphs, Boolean + Hill-cube ODEs, knockouts / drugs mid-run |
| **FastAPI** | Search-and-simulate, sources/situations, omics upload + simulate |
| **Research Studio** | Cytoscape cascade canvas, scrubber trajectories, XAI / BioReasoner panels |
| **Omics (Phase 2)** | CSV DE upload, multi-sample profile library, alignment fit score, log2FC heatmap |

Repo: https://github.com/gururajrao1/cistron

---

## Quick start

### 1. API (prefer port **8001**)

```bash
cd cistron
pip install -e ".[dev]"
python -m uvicorn cistron.api.app:app --host 127.0.0.1 --port 8001
```

Health check: `http://127.0.0.1:8001/api/v1/health`

> Avoid `:8000` if an old VoidSignal process is still bound there — the Studio probes for `cistron-api` on **8001**.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173 — Studio (`/studio`), Omics (`/omics`), Explorer.

### 3. Engine smoke test

```bash
python examples/mapk_demo.py
pytest
```

---

## Phase 2 · Multi-omics

Condition the hypoxia cascade with differential expression tables.

### Upload & simulate

| Endpoint | Role |
| --- | --- |
| `POST /api/v1/omics/upload` | Parse CSV (`gene` / `symbol`, `log2FC`, `padj`) → `OmicsProfile` |
| `POST /api/v1/omics/simulate` | Map log2FC → Hill-cube baselines \(y_0\), run ODE to \(t_{60}\), return scrubber payload + **alignment score** |

**Alignment (Omics Fit Score %)** compares simulated steady states \(y(t_{60})\) to omics-mapped \(y_0\) (MSE + R² blend) and is returned as `alignment_score` on the simulate response.

### Studio UX

- **Omics page** — upload CSV or load **Hypoxia Core** / **Control** examples; switch conditions from the profile dropdown (auto re-simulates)
- **Canvas heatmap** — mapped nodes tint red (↑log2FC) / blue (↓log2FC); unmapped stay slate `#64748b`
- **Legend** — floating log2FC bar (−3 → 0 → +3) with active profile badge
- **Header** — “Omics-Conditioned” chip + fit %

CSV headers are normalized (BOM-safe); aliases include `Symbol`, `log2FoldChange`, `padj` / `FDR`.

---

## API surface (`/api/v1`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `GET` | `/sources` | Knowledge-source catalogue |
| `GET` | `/situations` | Situation catalogue for Explorer |
| `POST` | `/search-and-simulate` | Query → graph resolve → ODE + prioritization / XAI |
| `POST` | `/omics/upload` | Multipart CSV → profile |
| `POST` | `/omics/simulate` | Profile JSON → conditioned simulation |

CLI entrypoint: `cistron-api` (see `pyproject.toml`).

---

## Architecture (core engine)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        CISTRON                                        │
├──────────────────────────────────────────────────────────────────────┤
│  components.py                                                       │
│    Gene · RNA · Protein · Complex · Ligand · Receptor · Compartment  │
│    Dual state: boolean_state  +  concentration                       │
├──────────────────────────────────────────────────────────────────────┤
│  topology.py                                                         │
│    SignalingNetwork  — directed typed multigraph                     │
│    Analytics         — hubs, feedback, crosstalk, robustness         │
├──────────────────────────────────────────────────────────────────────┤
│  simulation.py                                                       │
│    BooleanSimulator  ·  ODESimulator  ·  DualEngineSimulator         │
├──────────────────────────────────────────────────────────────────────┤
│  perturbation.py                                                     │
│    Mutation · DrugPerturbation · PerturbationManager                 │
├──────────────────────────────────────────────────────────────────────┤
│  models/omics.py · data/omics_parser.py · api/app.py                 │
│    OmicsProfile · map_to_initial_states · calculate_alignment_score  │
└──────────────────────────────────────────────────────────────────────┘
```

### Design contracts

| Concern | Choice |
| --- | --- |
| Identity | Stable `entity_id` / `edge_id`; graph stores IDs only |
| Dual state | Every node has Boolean + continuous fields |
| Kinetics | Immutable `KineticParameters` with `with_updates` |
| Perturbations | Compile to `PerturbationHook`; compose via manager |
| Omics | Sigmoid map log2FC → \(y_0 \in [0.01, 0.99]\); fit vs \(y_{60}\) |

### Data flow

```
EntityRegistry ──► SignalingNetwork
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
  BooleanSimulator                 ODESimulator
          │                             │
          └──────────► TrajectoryResult ◄──────────┘
                           ▲
                           │ OmicsProfile / Mutation / Drug
```

---

## Module map

| Path | Responsibility |
| --- | --- |
| [`cistron/components.py`](cistron/components.py) | Entities, kinetics, registry |
| [`cistron/topology.py`](cistron/topology.py) | Typed graph, motifs, hubs |
| [`cistron/simulation.py`](cistron/simulation.py) | Boolean + ODE engines |
| [`cistron/perturbation.py`](cistron/perturbation.py) | Mutations, drugs, hooks |
| [`cistron/models/omics.py`](cistron/models/omics.py) | Profile, \(y_0\) map, alignment score |
| [`cistron/data/omics_parser.py`](cistron/data/omics_parser.py) | DE CSV parsing |
| [`cistron/api/app.py`](cistron/api/app.py) | FastAPI routes |
| [`frontend/`](frontend/) | Research Studio (Vite + React + Cytoscape) |

---

## Python engine snippet

```python
from cistron import (
    DualEngineSimulator,
    InteractionType,
    PerturbationManager,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    ODEStepper,
)

net = SignalingNetwork(name="mapk_toy")
ids = {}
for name, conc in [("EGF", 1.0), ("EGFR", 0.2), ("MEK", 0.1), ("ERK", 0.1)]:
    node = Protein(name=name, concentration=conc)
    net.add_node(node)
    ids[name] = node.entity_id

net.registry.get(ids["EGF"]).set_boolean(True)
net.connect(ids["EGF"], ids["EGFR"], InteractionType.ACTIVATION, rate_constant=1.2)
net.connect(ids["EGFR"], ids["MEK"], InteractionType.ACTIVATION, rate_constant=1.0)
net.connect(ids["MEK"], ids["ERK"], InteractionType.PHOSPHORYLATION, rate_constant=1.0)

engine = DualEngineSimulator(net)
mgr = PerturbationManager()
mgr.knockout(ids["MEK"], t_start=5.0)
ode_traj = engine.run_ode(
    SimulationConfig(t_end=50.0, dt=0.05, stepper=ODEStepper.RK4),
    perturbation_hooks=mgr.hooks(),
)
```

---

## Roadmap

1. **Phase 1** — topology, dual sim, perturbations *(shipped)*
2. **Phase 2** — multi-omics upload, alignment scoring, canvas heatmap *(shipped)*
3. **Phase 3** — stochastic kinetics (Gillespie / tau-leaping), SBML import
4. **Phase 4** — graph algorithms at scale, community structure, control theory
5. **Later** — parameter inference, multi-cell grids, clinical benchmark / docking
