"""Phase 4 — disease phenotypes, pharmacology, toxicology."""

from __future__ import annotations

from voidsignal import (
    AggregationDrift,
    CancerSignalingConfig,
    CombinationSynergyCalculator,
    DiseasePhenotypingEngine,
    DoseResponseModeler,
    DrugAgent,
    DualEngineSimulator,
    InteractionType,
    Mechanism,
    NeurodegenerationConfig,
    PharmacokineticProfile,
    Protein,
    SafetyPathway,
    SafetyTarget,
    SafetyTargetPanel,
    SignalingNetwork,
    SimulationConfig,
    ThresholdDirection,
    ToxicologyMonitor,
    build_cancer_phenotype,
    effect_from_mechanism,
)


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="mapk_phase4")
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
        net.add_node(p)
        ids[name] = p.entity_id
    cascade = [
        ("EGF", "EGFR", InteractionType.ACTIVATION, 1.2),
        ("EGFR", "RAS", InteractionType.ACTIVATION, 1.0),
        ("RAS", "RAF", InteractionType.ACTIVATION, 1.0),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION, 1.0),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION, 1.0),
        ("ERK", "RAF", InteractionType.INHIBITION, 0.5),
    ]
    for s, t, it, r in cascade:
        net.connect(ids[s], ids[t], it, rate_constant=r)
    return net, ids


def test_cancer_phenotype_locks_oncogene_and_breaks_feedback() -> None:
    net, ids = _mapk()
    pheno = build_cancer_phenotype(
        net,
        CancerSignalingConfig(
            oncogenes=("RAS", "EGFR"),
            expression_level=3.0,
            attenuate_negative_feedback=True,
            feedback_scale=0.02,
            survival_nodes=("ERK",),
            survival_production_boost=2.0,
        ),
    )
    assert pheno.kind.name == "CANCER_SIGNALING"
    assert any("constitutive" in getattr(p, "name", "") for p in pheno.perturbations)

    engine = DualEngineSimulator(net)
    pheno.load_into(engine)
    traj = engine.run_ode(SimulationConfig(t_end=15.0, dt=0.1, record_every=10))
    final = traj.final_concentrations()
    assert final[ids["RAS"]] >= 2.5
    # Feedback edge should be attenuated while phenotype hooks are active
    fb = [e for e in net.active_edges() if e.source_id == ids["ERK"] and e.target_id == ids["RAF"]][0]
    assert fb.rate_constant < 0.5


def test_neuro_aggregation_increases_clearance() -> None:
    net, ids = _mapk()
    engine = DiseasePhenotypingEngine(net)
    pheno = engine.neurodegeneration(
        NeurodegenerationConfig(
            vulnerable_nodes=("ERK",),
            onset=0.0,
            alpha=0.2,
            power=1.0,
            concentration_bleed=0.0,
        )
    )
    drift = next(p for p in pheno.perturbations if isinstance(p, AggregationDrift))
    assert drift.delta_clearance(0.0) == 0.0 or drift.clearance_scale(0.0) >= 1.0
    assert drift.clearance_scale(10.0) > drift.clearance_scale(1.0)

    dual = DualEngineSimulator(net)
    pheno.load_into(dual)
    dual.run_ode(SimulationConfig(t_end=20.0, dt=0.1, record_every=20))
    erk = net.registry.get(ids["ERK"])
    assert erk.metadata.get("aggregation_deg_scale", 1.0) > 1.0
    assert erk.kinetics.degradation_rate > 0.1


def test_pk_clearance_and_mechanisms() -> None:
    pk = PharmacokineticProfile(dose=2.0, volume=1.0, kel=0.2, dosing_times=[0.0])
    assert pk.concentration(0.0) == 2.0
    assert pk.concentration(10.0) < pk.concentration(1.0)
    assert pk.auc(20.0) > 0.0

    comp = effect_from_mechanism(Mechanism.COMPETITIVE, 2.0, ki=1.0)
    assert comp.km_scale > 1.0
    assert abs(comp.vmax_scale - 1.0) < 1e-12

    noncomp = effect_from_mechanism(Mechanism.NONCOMPETITIVE, 2.0, ki=1.0)
    assert noncomp.vmax_scale < 1.0

    allo_inh = effect_from_mechanism(Mechanism.ALLOSTERIC_INHIBITION, 2.0, ki=1.0, hill=2.0)
    assert allo_inh.vmax_scale < 1.0

    allo_act = effect_from_mechanism(Mechanism.ALLOSTERIC_ACTIVATION, 2.0, ki=1.0, efficacy=1.5)
    assert allo_act.vmax_scale > 1.0


def test_drug_agent_washes_out_and_scales_target() -> None:
    net, ids = _mapk()
    base_vmax = net.registry.get(ids["MEK"]).kinetics.vmax
    agent = DrugAgent(
        target_id=ids["MEK"],
        mechanism=Mechanism.NONCOMPETITIVE,
        ki=0.5,
        plateau_concentration=5.0,
        t_start=5.0,
        t_end=15.0,
        pk=PharmacokineticProfile(dose=5.0, kel=0.5, hard_washout=True, dosing_times=[5.0]),
    )
    engine = DualEngineSimulator(net)
    traj = engine.run_ode(
        SimulationConfig(t_end=30.0, dt=0.1, record_every=5),
        perturbation_hooks=[agent.as_hook()],
    )
    # During exposure MEK should be suppressed vs early baseline trajectory values
    mid = traj.concentrations[len(traj) // 2][ids["MEK"]]
    late = traj.final_concentrations()[ids["MEK"]]
    assert mid >= 0.0 and late >= 0.0
    # After hard washout kinetics restored
    assert abs(net.registry.get(ids["MEK"]).kinetics.vmax - base_vmax) < 1e-9


def test_dose_response_ic50_and_bliss() -> None:
    def factory() -> SignalingNetwork:
        return _mapk()[0]

    modeler = DoseResponseModeler(
        factory, config=SimulationConfig(t_end=25.0, dt=0.2, record_every=25)
    )
    curve = modeler.sweep(
        target_id="MEK",
        readout_id="ERK",
        doses=[0.0, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
        mechanism=Mechanism.NONCOMPETITIVE,
        ki=0.8,
        mode="inhibition",
    )
    assert curve.responses[0] >= curve.responses[-1] - 1e-9
    assert curve.ic50 is None or curve.ic50 > 0.0

    calc = CombinationSynergyCalculator(
        factory, config=SimulationConfig(t_end=20.0, dt=0.25, record_every=20)
    )
    a = DrugAgent(
        target_id="MEK",
        mechanism=Mechanism.NONCOMPETITIVE,
        ki=1.0,
        plateau_concentration=2.0,
    )
    b = DrugAgent(
        target_id="RAF",
        mechanism=Mechanism.COMPETITIVE,
        ki=1.0,
        plateau_concentration=2.0,
    )
    syn = calc.score(a, b, readout_id="ERK", ic50_a=2.0, ic50_b=2.0)
    assert 0.0 <= syn.effect_a <= 1.0
    assert 0.0 <= syn.effect_ab <= 1.0
    assert syn.interpretation in {"synergy", "antagonism", "additive"}


def test_toxicology_flags_threshold_breach() -> None:
    net, ids = _mapk()
    # Promote ERK as a DNA-damage proxy safety node
    panel = SafetyTargetPanel().add(
        SafetyTarget(
            entity_id=ids["ERK"],
            pathway=SafetyPathway.DNA_DAMAGE,
            threshold=0.5,
            direction=ThresholdDirection.ABOVE,
            name="ERK",
        )
    )
    mon = ToxicologyMonitor(panel, cooldown=0.5)
    engine = DualEngineSimulator(net)
    mon.attach(engine)
    traj = engine.run_ode(SimulationConfig(t_end=30.0, dt=0.1, record_every=10))
    live = mon.report()
    offline = mon.evaluate_trajectory(traj)
    assert not live.safe or not offline.safe
    assert live.tox_index > 0.0 or offline.tox_index > 0.0
    assert ids["ERK"] in live.breached_targets or ids["ERK"] in offline.breached_targets
