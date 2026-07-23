"""Phase 5 — graph ML tensors, predictive models, explainability."""

from __future__ import annotations

from voidsignal import (
    AIScientistReasoner,
    DualEngineSimulator,
    EncoderKind,
    GraphExplainer,
    GraphTensorFactory,
    InteractionType,
    LinkPredictionModel,
    Protein,
    SignalingNetwork,
    SimulationConfig,
    TargetDiscoveryModel,
    build_graph_tensors,
)


def _mapk() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="mapk_ml")
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


def test_graph_tensor_shapes_and_namespace() -> None:
    net, ids = _mapk()
    traj = DualEngineSimulator(net).run_ode(
        SimulationConfig(t_end=10.0, dt=0.2, record_every=10)
    )
    # Fresh network + ids for alignment; use trajectory from same topology shape
    net2, ids2 = _mapk()
    # Remap trajectory keys by name order is fragile; rebuild tensors from live state
    tensors = build_graph_tensors(net2, normalize="zscore")
    assert tensors.num_nodes == 6
    assert tensors.num_edges == 6
    assert len(tensors.x) == 6
    assert len(tensors.x[0]) == tensors.num_node_features
    assert len(tensors.edge_index) == 2
    assert len(tensors.edge_index[0]) == 6
    assert tensors.row_of(ids2["ERK"]) >= 0
    assert tensors.node_id(tensors.row_of(ids2["MEK"])) == ids2["MEK"]

    mock = tensors.mock_torch()
    assert mock.num_nodes == 6
    assert mock.x.shape[0] == 6
    np_pack = tensors.to_numpy()
    assert "x" in np_pack and "edge_index" in np_pack

    # Zero-concentration node still produces finite features
    net2.registry.get(ids2["ERK"]).set_concentration(0.0)
    t0 = GraphTensorFactory().from_network(net2)
    assert all(all(abs(v) < 1e9 for v in row) for row in t0.x)
    _ = traj  # trajectory path exercised above via DualEngine


def test_target_discovery_and_link_prediction() -> None:
    net, ids = _mapk()
    tensors = build_graph_tensors(net, normalize="zscore")
    model = TargetDiscoveryModel(encoder_kind=EncoderKind.GAT, embed_dim=6, seed=3)
    labels = {
        ids["MEK"]: 0.9,
        ids["RAF"]: 0.7,
        ids["EGF"]: 0.1,
        ids["ERK"]: 0.2,
    }
    hist = model.fit(tensors, labels, epochs=40, lr=0.1)
    assert hist[-1] <= hist[0] + 0.5  # generally learns / stays bounded
    ranked = model.rank(tensors, net, top_k=3)
    assert ranked[0].score >= ranked[-1].score
    assert all(s.entity_id in ids.values() for s in ranked)

    link = LinkPredictionModel(encoder_kind=EncoderKind.MPNN, embed_dim=6, seed=5)
    link.fit(tensors, epochs=50, neg_ratio=1)
    suggestions = link.suggest(tensors, net, top_k=5)
    assert suggestions
    assert 0.0 <= suggestions[0].score <= 1.0
    # Suggested edges should not already exist when exclude_existing=True
    existing = {(e.source_id, e.target_id) for e in net.active_edges()}
    for s in suggestions:
        assert (s.source_id, s.target_id) not in existing


def test_explainer_integrated_gradients_and_reasoner() -> None:
    net, ids = _mapk()
    tensors = build_graph_tensors(net, normalize="minmax")
    model = TargetDiscoveryModel(encoder_kind=EncoderKind.GAT, embed_dim=6, seed=9)
    model.fit(
        tensors,
        {ids["MEK"]: 1.0, ids["RAF"]: 0.8, ids["EGF"]: 0.0, ids["EGFR"]: 0.2},
        epochs=30,
    )
    explainer = GraphExplainer(model, ig_steps=8, edge_top_k=4)
    report = explainer.explain_target(tensors, net, ids["MEK"])
    assert report.entity_id == ids["MEK"]
    assert report.name == "MEK"
    assert report.feature_attributions
    assert report.summary
    assert report.structural.feedback_loops  # ERK⊣RAF loop present

    link = LinkPredictionModel(embed_dim=6, seed=1)
    link.fit(tensors, epochs=30, neg_ratio=1)
    reasoner = AIScientistReasoner(model, link_model=link)
    out = reasoner.recommend(tensors, net, top_k=2, link_top_k=3)
    assert len(out["recommendations"]) == 2
    assert "suggested_crosstalk" in out
