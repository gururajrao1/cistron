# Cistron Deep Research 2026 — Virtual Cellular Lab

Date: 2026-11-05. Repo: `https://github.com/gururajrao1/cistron` at `da592ae`, cloned to `C:\Users\gurur\Documents\cistron` (351 files, v0.21.0).
Scope: what Cistron is, domain SOTA, papers/journals/conferences/benchmarks, gaps, 12 feature suggestions, build plan.

## 1. What Cistron is

Interactive virtual cellular lab (research sandbox, NOT clinical): build disease pathway graphs
(Reactome/STRING/curated hypoxia-MAPK), Hill-cube ODE simulation (NumPy/SciPy LSODA) with
KO/clamp/dose + Bliss/Loewe combo screens, multi-omics clamping onto the active graph, illustrative
spatial reaction-diffusion mesh + BBB, Sobol-lite/parameter-force sensitivity, template Mechanistic
Briefs + retrieve-only literature copilot, 3D structure (UniProt/PDB/AlphaFold) + ChimeraX bridge,
client report export. Honesty rules: 422 on unmatched disease, no silent hypoxia fallback,
no fake GAT/SHAP (`README.md`, `docs/BLUEPRINT.md`).

Stack: Python 3.10+ FastAPI/pydantic/httpx/uvicorn; React 19/Vite 8/Tailwind 4 Studio in
`frontend/` (real deps: react-query, cytoscape/dagre, recharts, 3dmol, framer-motion, jspdf).
Legacy Streamlit `app.py` optional; `web/` is deprecated (kept for history, Dockerfile/render build
`frontend/` only). Entries: `uvicorn cistron.api.app:app` (port 8001 dev, 8000 prod single-process),
`cistron-run`, `cistron-lab`, `examples/mapk_demo.py`. Live: `https://cistron.onrender.com`
(sleeps ~15 min idle).

## 2. Domain foundations (knee-deep)

Core formalism: Kraeutler logic-based differential equations — normalized Hill
activation/inhibition functions with AND/OR gates for crosstalk (Kraeutler et al., BMC Syst Biol
2010, 4:157). Boolean-to-continuous via HillCube ODEs (Wittmann et al., BMC Syst Biol 2009, 3:98).
Tooling lineage: Netflux / logic-based ODE reviews (Clark et al. 2024; PLoS Comp Biol Netflux
2024-2025, 10.1371/journal.pcbi.1012864). Cistron implements this with LSODA
(`HillCubeConfig`: hill_n=3.0, ec50=0.5, rtol=1e-5, atol=1e-7, max_step=1.0).

Pathway/PPI sources: Reactome (2,769 human pathways, Mar 2025), STRING (functional + physical,
confidence-scored), BioGRID (curated physical/genetic), OmniPath (>100 resources, enzyme-PTM +
complexes, MIT), SIGNOR (causal), KEGG, Pathway Commons, UniProt offline. Benchmarking: Pathway
Commons best at recovering curated logic-model edges; Reactome/DIP highest precision P@k ~0.55-0.57
on held-out interactome task (Mol Syst Biol 2024; BioData Mining 2025 review).

Combos: Bliss independence vs Loewe additivity are the two nulls; ZIP/HSA/ComboScore/ALMANAC add
context. O'Neil (17,901 pairs, 38 drugs) and AZ-Sanger DREAM (11,576 expts, 910 pairs, 85 lines)
are the standard benchmarks; NCI-ALMANAC for clinic-anchored synergy. Each metric finds distinct
pairs; Bliss tracks clinically tested combos best (Menden et al.; Monem et al. BMC Bioinf 2024).

Eval culture (from paperswithcode): no single leaderboard for pathway simulators; de-facto sets are
O'Neil / DREAM / ALMANAC / NCI60; metrics AUROC/AUPRC + calibration + cold-start splits. Cistron
follows the same honesty pattern: template briefs, retrieve-only lit, explicit non-claims.

## 3. Papers / journals / conferences

Key papers: Kraeutler et al. 2010 (normalized-Hill LBODE); Wittmann et al. 2009 (HillCube);
Netflux logic-based modeling (PLoS Comp Biol 2024-2025); interactome benchmarking (State of the
interactomes, 2025; Benchmarking PPI DBs for signaling models, J Mol Biol 2024); synergy:
O'Neil, AZ-Sanger DREAM, NCI-ALMANAC multi-task synergy (AUC 0.89-0.95), CLC-Pred Synergy 2025.

Journals: Bioinformatics, PLoS Comp Biol, BMC Syst Biol / BMC Bioinf / BioData Mining, Mol Syst
Biol, npj Syst Biol, Cell Syst. Conferences: ISMB (2026 Washington DC Jul 12-16; 2025 Liverpool),
ECCB 2026 Geneva Aug 31-Sep 4, RECOMB 2026 Thessaloniki May 26-29, ISCB RegSysGen. All dates
verified via ISCB + Databio listings Nov 2026.

## 4. Gaps closed this session

1. `metadata.provenance.selected_sources` missing on `/api/v1/search-and-simulate` -> KeyError fail in
   `test_search_with_selected_sources`. Fixed in `cistron/api/app.py` (echo request sources, default
   `["local"]`) + regression test `test_search_provenance_echoes_default_sources`.
2. Version drift: API/schemas said 0.22.0, package truth 0.21.0 (`test_rich_entities`, `test_studio_ui`
   pin 0.21.0). Aligned API to 0.21.0.
3. `SYSTEM_CONTEXT.md` stale 0.12.0 -> 0.21.0 note; `web/` marked DEPRECATED (served Studio is
   `frontend/`); root `package.json` now delegates to `frontend/` scripts.
4. Reproducibility: `_run_engine` scrubber metadata now carries `solver` block (method LSODA, rtol,
   atol, hill_n, ec50, max_step, t_end, dense grid).

## 5. 12 domain-grounded feature suggestions

1. Combo agreement badge (Bliss + Loewe + replicate spread) per pair — O'Neil/DREAM convention.
2. OMOP-style positive/negative control eval page (curated sensitive/insensitive pairs, AUROC/AUPRC).
3. Confounder panel: cell-line/tissue context, passage/batch note, concomitant-perturbation warning.
4. Dose-time response matrices (Weibull-style kinetics analogue) instead of single-t_end snapshots.
5. Pathway-level DDI check: shared-node / compensatory-path flags for dual perturbations.
6. PGx-actionability drawer: variant (EGFR/KRAS/TP53) -> model-context note + Brief text.
7. Evidence drawer: Reactome + STRING confidence + PubMed retrieve-only quotes (no RAG claims).
8. Negative-control transparency: list insensitive nodes / failed combos explicitly.
9. Reproducible export: Brief + spec JSON (graph/params/solver/versions/seed) + honesty checklist.
10. Data roadmap: STRING confidence filter -> DepMap overlay -> LINCS L1000 link; defer SEC EDGAR.
11. Calibration + uncertainty: solver tolerances/seed + parameter-force spread as error bars.
12. Graph ML only when real: keep Sobol-lite + explicit no-GAT/SHAP label until implemented.

Non-goals (documented): full RAG, GAT/SHAP claims, COBRA FBA, Celery/Redis on free tier.

## 6. Build plan to working product

Step 0 reproduce: `pip install -e ".[dev]"`; `pytest -q`; `python examples/mapk_demo.py`;
`cd frontend && npm install && npm run dev` (5173) + uvicorn 8001; click graph->simulate->brief.
Step 1 hygiene (done above). Step 2 credibility: surface solver block in Studio + Brief; agreement
badge; negative-result display. Step 3 evidence/export: drawer links + spec JSON + PDF. Step 4 eval
harness with control set + CI gate. Step 5 data increments behind flags. Step 6 deploy smoke
(Render cold-start note) + `/api/v1/health` version assert. Acceptance: full pytest green, Studio
dev+prod verified, demo path recorded, honesty 422 paths covered.

## 7. Round 2 — eval harness, cache bound, type unblock (2026-11-05)

Implemented from section 5 items 2 (control eval) and 11 (calibration discipline):

- `cistron/benchmarks/pathway_controls.py`: 18 OMOP-style controls (10 positive
  query-to-readout pairs across 6 curated profiles, 8 absent-node negatives),
  pure-Python AUROC (Mann-Whitney, averaged ties) + AUPRC (average precision),
  per-case score floors and a 15 s wall budget. Observed on this tree:
  AUROC = 1.0, AUPRC = 1.0, slowest case 39 ms (queries grouped: 6 engine runs).
  Gate: `tests/test_eval_harness.py` (metric sanity + full gate).
- Known-weak documented in-module: TNBC readout AKT1 scores ~0.007 under the
  default EGF clamp (PI3K arm under-driven vs MAPK arm MAPK1 0.816 / MYC 0.589)
  and is excluded from the positive set until re-driven.
- Efficiency/robustness: `_DYNAMIC_GRAPHS` is now a FIFO-bounded cache
  (`MAX_DYNAMIC_GRAPHS = 128`, `cistron/api/app.py`) so the long-lived
  free-tier process cannot grow memory without limit; canonical writer is
  `_remember_graph`.
- Leftover fixed: `NavItem.phase` (`frontend/src/layout/SidebarNav.tsx`) —
  `tsc -b` is clean, which unblocks `npm run build`. `web/` stays deprecated
  (history only); root `package.json` delegates to `frontend/`.
- Not done: oxlint still reports 25 pre-existing warnings (none in touched
  lines); `web/` deletion deferred as destructive.

## 8. Round 3 — confounder panel + reproducibility spec (2026-11-05)

Implemented from section 5 items 3 (confounder panel), 8 (negative-result
transparency, partial) and 9 (standards-mapped export):

- `ModelContext` (cell_line / tissue / passage / batch_note, recorded not
  simulated) on `SearchAndSimulateRequest`; Studio `PerturbationPanel` gained a
  Model context form wired through `LabControls` into every search request.
- Same-node multi-class perturbations (KO+clamp, drug+clamp, drug+KO) and
  polypharmacy now raise masking warnings (`confounder_flags`), echoed in
  payload metadata, shown as amber flags in the panel, and appended to the
  Mechanistic Brief (`format_confounder_line`, same thread as the solver line).
- Export: `buildReproducibilitySpec` (graph + perturbations + solver + context
  + flags + honesty checklist + brief) with a Spec JSON download in the report
  modal; markdown/PDF reports gained Solver / Context rows and a
  Reproducibility & honesty checklist section.
- Verified: backend 234 passed, `tsc -b` clean, `npm run build` green,
  `oxlint` 0 errors (25 pre-existing warnings, none in touched lines).
