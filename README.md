# CISTRON


Research-grade computational biology platform — **Phase 1: Core Simulation & Network Engine**.

Pure-Python, zero hard dependencies. Dual-paradigm signalling on one shared graph:
discrete Boolean logic and continuous mass-action ODEs, with mid-run mutations and drug models.

---

## Architecture blueprint

```
┌──────────────────────────────────────────────────────────────────────┐
│                        CISTRON Phase 1                            │
├──────────────────────────────────────────────────────────────────────┤
│  components.py                                                       │
│    Gene · RNA · Protein · Complex · Ligand · Receptor · Compartment  │
│    Dual state: boolean_state  +  concentration                       │
│    EntityRegistry  (O(1) payload store)                              │
├──────────────────────────────────────────────────────────────────────┤
│  topology.py                                                         │
│    SignalingNetwork  — directed typed multigraph                     │
│    InteractionType   — activation, inhibition, phospho, …            │
│    Analytics         — hubs, feedback loops, crosstalk, robustness,  │
│                        betweenness; NetworkX-ready exporters         │
├──────────────────────────────────────────────────────────────────────┤
│  simulation.py                                                       │
│    BooleanSimulator  — AND/OR/NOT/MAJORITY/COPY + delay buffer       │
│    ODESimulator      — mass-action / Hill RHS · RK4 · adaptive Heun  │
│    DualEngineSimulator facade + Boolean→ODE hybrid hand-off          │
├──────────────────────────────────────────────────────────────────────┤
│  perturbation.py                                                     │
│    Mutation          — KO, constitutive ON/OFF, OE, hypomorph        │
│    DrugPerturbation  — competitive / non-competitive / uncompetitive │
│    PerturbationManager → hooks injected mid-trajectory               │
└──────────────────────────────────────────────────────────────────────┘
```

### Design contracts

| Concern | Choice |
| --- | --- |
| Identity | Stable `entity_id` / `edge_id`; graph stores IDs only |
| Dual state | Every node has Boolean + continuous fields; sync helpers bridge engines |
| Kinetics | Immutable `KineticParameters` with `with_updates` |
| Time | Shared `SimulationConfig`; hooks see `SimulationState(t, step)` |
| Extensibility | `to_edge_list` / `adjacency_matrix` / columnar trajectories |
| Perturbations | Compile to `PerturbationHook`; compose via manager |

### Data flow

```
EntityRegistry ──► SignalingNetwork (IDs + typed edges + NodeLogic)
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
  BooleanSimulator                 ODESimulator
  (logic gates, delays)         (mass-action RHS, RK4/Heun)
          │                             │
          └──────────► TrajectoryResult ◄──────────┘
                           ▲
                           │ PerturbationHook(t)
                    Mutation / Drug / RateOverride
```

---

## Install

```bash
cd cistron
pip install -e ".[dev]"
```

---

## Quickstart

```bash
python examples/mapk_demo.py
pytest
```

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
bool_traj = engine.run_boolean(SimulationConfig(boolean_steps=20, dt=1.0))

mgr = PerturbationManager()
mgr.knockout(ids["MEK"], t_start=5.0)
ode_traj = engine.run_ode(
    SimulationConfig(t_end=50.0, dt=0.05, stepper=ODEStepper.RK4),
    perturbation_hooks=mgr.hooks(),
)
```

---

## Module map

| File | Responsibility |
| --- | --- |
| [`cistron/components.py`](cistron/components.py) | Biological entities, kinetics, compartments, registry |
| [`cistron/topology.py`](cistron/topology.py) | Typed directed graph, motifs, hubs, robustness |
| [`cistron/simulation.py`](cistron/simulation.py) | Boolean + ODE engines, trajectories |
| [`cistron/perturbation.py`](cistron/perturbation.py) | Mutations, drugs, rate overrides, manager |

---

## Frontend (Enterprise Research Studio)

Decoupled React + Tailwind console (replaces the temporary Streamlit entrypoint for day-to-day research UX):

```bash
cd web
npm install
npm run dev
```

See [`web/DESIGN.md`](web/DESIGN.md) and [`web/README.md`](web/README.md). Mock API is on by default; set `VITE_API_BASE` to point at FastAPI.

## Phase roadmap

1. **Phase 1** — this engine (topology, dual sim, perturbations)
2. **Phase 2** — stochastic kinetics (Gillespie / tau-leaping), SBML import
3. **Phase 3** — graph algorithms at scale, community structure, control theory
4. **Phase 4** — visualisation adapters, parameter inference, multi-cell grids
5. **Phase 9–11** — Streamlit viz, AI Scientist agent, clinical benchmark, docking
6. **UI Studio** — React Research Studio (`web/`) with design-system tokens
