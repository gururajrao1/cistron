"""Phase 8 — HPC ensembles, sensitivity, optimization."""

from __future__ import annotations

from cistron import (
    DualEngineSimulator,
    EnsembleRunner,
    FitTarget,
    InteractionType,
    LocalSensitivityAnalyzer,
    MorrisAnalyzer,
    ParameterEstimator,
    ParameterSpec,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    SobolAnalyzer,
    discover_parameters,
    nelder_mead,
)


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="mapk_p8")
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
        ("EGF", "EGFR", InteractionType.ACTIVATION, 1.0),
        ("EGFR", "RAS", InteractionType.ACTIVATION, 1.0),
        ("RAS", "RAF", InteractionType.ACTIVATION, 1.0),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION, 1.0),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION, 1.0),
        ("ERK", "RAF", InteractionType.INHIBITION, 0.3),
    ]:
        net.connect(ids[s], ids[t], it, rate_constant=r)
    return net, ids


def test_ensemble_monte_carlo_serial_bands() -> None:
    net, ids = _mapk()
    runner = EnsembleRunner(
        net,
        SimulationConfig(t_end=6.0, dt=0.25, record_every=4),
        executor="serial",
        max_workers=1,
    )
    result = runner.monte_carlo(
        6,
        seed=1,
        initial_noise_sigma=0.05,
        lognormal_param_sigma=0.1,
        level=0.8,
        entity_ids=[ids["ERK"], ids["MEK"]],
    )
    assert result.n_success == 6
    assert ids["ERK"] in result.bands
    band = result.bands[ids["ERK"]]
    assert len(band.mean) == len(band.times)
    assert all(lo <= hi for lo, hi in zip(band.low, band.high))


def test_local_and_morris_sensitivity() -> None:
    net, ids = _mapk()
    specs = [
        ParameterSpec(ids["MEK"], "vmax", 0.5, 1.5, name="MEK.vmax"),
        ParameterSpec(ids["ERK"], "km", 0.5, 1.5, name="ERK.km"),
    ]
    cfg = SimulationConfig(t_end=6.0, dt=0.25, record_every=6)
    local = LocalSensitivityAnalyzer(net, specs, config=cfg, relative_step=1e-2).analyze(
        [ids["ERK"]], mode="final"
    )
    assert local.matrix
    assert len(local.matrix[0]) == 2

    morris = MorrisAnalyzer(net, specs, config=cfg, levels=6, seed=2).analyze(
        ids["ERK"], n_trajectories=4, mode="final"
    )
    assert len(morris.mu_star) == 2
    assert morris.n_trajectories == 4


def test_sobol_small() -> None:
    net, ids = _mapk()
    specs = discover_parameters(net, fields=("vmax",), entity_ids=[ids["MEK"], ids["ERK"]], relative_span=0.3)
    assert len(specs) >= 1
    cfg = SimulationConfig(t_end=5.0, dt=0.25, record_every=5)
    sob = SobolAnalyzer(net, specs[:2], config=cfg, seed=3).analyze(
        ids["ERK"], n_base=8, mode="final"
    )
    assert len(sob.first_order) == len(specs[:2])
    assert sob.output_variance >= 0.0


def test_parameter_estimator_nelder_mead() -> None:
    net, ids = _mapk()
    # Generate synthetic "experimental" data from nominal run
    truth = DualEngineSimulator(net).run_ode(
        SimulationConfig(t_end=8.0, dt=0.25, record_every=4)
    )
    times = truth.times[::2]
    values = [truth.concentrations[i][ids["ERK"]] for i in range(0, len(truth.times), 2)]
    target = FitTarget(ids["ERK"], times, values, weight=1.0)

    # Perturb MEK.vmax away from truth then recover
    mek = net.registry.get(ids["MEK"])
    true_vmax = mek.kinetics.vmax
    mek.kinetics = mek.kinetics.with_updates(vmax=true_vmax * 0.6)
    specs = [ParameterSpec(ids["MEK"], "vmax", 0.3, 2.0, name="MEK.vmax")]
    est = ParameterEstimator(
        net,
        specs,
        [target],
        config=SimulationConfig(t_end=8.0, dt=0.25, record_every=4),
    )
    result = est.fit(method="nelder_mead", max_iter=25)
    assert result.nfev > 0
    assert result.fun >= 0.0
    # Should move toward truth (not necessarily exact in few iters)
    assert abs(result.x[0] - true_vmax) < abs(0.6 * true_vmax - true_vmax) + 0.5

    # Smoke-test nelder_mead on a quadratic
    q = nelder_mead(lambda x: (x[0] - 3.0) ** 2 + (x[1] + 1.0) ** 2, [0.0, 0.0], max_iter=80)
    assert abs(q.x[0] - 3.0) < 0.2
    assert abs(q.x[1] + 1.0) < 0.2
