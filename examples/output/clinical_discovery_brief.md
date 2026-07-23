# Clinical Discovery Brief — Multi-Hit Oncology Benchmark

**VOIDSIGNAL** `0.11.0` · patient `CLIN_MULTIHIT_01`

## Clinical profile

- VCF: `multihit_clinical.vcf` (EGFR p.L858R, KRAS p.G12D, TP53 p.R213*)
- Expression: `clinical_expression.tsv`
- Vendored pathway hsa04010 nodes: 15
- Simulation baseline: `clinical_baseline:demo_mapk`
- Variants parsed: 3; mutations applied: 3
- Expression scales applied: 6
- Pre-treatment HSI: **0.7302**
- Post-treatment HSI: **0.3530**
- Literature Alignment Score (LAS): **0.5206**
- Agent objective met: **True**
- Readout species: `ERK`

### Structural disruption (δ)

- **EGFR** `p.L858R` · δ=1.000 · missense_variant · applied=True
- **KRAS** `p.G12D` · δ=1.000 · missense_variant · applied=True
- **TP53** `p.R213*` · δ=1.000 · stop_gained · applied=True

---

# VOIDSIGNAL Autonomous Research Brief

**Generated:** 2026-07-20 06:59 UTC  
**Agent:** BiologicalAgentPlanner  
**Patient / case id:** `CLIN_MULTIHIT_01`  
**Objective met:** YES  

---

## Abstract

We tasked an autonomous VOIDSIGNAL agent with the objective: *"Find a two-drug combination that halts ERK over-activation in a mutated EGFR background without exceeding the toxicity threshold"*. Working in a `cancer` phenotype with oncogene background **EGFR**, the planner selected **agent:MEK (C0=2.5), agent:RAF (C0=2.125)** to modulate readout **ERK**. Homeostatic Shift Index (treated vs baseline) reached **HSI=0.353**, Literature Alignment Score **LAS=0.521**, and the stated safety / efficacy objective was **satisfied**.

## Hypothesis

In a EGFR-driven cancer signalling background, a dual EGFR/MEK inhibition regimen can suppress ERK over-activation below pathogenic levels while respecting toxicity threshold 8.

*Parse confidence:* 0.98  
*Matched rules:* n_drugs=2 from combination language, readout=ERK, oncogenes=('EGFR',), disease=cancer, require_tox_safe, halt_overactivation, drug_candidates=('EGFR', 'MEK', 'RAF')

## Experimental Design

| Parameter | Value |
|-----------|-------|
| Readout | `ERK` |
| Disease preset | `cancer` |
| Oncogenes | EGFR |
| Drug count | 2 |
| Candidates | EGFR, MEK, RAF |
| Dose C₀ | 2.5 |
| Wash-in / washout | t∈[2, 15] |
| Horizon / dt | 20 / 0.5 |
| Toxicity threshold | 8 |
| Ensemble members | 4 |

### Workflow steps

1. **parse_goal** — Parse research objective into structured goal [done] confidence=0.98
2. **build_network** — Instantiate baseline signalling network [done] nodes=17
3. **disease_preset** — Apply disease preset 'cancer' with oncogenes ('EGFR',) [done] cancer_signaling
4. **target_prioritize** — Rank therapeutic targets via GAT / AIScientistReasoner [done] top=protein_f41e40f2da68
5. **drug_combination** — Screen two-drug combinations (Bliss/Loewe) under disease background [done] MEK+RAF effect_ab=0.498 bliss=-0.017 (additive)
6. **ensemble_sensitivity** — Monte Carlo ensemble (n=4) for uncertainty bands [done] success=4/4
7. **toxicology_audit** — Audit trajectories against toxicity threshold 8 [done] events=0 safe=True
8. **statistical_audit** — Welch t-tests on baseline vs treated readout windows [done] p=5.12e-09 d=-4.4 Δrel=-0.466
9. **literature_align** — Compute Literature Alignment Score against curated + KEGG evidence [done] LAS=0.521 (moderate literature concordance). Top simulated targets [TP53, EGFR, RAS] matched 25 curated evidence records (pathway coverage=0.86, synergy=0.15).
10. **synthesize_report** — Generate Markdown scientific research brief [done] chars=8568

### Selected dosing regimen

- `agent:MEK` → target `protein_3d73…` mechanism=competitive, C0=2.5, window=[2, 15.0]
- `agent:RAF` → target `protein_662c…` mechanism=competitive, C0=2.125, window=[2, 15.0]

Spatial routing uses the default DualEngine / MassActionRHS compartment boundary conditions inherited from the Phase 1–3 stack; no additional spatial overrides were injected by the agent.

## Results

- Disease steady-state **ERK** = **7.3831**
- Treated steady-state **ERK** = **3.7068**
- **HSI** = 0.3530 (collapse_flag=False)
- Top node shifts:
  - RAF: Δrel=0.742, contrib=0.742
  - MEK: Δrel=-0.563, contrib=0.563
  - EGFR: Δrel=-0.560, contrib=0.560
  - ERK: Δrel=-0.555, contrib=0.555
  - RAS: Δrel=-0.052, contrib=0.052

### Combination pharmacology

- Effect A / B / AB = 0.451 / 0.116 / 0.498
- Bliss expected = 0.515, Bliss excess = -0.017
- Loewe CI = n/a
- Interpretation: **additive**

### Monotherapy effects

- MEK: fractional inhibition ≈ 0.451
- RAF: fractional inhibition ≈ 0.116
- EGFR: fractional inhibition ≈ 0.000

### Toxicology

- Events flagged: **0**
- Tox-safe verdict: **True**

### Ensemble uncertainty

- Members succeeded: 4/4
- Note: Disease ERK=7.383 → treated=3.707 (reduction=49.8%)

## Statistical Auditing

| Entity | p-value | Cohen's d | Δrel | Significant |
|--------|---------|-----------|------|-------------|
| `protein_…` | 5.12e-09 | -4.4 | -0.466 | True |

Tests use Welch's *t* on post burn-in samples (`compare_trajectories`, Phase 6 statistics engine).

## Target Rationale (GAT + AIScientistReasoner)

| Rank | Symbol | Score |
|------|--------|-------|
| 1 | protein_f41e40f2da68 | 0.6485 |
| 2 | protein_118cc6440881 | 0.5486 |
| 3 | protein_5059d8dffa95 | 0.5486 |
| 4 | protein_dc99d7681e16 | 0.5486 |
| 5 | protein_3d73ff3931da | 0.5248 |
| 6 | protein_662cad47c5a5 | 0.5108 |
| 7 | protein_f3b9be9638da | 0.4933 |

### Edge-occlusion / feature attributions

**TP53** — score 0.64849566559904

Prioritize TP53 (score=0.648). Top features: binding=+0.125, boolean=+0.107, km=+0.071. Critical edge EGF→EGFR (Δ=+0.000). Feedback context: MEK→ERK→RAF→MEK.

Feature importance:
- binding: value=-2.267786838055363, attr=0.12473140338637062
- boolean: value=-2.2677868380553634, attr=0.10690600414205076
- km: value=2.2082097898955335, attr=0.07121396589767671
- in_degree: value=-1.224744871391589, attr=-0.04801977755468544
- betweenness: value=-1.2165006031411487, attr=0.04386418677111952

Critical edges:
- EGF→EGFR: Δ=0.0
- EGFR→RAS: Δ=0.0
- RAS→RAF: Δ=0.0
- RAF→MEK: Δ=0.0
- MEK→ERK: Δ=0.0

**EGFR** — score 0.5486364755314397

Prioritize EGFR (score=0.549). Top features: concentration=-0.000, boolean=+0.000, production=+0.000. Critical edge EGF→EGFR (Δ=-0.075). Feedback context: MEK→ERK→RAF→MEK.

Feature importance:
- concentration: value=-0.6255588549473973, attr=-0.0
- boolean: value=0.37796447300922736, attr=0.0
- production: value=2.2673322591115106, attr=0.0
- degradation: value=0.5698028822981894, attr=0.0
- vmax: value=1.1412422590670863, attr=0.0

Critical edges:
- EGF→EGFR: Δ=-0.07470148106674401
- EGFR→RAS: Δ=0.026727994046068515
- RAS→RAF: Δ=0.026727994046068515
- RAF→MEK: Δ=0.026727994046068515
- MEK→ERK: Δ=0.026727994046068515

**RAS** — score 0.5486364755314397

Prioritize RAS (score=0.549). Top features: concentration=+0.000, boolean=+0.000, production=-0.000. Critical edge RAS→RAF (Δ=+0.063). Feedback context: MEK→ERK→RAF→MEK.

Feature importance:
- concentration: value=1.3410230725295378, attr=0.0
- boolean: value=0.37796447300922736, attr=0.0
- production: value=-0.38684260023731604, attr=-0.0
- degradation: value=0.5698028822981894, attr=0.0
- vmax: value=0.405979121507466, attr=0.0

Critical edges:
- RAS→RAF: Δ=0.06259317381243595
- RAF→MEK: Δ=0.06259317381243595
- MEK→ERK: Δ=0.06259317381243595
- ERK→RAF: Δ=0.06259317381243595
- TP53→ERK: Δ=0.06259317381243595


## Literature Alignment

LAS=0.521 (moderate literature concordance). Top simulated targets [TP53, EGFR, RAS] matched 25 curated evidence records (pathway coverage=0.86, synergy=0.15).

- **LAS** = **0.521**
- Pathway coverage = 0.857
- Synergy literature alignment = 0.150
- Evidence hits = 25 / corpus 22

| Symbol | LASᵢ | Pathway | Drug-target | PPI |
|--------|------|---------|-------------|-----|
| TP53 | 0.205 | n | n | Y |
| EGFR | 0.925 | Y | Y | Y |
| RAS | 0.620 | Y | n | Y |
| EGF | 0.562 | Y | n | Y |
| MEK | 0.769 | Y | Y | Y |
| RAF | 0.614 | Y | n | Y |
| ERK | 0.561 | Y | n | Y |

### Supporting evidence

- (VOIDSIGNAL:topology) Simulation topology edge TP53→ERK (inhibition).
- (UniProt:P00533) EGFR is a receptor tyrosine kinase frequently mutated / amplified in cancer; constitutive signalling drives MAPK cascade hyperactivation.
- (PMID:15118073) EGFR tyrosine kinase inhibitors are clinically validated oncology drugs.
- (UniProt:P01112) RAS GTPases transmit EGFR signals to RAF; oncogenic RAS locks GTP-bound state.
- (STRING) STRING-supported physical / functional association with RAF in MAPK cascade.

## Conclusions

The autonomous campaign **met** the stated efficacy and safety constraints.

### Recommended next experiments

1. Validate top combination in an expanded dose-response grid.
2. Re-run Morris / Sobol sensitivity on selected kinetic parameters.
3. Cross-check LAS hits against live UniProt / STRING when network access is available.

Primary readout of interest remains **ERK** under **EGFR** pressure.

## Appendix — machine-readable summary

```json
{
  "success": true,
  "objective_met": true,
  "best_agents": [
    {
      "name": "agent:MEK",
      "target_id": "protein_3d73ff3931da",
      "dose": 2.5,
      "mechanism": "competitive",
      "t_start": 2.0,
      "t_end": 15.0
    },
    {
      "name": "agent:RAF",
      "target_id": "protein_662cad47c5a5",
      "dose": 2.125,
      "mechanism": "competitive",
      "t_start": 2.0,
      "t_end": 15.0
    }
  ],
  "hsi": 0.3529794100712854,
  "las": 0.5206437522807501,
  "tox_safe": true
}
```