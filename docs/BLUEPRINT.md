# Cistron VCL — Free-safe scientific blueprint

Present-state integration of the master architecture under **Render Free** constraints.
No Celery/Redis, no React Flow rewrite, no fake RAG.

## Anti-heuristic manifesto (shipped)

| Rule | Status |
| --- | --- |
| No silent hypoxia fallback for unmatched queries | **Done** — HTTP 422 + suggestions |
| No synthetic A→B→C edge chains | **Done** — disconnected nodes stay isolated |
| Omics clamps onto **active** Studio/Pathways graph | **Done** — `graph_id` / inline topology; unmapped panel |
| Honest terminology (no GAT/SHAP/AI Scientist overclaim) | **Done** — Perturbation Sensitivity / Mechanistic Brief |
| Timeout → honest 504 (no silent local hypoxia) | **Done** |
| FAIR `sim_id` manifests | **Done** — response metadata + snapshot field |
| `/health` reports `spa_built` | **Done** |
| Bliss + Loewe labels | **Done** (math already present) |
| Hill-cube stiff integrator | **Done** — default `LSODA`, nonnegative clamp, dense `t_eval` |
| Server 2-compartment HIF1A translocation | **Done** — `cistron/engine/compartments.py` → payload.`compartments` |
| Single-source scrubber payload | **Done** — `time_steps` + `trajectories`/`nodes` + `compartments` |
| Wet-lab Insight Layer (Studio dock) | **Done** — rule/template translation of Δ + lab next steps (not an LLM) |
| ChimeraX desktop bridge | **Done** — Structure view exports `.cxc` + optional localhost REST remotecontrol |

## Wet-lab Insight Layer

Studio bottom tabs (Trajectory / Organelle / Flux / Compare) lead with:

1. A plain-English **headline** (timing, nuclear localization, metabolic phenotype)
2. **Δ badges** vs t₀ or untreated baseline
3. One **lab next step** (when to sample, fractionation, OCR/ECAR)

Raw tables and FBA vectors sit behind **Show numbers**. Chart shaded bands are **illustrative activity zones**, not clinical cutoffs. Translation is deterministic client rules over the server SoT scrubber — not a trained model inventing kinetics.

### View modes (header switcher)

| Mode | Default visibility |
| --- | --- |
| **Biologist** | Phenotype + wet-lab cards + gauges; pathway bubbles on map; hide charts/mesh/raw matrices |
| **Lab Researcher** (default) | Cards + trajectories + spatial mesh + drug controls |
| **Systems Math** | Researcher + raw tables / FBA vectors opened by default |

### Semantic zoom (network graph)

Shneiderman-style LOD on the Studio topology map:

1. **Zoomed out** — pathway program bubbles (Hypoxia/HIF, Glycolysis, Growth, …) with green/red health glow
2. **Mid zoom** — protein nodes + activation/inhibition edges (IPA-style semantic colors)
3. **Max zoom** — hover reveals live y(t), y₀, τ, inbound/outbound flux and a dy/dt sketch

Click a pathway bubble to zoom into its proteins. Biologist mode opens at the pathway LOD by default.

Trajectory charts use green / amber / red **phenotype zones** (Healthy · Transient stress · Pathogenic) with muted Y-axis ticks. Hover gauges for exact floats.

## Free-safe substitutes (shipped)

| Item | What shipped |
| --- | --- |
| Literature Copilot | `GET /literature/copilot` — retrieve-only PubMed + Reactome (no vector DB / Redis) |
| Saltelli-lite | `POST /sensitivity/saltelli` — numpy first-order / total-effect proxies (no SALib) |
| Mini FBA-lite | Client `solveMiniFbaLite` — glycolytic projection under enzyme capacities (not COBRA) |
| In-process jobs | `POST /jobs/search-and-simulate` + `GET /jobs/{id}` — thread-pool board (no Celery/Redis) |

## Explicitly deferred (not Free / not pretended)

| Item | Why deferred |
| --- | --- |
| Celery + Redis workers | Needs always-on Redis; Free is one process — use in-process jobs instead |
| PhysiCell agent–ODE coupling | Heavy; mesh remains illustrative RD |
| Full RAG / embeddings | Copilot is retrieve-only; Mechanistic Brief stays template |
| React Flow canvas | SVG already has live flux thickness; rewrite risks Studio |
| Genome-scale COBRA FBA | Mini FBA-lite only; labeled honestly |
| Auth / multi-tenant / durable server store | Out of Free scope |

## Hosting note

Render Free builds the Vite app in `scripts/render-build.sh`. A failed Studio build **aborts** the deploy (never ship API-only). Check `GET /api/v1/health` → `database_handles.spa_built` should be `true`.

## References (methods)

- Kraeutler et al. (2010) / Terfve et al. (2012) — Hill-cube / CellNOpt lineage  
- Bliss (1939); SynergyFinder — combination metrics  
- Saltelli / SALib — full QMC deferred; server uses numpy Saltelli-lite  
- PhysiCell — deferred spatial agent architecture  
