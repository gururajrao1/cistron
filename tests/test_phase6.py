"""Phase 6 — storage, statistics, plugins."""

from __future__ import annotations

from voidsignal import (
    BasePlugin,
    BayesianParameterAuditor,
    DualEngineSimulator,
    FinalConcentrationScorePlugin,
    InteractionType,
    PluginRegistry,
    Protein,
    RunMetadataPlugin,
    SignalingNetwork,
    SimulationConfig,
    SimulationStore,
    build_graph_tensors,
    compare_trajectories,
    cohens_d,
    create_default_registry,
    mean,
    welch_ttest,
)


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="mapk_p6")
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


def test_storage_roundtrip_and_hash() -> None:
    net, ids = _mapk()
    traj = DualEngineSimulator(net).run_ode(
        SimulationConfig(t_end=8.0, dt=0.2, record_every=10)
    )
    tensors = build_graph_tensors(net, normalize="none")
    store = SimulationStore(":memory:")
    rec = store.save_run(
        net,
        traj,
        name="mapk_smoke",
        tags={"phase": 6},
        pk_paths={"drugA": {"times": [0.0, 1.0], "concentrations": [1.0, 0.5]}},
        embeddings={"gat": [[0.1, 0.2], [0.3, 0.4]]},
        embedding_node_ids={"gat": [ids["EGF"], ids["ERK"]]},
        graph_tensors=tensors,
    )
    assert rec.network_hash
    assert store.verify_run(rec.run_id)
    loaded = store.load_run(rec.run_id, verify=True)
    assert loaded.network.name == "mapk_p6"
    assert len(loaded.network.nodes()) == 6
    assert len(loaded.trajectory) == len(traj)
    assert loaded.pk_paths["drugA"]["concentrations"][1] == 0.5
    assert loaded.graph_tensors is not None
    assert loaded.graph_tensors.num_nodes == 6
    # Re-simulate restored network without crash
    DualEngineSimulator(loaded.network).run_ode(
        SimulationConfig(t_end=2.0, dt=0.5, record_every=2)
    )
    store.close()


def test_statistics_empty_safe_and_welch() -> None:
    assert mean([]) == 0.0
    assert cohens_d([], [1.0]).interpretation == "undefined"
    ctrl = [1.0, 1.1, 0.9, 1.05, 0.95]
    treat = [0.2, 0.25, 0.15, 0.22, 0.18]
    res = welch_ttest(ctrl, treat)
    assert res.p_value < 0.05
    assert res.effect.cohens_d < 0.0

    net, ids = _mapk()
    control = DualEngineSimulator(net).run_ode(
        SimulationConfig(t_end=10.0, dt=0.25, record_every=5)
    )
    net2, ids2 = _mapk()
    # Knock down MEK production
    mek = net2.registry.get(ids2["MEK"])
    mek.kinetics = mek.kinetics.with_updates(production_rate=0.0, vmax=0.1)
    treated = DualEngineSimulator(net2).run_ode(
        SimulationConfig(t_end=10.0, dt=0.25, record_every=5)
    )
    cmp_ = compare_trajectories(control, treated, ids["ERK"], burn_in=2.0)
    assert cmp_.entity_id == ids["ERK"]
    assert 0.0 <= cmp_.test.p_value <= 1.0


def test_bayesian_parameter_audit() -> None:
    def factory() -> SignalingNetwork:
        return _mapk()[0]

    report = BayesianParameterAuditor(
        factory, noise_sigma=0.2, seed=1, config=SimulationConfig(t_end=6.0, dt=0.3, record_every=10)
    ).run(n_samples=8, cv_threshold=0.5)
    assert report.n_samples == 8
    assert report.bounds
    assert all(b.std_ss >= 0.0 for b in report.bounds)


def test_plugin_registry_hooks_into_dual_engine() -> None:
    net, ids = _mapk()
    seen: list[float] = []

    class CounterPlugin(BasePlugin):
        name = "counter"
        priority = 1

        def step_hook(self):
            def hook(state, t):
                seen.append(t)

            return hook

        def after_run(self, engine, trajectory, context):
            context.extras["n_steps_seen"] = len(seen)

    reg = PluginRegistry()
    reg.register(RunMetadataPlugin())
    reg.register(FinalConcentrationScorePlugin(entity_ids=[ids["ERK"]]))
    reg.register(CounterPlugin())

    engine = DualEngineSimulator(net, plugins=reg)
    traj = engine.run_ode(SimulationConfig(t_end=3.0, dt=0.5, record_every=1))
    assert seen
    assert "plugin_scores" in traj.metadata
    assert ids["ERK"] in traj.metadata["plugin_scores"]["final_concentration_score"]
    assert traj.metadata.get("plugins", {}).get("run_metadata", {}).get("network_name") == "mapk_p6"

    # Default registry factory
    reg2 = create_default_registry()
    assert "run_metadata" in reg2
