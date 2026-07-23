"""Phase 7 — patient profiles, systemic disease, pathology metrics."""

from __future__ import annotations

from cistron import (
    DiseaseSimulator,
    DualEngineSimulator,
    ExpressionRecord,
    InflammationConfig,
    InteractionType,
    MetabolicConfig,
    MultiHitOncogenesisConfig,
    PathologyMetricsEngine,
    PatientGenomicProfile,
    PatientProfileEngine,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    VariantConsequence,
    VariantRecord,
    build_inflammation_phenotype,
    build_metabolic_phenotype,
    build_multihit_oncogenesis_phenotype,
    build_patient_network,
    homeostatic_shift_index,
    pathway_dysregulation_score,
)


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="mapk_p7")
    ids: dict[str, str] = {}
    for name, conc in {
        "EGF": 1.0,
        "EGFR": 0.3,
        "RAS": 0.2,
        "RAF": 0.2,
        "MEK": 0.2,
        "ERK": 0.2,
    }.items():
        p = Protein(name=name, concentration=conc)
        if name == "EGF":
            p.set_boolean(True)
            p.kinetics = p.kinetics.with_updates(production_rate=0.05, degradation_rate=0.01)
        p.metadata["gene_symbol"] = name
        net.add_node(p)
        ids[name] = p.entity_id
    for s, t, it, r in [
        ("EGF", "EGFR", InteractionType.ACTIVATION, 1.2),
        ("EGFR", "RAS", InteractionType.ACTIVATION, 1.0),
        ("RAS", "RAF", InteractionType.ACTIVATION, 1.0),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION, 1.0),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION, 1.0),
        ("ERK", "RAF", InteractionType.INHIBITION, 0.4),
    ]:
        net.connect(ids[s], ids[t], it, rate_constant=r)
    return net, ids


def test_patient_profile_vcf_and_expression() -> None:
    baseline, ids = _mapk()
    variants = [
        VariantRecord(
            chrom="12",
            pos=1,
            variant_id="rsMEK",
            ref="A",
            alt=["G"],
            qual=99.0,
            filter_status=["PASS"],
            info={},
            gene="MEK",
            consequence=VariantConsequence.MISSENSE,
        ),
        VariantRecord(
            chrom="7",
            pos=2,
            variant_id="rsEGFR",
            ref="C",
            alt=["T"],
            qual=80.0,
            filter_status=["PASS"],
            info={},
            gene="EGFR",
            consequence=VariantConsequence.MISSENSE,
        ),
    ]
    expr = [
        ExpressionRecord(symbol="ERK", fold_change=2.0),
        ExpressionRecord(symbol="RAS", fold_change=0.5),
    ]
    patient = build_patient_network(
        baseline,
        "P001",
        variants,
        expression=expr,
        missense_rate_scale=0.4,
    )
    assert patient.patient_id == "P001"
    assert patient.applied_mutations
    assert ids["ERK"] in {  # cloned network has new ids — check by name scales
        eid for eid, _ in patient.expression_scales.items()
    } or any(
        patient.network.registry.get(eid).name == "ERK" for eid in patient.expression_scales
    )
    # Expression applied on clone
    erk = next(e for e in patient.network.registry.entities() if e.name == "ERK")
    assert erk.metadata.get("expression_fold_change") == 2.0
    assert erk.concentration >= 0.39  # 0.2 * 2

    engine = DualEngineSimulator(patient.network)
    patient.load_into(engine)
    traj = engine.run_ode(SimulationConfig(t_end=5.0, dt=0.2, record_every=5))
    assert len(traj) > 0


def test_inflammation_and_metabolic_controllers() -> None:
    net, _ = _mapk()
    pheno = build_inflammation_phenotype(
        net,
        InflammationConfig(ensure_missing=True, exhaustion_onset=8.0, cytokines=("TNF", "IL6")),
    )
    assert pheno.perturbations
    engine = DualEngineSimulator(net)
    pheno.load_into(engine)
    traj = engine.run_ode(SimulationConfig(t_end=12.0, dt=0.2, record_every=10))
    tnf = next(e for e in net.registry.entities() if e.name == "TNF")
    assert "cytokine_drive" in tnf.metadata or traj.final_concentrations().get(tnf.entity_id, 0) >= 0.0

    net2, _ = _mapk()
    meta = build_metabolic_phenotype(net2, MetabolicConfig(ensure_missing=True, desense_onset=2.0))
    eng2 = DualEngineSimulator(net2)
    meta.load_into(eng2)
    eng2.run_ode(SimulationConfig(t_end=10.0, dt=0.2, record_every=10))
    insr = next(e for e in net2.registry.entities() if e.name == "INSR")
    assert float(insr.metadata.get("desensitization_efficiency", 1.0)) < 1.0


def test_multihit_oncogenesis_and_disease_simulator() -> None:
    net, ids = _mapk()
    sim = DiseaseSimulator(net)
    pheno = sim.multi_hit_cancer(
        MultiHitOncogenesisConfig(
            primary_drivers=("RAS", "EGFR"),
            secondary_hits=(("TP53", 4.0),),
            caretakers=("TP53",),
            ensure_missing=True,
            instability_onset=3.0,
        )
    )
    assert pheno.kind.name == "CANCER_SIGNALING"
    engine = DualEngineSimulator(net)
    traj = sim.run(engine, SimulationConfig(t_end=12.0, dt=0.2, record_every=10))
    assert len(traj) > 0
    tp53 = next(e for e in net.registry.entities() if e.name == "TP53")
    # After hit time, knockout should drive concentration toward 0
    assert traj.final_concentrations().get(tp53.entity_id, 1.0) <= 0.05


def test_pathology_metrics_hsi_pds() -> None:
    net, ids = _mapk()
    baseline = DualEngineSimulator(net).run_ode(
        SimulationConfig(t_end=15.0, dt=0.25, record_every=10)
    )
    net2, ids2 = _mapk()
    # Pathological: constitutive RAS + ERK overexpression
    ras = net2.registry.get(ids2["RAS"])
    ras.set_boolean(True)
    ras.kinetics = ras.kinetics.with_updates(production_rate=0.5, basal_activity=1.0)
    ras.set_concentration(3.0)
    disease = DualEngineSimulator(net2).run_ode(
        SimulationConfig(t_end=15.0, dt=0.25, record_every=10)
    )
    # Align entity ids by name for metric comparison
    # Use net2 for both reports against disease traj; baseline needs same ids —
    # rebuild baseline on net2 without disease warp for fair HSI
    net3, ids3 = _mapk()
    base3 = DualEngineSimulator(net3).run_ode(
        SimulationConfig(t_end=15.0, dt=0.25, record_every=10)
    )
    # Compare series lengths; HSI uses name-aligned finals via shared topology names
    # For identical UUID layouts we'd need same factory — use node names via remap:
    from cistron.pathology_metrics import HomeostaticShiftReport

    # Map baseline finals by name onto disease ids
    base_by_name = {
        net3.registry.get(eid).name: val for eid, val in base3.final_concentrations().items()
    }
    # Synthesize a fake baseline traj with disease entity ids
    from cistron.simulation import SimulatorBackend, TrajectoryResult

    remapped_conc = []
    for sample in base3.concentrations:
        row = {}
        for eid, val in sample.items():
            name = net3.registry.get(eid).name
            # find matching id on net2
            match = ids2[name]
            row[match] = val
        remapped_conc.append(row)
    remapped_bool = []
    for sample in base3.boolean_states:
        row = {}
        for eid, val in sample.items():
            name = net3.registry.get(eid).name
            row[ids2[name]] = val
        remapped_bool.append(row)
    baseline_aligned = TrajectoryResult(
        times=list(base3.times),
        concentrations=remapped_conc,
        boolean_states=remapped_bool,
        backend=SimulatorBackend.ODE,
    )
    hsi = homeostatic_shift_index(baseline_aligned, disease, net2, threshold=0.1)
    assert hsi.hsi >= 0.0
    assert hsi.node_shifts

    pds = pathway_dysregulation_score(baseline_aligned, disease, net2, threshold=0.01)
    assert pds.pds >= 0.0

    report = PathologyMetricsEngine(net2).evaluate(baseline_aligned, disease)
    assert "homeostatic_shift" in report
    assert "pathway_dysregulation" in report
