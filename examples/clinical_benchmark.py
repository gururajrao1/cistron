"""
Real-world clinical benchmarking pipeline for CISTRON (Option A).

1. Load air-gapped MAPK pathway via VendoredPathwayRepository
2. Ingest multi-hit VCF (EGFR L858R, KRAS G12D, TP53 R213*) + RNA-seq folds
3. Build personalized PatientSignalingNetwork with AlphaFold δ kinetics
4. Run BiologicalAgentPlanner dual-agent objective (ERK suppression, tox ≤ 8)
5. Emit HSI / LAS metrics and save clinical_discovery_brief.md

Usage::

    python examples/clinical_benchmark.py
"""

from __future__ import annotations

from pathlib import Path
import copy
import logging
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("CISTRON_HEADLESS", "1")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cistron import ResearchGoal, __version__
from cistron.agent.planner import BiologicalAgentPlanner
from cistron.agent.reporter import ReportContext, ScientificReportGenerator
from cistron.benchmarks.clinical_data import (
    ClinicalIngestionEngine,
    write_expression_tsv,
    write_multihit_vcf,
)
from cistron.simulation import DualEngineSimulator, SimulationConfig
from cistron.pathology_metrics import homeostatic_shift_index

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("clinical_benchmark")

OUT_DIR = _ROOT / "examples" / "output"
BRIEF_PATH = OUT_DIR / "clinical_discovery_brief.md"
TELEMETRY_PATH = OUT_DIR / "clinical_benchmark_telemetry.json"


AGENT_GOAL = (
    "Find a two-drug combination that "
    "halts ERK over-activation in a mutated EGFR background "
    "without exceeding the toxicity threshold"
)


def _patient_network_factory(bundle):
    """Factory returning deep-copied patient network + name→id map for the agent."""

    def factory():
        net = copy.deepcopy(bundle.patient.network)
        ids = {}
        for ent in net.registry.entities():
            ids[ent.name] = ent.entity_id
            ids[ent.name.upper()] = ent.entity_id
            for a in ent.metadata.get("aliases") or []:
                ids[str(a)] = ent.entity_id
                ids[str(a).upper()] = ent.entity_id
            gs = ent.metadata.get("gene_symbol")
            if gs:
                ids[str(gs)] = ent.entity_id
                ids[str(gs).upper()] = ent.entity_id
        # Prefer phosphorylated / active MAPK readout for "ERK"
        for canon, aliases in {
            "ERK": ("MAPK1_P", "MAPK1", "ERK", "MAPK3"),
            "MEK": ("MAP2K1", "MEK", "MAP2K2", "MAP2K1_P"),
            "EGFR": ("EGFR",),
            "RAS": ("KRAS", "RAS", "HRAS", "NRAS"),
            "RAF": ("BRAF", "RAF", "RAF1"),
        }.items():
            for a in aliases:
                key = a if a in ids else a.upper()
                if key in ids:
                    ids[canon] = ids[key]
                    ids[canon.upper()] = ids[key]
                    break
        return net, ids

    return factory


def _resolve_readout_name(bundle) -> str:
    names = {e.name for e in bundle.patient.network.registry.entities()}
    for cand in ("MAPK1_P", "MAPK1", "ERK"):
        if cand in names:
            return cand
    return "ERK"

def main() -> int:
    print(f"CISTRON {__version__} — clinical benchmark (Option A)")
    print("=" * 64)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vcf_path = write_multihit_vcf(OUT_DIR / "multihit_clinical.vcf")
    expr_path = write_expression_tsv(OUT_DIR / "clinical_expression.tsv")
    print(f"[1] Wrote multi-hit VCF → {vcf_path}")
    print(f"    Wrote expression TSV → {expr_path}")

    # Air-gapped pathway proof (vendored KGML)
    from cistron.benchmarks.clinical_data import build_clinical_baseline

    vendored_net, vendored_ids, vw = build_clinical_baseline(
        pathway_id="hsa04010", prefer_vendored=True, fallback_demo=False
    )
    print(
        f"[1b] VendoredPathwayRepository hsa04010: "
        f"nodes={len(vendored_net.nodes())} edges={len(list(vendored_net.edges()))} "
        f"symbols={len(vendored_ids)}"
    )
    for w in vw:
        print(f"    warn: {w}")

    # Simulation baseline: demo MAPK cascade (proven DualEngine dynamics) + clinical TP53
    engine = ClinicalIngestionEngine(pathway_id="hsa04010", prefer_vendored=False)
    bundle = engine.ingest(
        patient_id="CLIN_MULTIHIT_01",
        vcf_path=vcf_path,
        expression=expr_path,
        apply_structure=True,
    )
    bundle.ingestion.metadata["vendored_nodes"] = len(vendored_net.nodes())
    bundle.ingestion.metadata["simulation_baseline"] = bundle.baseline.name
    ing = bundle.ingestion
    print(f"[2] Patient network: {bundle.patient.summary()}")
    print(
        f"    variants_parsed={ing.n_variants_parsed} mutations={ing.n_mutations_applied} "
        f"expression_scales={ing.n_expression_applied}"
    )
    print(f"    unresolved={ing.unresolved_genes or '[]'}")
    for w in ing.warnings:
        print(f"    warn: {w}")
    for hit in ing.structural_hits:
        print(
            f"    δ {hit.gene} {hit.hgvs_p}: disruption={hit.disruption:.3f} "
            f"applied={hit.applied} notes={hit.notes}"
        )

    # Baseline vs patient disease HSI (pre-treatment) — mutations already materialized
    cfg = SimulationConfig(t_end=14.0, dt=0.5, record_every=2)
    base_net = copy.deepcopy(bundle.baseline)
    base_traj = DualEngineSimulator(base_net).run_ode(cfg)
    dis_net = copy.deepcopy(bundle.patient.network)
    dis_traj = DualEngineSimulator(dis_net).run_ode(cfg)
    pre_hsi = homeostatic_shift_index(base_traj, dis_traj, dis_net, threshold=0.75)
    print(f"[3] Pre-treatment HSI (patient vs baseline) = {pre_hsi.hsi:.4f}")
    # Show readout levels
    rid_name = _resolve_readout_name(bundle)
    rid = next(
        (e.entity_id for e in dis_net.registry.entities() if e.name == rid_name),
        None,
    )
    if rid:
        print(
            f"    readout {rid_name}: baseline={base_traj.final_concentrations().get(rid, float('nan')):.4f} "
            f"patient={dis_traj.final_concentrations().get(rid, float('nan')):.4f}"
        )
    readout = _resolve_readout_name(bundle)
    print(f"[4] Launching BiologicalAgentPlanner (readout={readout})…")
    defaults = ResearchGoal(
        text=AGENT_GOAL,
        readout=readout,
        oncogenes=("EGFR", "RAS"),
        disease="none",
        n_drugs=2,
        drug_candidates=("MEK", "EGFR", "RAF"),
        dose=2.5,
        t_sim=20.0,
        dt=0.5,
        t_start=2.0,
        t_end=15.0,
        tox_threshold=8.0,
        ensemble_members=4,
        patient_id=bundle.patient.patient_id,
        halt_overactivation=True,
        require_tox_safe=True,
        metadata={"clinical_benchmark": True, "vendored_pathway": "hsa04010"},
    )
    planner = BiologicalAgentPlanner(network_factory=_patient_network_factory(bundle))
    plan = planner.plan(AGENT_GOAL, defaults=defaults)
    result = planner.run(AGENT_GOAL, defaults=defaults, plan=plan)

    print(f"    success={result.success} objective_met={result.objective_met}")
    if result.synergy:
        agents = " + ".join(a.name for a in result.best_agents)
        print(
            f"    combo={agents} effect_ab={result.synergy.effect_ab:.3f} "
            f"bliss={result.synergy.bliss_score:.3f} ({result.synergy.interpretation})"
        )
    post_hsi = result.hsi.hsi if result.hsi else float("nan")
    las = result.literature.las if result.literature else float("nan")
    print(f"[5] Post-treatment HSI={post_hsi:.4f}  LAS={las:.4f}")
    print(f"    tox_events={len(result.tox_events)} tox_safe={result.tox_safe}")
    for note in result.notes:
        print(f"    note: {note}")

    # Augment report with clinical preamble
    reporter = ScientificReportGenerator()
    md = reporter.generate(
        ReportContext(plan=result.plan, result=result, network=bundle.patient.network)
    )
    preamble = [
        "# Clinical Discovery Brief — Multi-Hit Oncology Benchmark",
        "",
        f"**CISTRON** `{__version__}` · patient `{bundle.patient.patient_id}`",
        "",
        "## Clinical profile",
        "",
        f"- VCF: `{vcf_path.name}` (EGFR p.L858R, KRAS p.G12D, TP53 p.R213*)",
        f"- Expression: `{expr_path.name}`",
        f"- Vendored pathway hsa04010 nodes: {len(vendored_net.nodes())}",
        f"- Simulation baseline: `{bundle.baseline.name}`",
        f"- Variants parsed: {ing.n_variants_parsed}; mutations applied: {ing.n_mutations_applied}",
        f"- Expression scales applied: {ing.n_expression_applied}",
        f"- Pre-treatment HSI: **{pre_hsi.hsi:.4f}**",
        f"- Post-treatment HSI: **{post_hsi:.4f}**",
        f"- Literature Alignment Score (LAS): **{las:.4f}**",
        f"- Agent objective met: **{result.objective_met}**",
        f"- Readout species: `{readout}`",
        "",
        "### Structural disruption (δ)",
        "",
    ]
    for hit in ing.structural_hits:
        preamble.append(
            f"- **{hit.gene}** `{hit.hgvs_p}` · δ={hit.disruption:.3f} · "
            f"{hit.consequence} · applied={hit.applied}"
        )
    preamble.extend(["", "---", "", md])
    brief = "\n".join(preamble)
    BRIEF_PATH.write_text(brief, encoding="utf-8")
    print(f"[6] Wrote discovery brief → {BRIEF_PATH} ({len(brief)} chars)")

    import json

    telemetry = {
        "version": __version__,
        "patient": bundle.as_dict(),
        "pre_hsi": pre_hsi.as_dict(),
        "agent": result.as_dict(),
        "brief_path": str(BRIEF_PATH),
    }
    TELEMETRY_PATH.write_text(json.dumps(telemetry, indent=2, default=str), encoding="utf-8")
    print(f"    Telemetry → {TELEMETRY_PATH}")
    print("=" * 64)
    print("Clinical benchmark OK" if result.success else "Clinical benchmark FAILED")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
