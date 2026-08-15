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
| Hill-cube stiff integrator | **Done** — default `LSODA` |

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

Render Free may soft-fail the Vite build (`scripts/render-build.sh`). Check `GET /api/v1/health` → `database_handles.spa_built`.

## References (methods)

- Kraeutler et al. (2010) / Terfve et al. (2012) — Hill-cube / CellNOpt lineage  
- Bliss (1939); SynergyFinder — combination metrics  
- Saltelli / SALib — full QMC deferred; server uses numpy Saltelli-lite  
- PhysiCell — deferred spatial agent architecture  
