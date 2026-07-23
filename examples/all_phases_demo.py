"""Live smoke demos for CISTRON Phases 1–8."""

from __future__ import annotations

from cistron import (
    CancerSignalingConfig,
    CentralDogmaEngine,
    CompartmentTier,
    DiseaseSimulator,
    DualEngineSimulator,
    EncoderKind,
    EnsembleRunner,
    ExpressionRecord,
    FitTarget,
    Gene,
    GraphExplainer,
    InflammationConfig,
    InhibitionModel,
    InteractionType,
    LocalSensitivityAnalyzer,
    LogicGate,
    NodeLogic,
    ODEStepper,
    ParameterEstimator,
    ParameterSpec,
    PathologyMetricsEngine,
    PatientProfileEngine,
    PerturbationManager,
    PharmacokineticProfile,
    Protein,
    RNA,
    SafetyPathway,
    SafetyTarget,
    SafetyTargetPanel,
    SignalingNetwork,
    SimulationConfig,
    SimulationStore,
    SimulatorBackend,
    SpatialCompartmentModel,
    StructuralDomain,
    StructuralMap,
    StructureAwareModulator,
    BindingPocket,
    TargetDiscoveryModel,
    ToxicologyMonitor,
    TrajectoryResult,
    ThresholdDirection,
    VariantConsequence,
    VariantRecord,
    VendoredPathwayRepository,
    __version__,
    build_cancer_phenotype,
    build_graph_tensors,
    build_patient_network,
    consequence_to_mapping,
    create_default_registry,
    homeostatic_shift_index,
    welch_ttest,
)


def mapk(name: str = "mapk") -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name=name)
    ids: dict[str, str] = {}
    for n, c in {
        "EGF": 1.0,
        "EGFR": 0.3,
        "RAS": 0.2,
        "RAF": 0.2,
        "MEK": 0.2,
        "ERK": 0.2,
    }.items():
        p = Protein(name=n, concentration=c)
        if n == "EGF":
            p.set_boolean(True)
            p.kinetics = p.kinetics.with_updates(production_rate=0.05, degradation_rate=0.01)
        p.metadata["gene_symbol"] = n
        net.add_node(p)
        ids[n] = p.entity_id
    for s, t, it, r in [
        ("EGF", "EGFR", InteractionType.ACTIVATION, 1.2),
        ("EGFR", "RAS", InteractionType.ACTIVATION, 1.0),
        ("RAS", "RAF", InteractionType.ACTIVATION, 1.0),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION, 1.0),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION, 1.0),
        ("ERK", "RAF", InteractionType.INHIBITION, 0.35),
    ]:
        net.connect(ids[s], ids[t], it, rate_constant=r)
    net.set_node_logic(ids["ERK"], NodeLogic(gate=LogicGate.OR, inhibitor_veto=True))
    return net, ids


def main() -> None:
    print("=" * 64)
    print(f"CISTRON v{__version__} — Phases 1-8 live smoke demos")
    print("=" * 64)

    # Phase 1
    print("\n### PHASE 1 — Core engine")
    net, ids = mapk("p1")
    summary = net.summary()
    print(
        f"  topology: {summary['n_nodes']} nodes, {summary['n_edges']} edges, "
        f"loops={len(net.detect_feedback_loops())}"
    )
    eng = DualEngineSimulator(net)
    bt = eng.run_boolean(SimulationConfig(boolean_steps=20, dt=1.0))
    print(f"  Boolean ERK final: {bt.final_boolean()[ids['ERK']]}")
    net2, ids2 = mapk("p1b")
    eng2 = DualEngineSimulator(net2)
    mgr = PerturbationManager()
    mgr.knockout(ids2["MEK"], t_start=10.0)
    mgr.dose(ids2["RAF"], concentration=3.0, ki=0.4, t_start=20.0, t_end=35.0)
    ot = eng2.run_ode(
        SimulationConfig(t_end=50.0, dt=0.1, record_every=25, stepper=ODEStepper.RK4),
        mgr.hooks(),
    )
    fin = ot.final_concentrations()
    print(
        f"  ODE finals: MEK={fin[ids2['MEK']]:.4f} ERK={fin[ids2['ERK']]:.4f} "
        "(MEK KO expected ~0)"
    )

    # Phase 2
    print("\n### PHASE 2 — Data / VCF mapping")
    m = consequence_to_mapping(VariantConsequence.MISSENSE)
    print(f"  missense -> {m.kind.name} rate_scale={m.rate_scale}")
    m2 = consequence_to_mapping(VariantConsequence.STOP_GAINED)
    print(f"  stop_gained -> {m2.kind.name}")
    vp = VendoredPathwayRepository()
    print(f"  VendoredPathwayRepository: {type(vp).__name__}")

    # Phase 3
    print("\n### PHASE 3 — Structure / dogma / compartments")
    smap = StructuralMap(
        protein_id="EGFR",
        sequence_length=1210,
        domains=[StructuralDomain("Kinase", 712, 979, kind="catalytic")],
        pockets=[BindingPocket("ATP", residues=(745, 746, 747), radius_angstrom=5.0)],
    )
    mod = StructureAwareModulator()
    mod.register(smap)
    hit, scales = mod.evaluate_variant("EGFR", 746)
    print(
        f"  structure pocket hit disruption={hit.disruption:.3f} "
        f"kcat_scale={scales.kcat_scale:.3f}"
    )
    g = Gene(name="G", transcription_rate=1.0, promoter_strength=1.0, concentration=1.0)
    g.set_boolean(True)
    r = RNA(
        name="R",
        source_gene_id=g.entity_id,
        translation_rate=1.0,
        half_life=5.0,
        concentration=0.0,
    )
    pr = Protein(name="P", concentration=0.0, sequence_length=100)
    r.product_protein_id = pr.entity_id
    pr.source_rna_id = r.entity_id
    g.expressed_rna_id = r.entity_id
    r.metadata["sequence_length"] = 300
    dnet = SignalingNetwork(name="dogma")
    dnet.add_node(g)
    dnet.add_node(r)
    dnet.add_node(pr)
    dogma = CentralDogmaEngine(dnet, nt_per_time=500.0, aa_per_time=100.0)
    chains = dogma.discover_chains()
    print(f"  dogma chains={len(chains)} tx_delay={chains[0].transcription_delay:.3f}")
    net3, ids3 = mapk("p3")
    spatial = SpatialCompartmentModel(net3)
    spatial.ensure_default_tiers()
    spatial.assign(ids3["EGF"], CompartmentTier.EXTRACELLULAR)
    spatial.assign(ids3["EGFR"], CompartmentTier.PLASMA_MEMBRANE)
    spatial.assign(ids3["RAS"], CompartmentTier.CYTOPLASM)
    print("  spatial tiers assigned for EGF/EGFR/RAS")

    # Phase 4
    print("\n### PHASE 4 — Disease / pharmacology / tox")
    net4, ids4 = mapk("p4")
    ph = build_cancer_phenotype(
        net4,
        CancerSignalingConfig(
            oncogenes=("RAS", "EGFR"),
            survival_nodes=("ERK",),
            expression_level=2.5,
        ),
    )
    print(f"  cancer phenotype perturbations: {len(ph.perturbations)}")
    pk = PharmacokineticProfile(dose=2.0, volume=1.0, kel=0.2, dosing_times=[0.0])
    print(f"  PK C(0)={pk.concentration(0.0):.3f} C(5)={pk.concentration(5.0):.3f}")
    panel = SafetyTargetPanel().add(
        SafetyTarget(
            ids4["ERK"],
            SafetyPathway.DNA_DAMAGE,
            0.3,
            ThresholdDirection.ABOVE,
            name="ERK",
        )
    )
    mon = ToxicologyMonitor(panel, cooldown=0.5)
    eng4 = DualEngineSimulator(net4)
    mon.attach(eng4)
    ph.load_into(eng4)
    eng4.run_ode(SimulationConfig(t_end=15.0, dt=0.2, record_every=10))
    rep = mon.report()
    print(f"  tox events={len(rep.events)} tox_index={rep.tox_index:.3f} safe={rep.safe}")

    # Phase 5
    print("\n### PHASE 5 — Graph ML / XAI")
    net5, ids5 = mapk("p5")
    tensors = build_graph_tensors(net5, normalize="zscore")
    print(
        f"  tensors X={tensors.num_nodes}x{tensors.num_node_features} "
        f"edges={tensors.num_edges}"
    )
    model = TargetDiscoveryModel(encoder_kind=EncoderKind.GAT, embed_dim=6, seed=3)
    model.fit(
        tensors,
        {ids5["MEK"]: 0.9, ids5["RAF"]: 0.7, ids5["EGF"]: 0.1},
        epochs=25,
    )
    top = model.rank(tensors, net5, top_k=2)
    print(
        "  top targets:",
        [(net5.registry.get(t.entity_id).name, round(t.score, 3)) for t in top],
    )
    ex = GraphExplainer(model, ig_steps=6).explain_target(
        tensors, net5, top[0].entity_id
    )
    print("  XAI summary:", ex.summary[:120].replace("→", "->"), "...")

    # Phase 6
    print("\n### PHASE 6 — Storage / stats / plugins")
    net6, ids6 = mapk("p6")
    reg = create_default_registry()
    eng6 = DualEngineSimulator(net6, plugins=reg)
    t6 = eng6.run_ode(SimulationConfig(t_end=8.0, dt=0.2, record_every=8))
    store = SimulationStore(":memory:")
    rec = store.save_run(net6, t6, name="live_p6", tags={"phase": 6})
    loaded = store.load_run(rec.run_id, verify=True)
    print(
        f"  stored run={rec.run_id[:16]}... verified, "
        f"restored nodes={len(loaded.network.nodes())}"
    )
    wt = welch_ttest([1.0, 1.1, 0.95, 1.05], [0.2, 0.25, 0.18, 0.22])
    print(
        f"  welch p={wt.p_value:.2e} Cohen d={wt.effect.cohens_d:.2f} "
        f"significant={wt.significant}"
    )
    print("  plugin_scores keys:", list(t6.metadata.get("plugin_scores", {}).keys()))

    # Phase 7
    print("\n### PHASE 7 — Patient / systemic disease / pathology")
    base7, _ = mapk("p7base")
    variants = [
        VariantRecord(
            chrom="12",
            pos=1,
            variant_id="v1",
            ref="A",
            alt=["G"],
            qual=99.0,
            filter_status=["PASS"],
            info={},
            gene="MEK",
            consequence=VariantConsequence.MISSENSE,
        )
    ]
    patient = build_patient_network(
        base7, "PAT_LIVE", variants, [ExpressionRecord("ERK", 2.0)]
    )
    print(
        f"  patient mutations={len(patient.applied_mutations)} "
        f"expr_scales={len(patient.expression_scales)}"
    )
    net7, _ = mapk("p7dis")
    sim = DiseaseSimulator(net7)
    inf = sim.inflammation(
        InflammationConfig(
            ensure_missing=True, cytokines=("TNF", "IL6"), exhaustion_onset=6.0
        )
    )
    eng7 = DualEngineSimulator(net7)
    sim.load(eng7)
    eng7.run_ode(SimulationConfig(t_end=10.0, dt=0.25, record_every=8))
    has_tnf = any(e.name == "TNF" for e in net7.registry.entities())
    print(f"  inflammation perts={len(inf.perturbations)} TNF injected={has_tnf}")

    net_a, id_a = mapk("A")
    net_b, id_b = mapk("B")
    net_b.registry.get(id_b["RAS"]).set_concentration(3.0)
    ta = DualEngineSimulator(net_a).run_ode(
        SimulationConfig(t_end=8.0, dt=0.25, record_every=8)
    )
    tb = DualEngineSimulator(net_b).run_ode(
        SimulationConfig(t_end=8.0, dt=0.25, record_every=8)
    )
    rem = [
        {id_b[net_a.registry.get(eid).name]: v for eid, v in sample.items()}
        for sample in ta.concentrations
    ]
    rem_b = [
        {id_b[net_a.registry.get(eid).name]: v for eid, v in sample.items()}
        for sample in ta.boolean_states
    ]
    ta_al = TrajectoryResult(list(ta.times), rem, rem_b, SimulatorBackend.ODE)
    hsi = homeostatic_shift_index(ta_al, tb, net_b, threshold=0.2)
    print(f"  HSI={hsi.hsi:.3f} collapse_flag={hsi.collapse_flag}")

    # Phase 8
    print("\n### PHASE 8 — HPC / sensitivity / optimization")
    net8, ids8 = mapk("p8")
    cfg8 = SimulationConfig(t_end=6.0, dt=0.25, record_every=4)
    ens = EnsembleRunner(net8, cfg8, executor="serial").monte_carlo(
        6, seed=1, initial_noise_sigma=0.05, lognormal_param_sigma=0.1
    )
    b = ens.bands[ids8["ERK"]]
    print(
        f"  ensemble {ens.n_success}/{ens.n_members} "
        f"ERK mean={b.mean[-1]:.3f} CI=[{b.low[-1]:.3f},{b.high[-1]:.3f}]"
    )
    specs = [ParameterSpec(ids8["MEK"], "vmax", 0.5, 1.5, name="MEK.vmax")]
    loc = LocalSensitivityAnalyzer(net8, specs, config=cfg8, relative_step=1e-2).analyze(
        [ids8["ERK"]]
    )
    print(f"  local dERK/dMEK.vmax={loc.matrix[0][0]:.3f}")
    truth = DualEngineSimulator(net8).run_ode(cfg8)
    times = truth.times[::2]
    vals = [truth.concentrations[i][ids8["ERK"]] for i in range(0, len(truth.times), 2)]
    mek = net8.registry.get(ids8["MEK"])
    mek.kinetics = mek.kinetics.with_updates(vmax=0.55)
    fit = ParameterEstimator(
        net8, specs, [FitTarget(ids8["ERK"], times, vals)], config=cfg8
    ).fit(method="nelder_mead", max_iter=20)
    print(f"  fit vmax={fit.x[0]:.3f} SSE={fit.fun:.4f} success={fit.success}")

    print("\n" + "=" * 64)
    print("ALL PHASES 1-8 SMOKE COMPLETE")
    print("=" * 64)


if __name__ == "__main__":
    main()
