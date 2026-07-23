"""MAPK-like cascade smoke demo for CISTRON Phase 1."""

from __future__ import annotations

from cistron import (
    DualEngineSimulator,
    InteractionType,
    LogicGate,
    NodeLogic,
    ODEStepper,
    PerturbationManager,
    Protein,
    SignalingNetwork,
    SimulationConfig,
)


def build_mapk_network() -> tuple[SignalingNetwork, dict[str, str]]:
    net = SignalingNetwork(name="mapk_toy")
    ids: dict[str, str] = {}
    initials = {"EGF": 1.0, "EGFR": 0.2, "RAS": 0.1, "RAF": 0.1, "MEK": 0.1, "ERK": 0.1}
    for name, conc in initials.items():
        entity = Protein(name=name, concentration=conc)
        if name == "EGF":
            entity.set_boolean(True)
            entity.kinetics = entity.kinetics.with_updates(production_rate=0.05, degradation_rate=0.01)
        net.add_node(entity)
        ids[name] = entity.entity_id

    cascade = [
        ("EGF", "EGFR", InteractionType.ACTIVATION, 1.2),
        ("EGFR", "RAS", InteractionType.ACTIVATION, 1.0),
        ("RAS", "RAF", InteractionType.ACTIVATION, 1.0),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION, 1.0),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION, 1.0),
        ("ERK", "RAF", InteractionType.INHIBITION, 0.35),
    ]
    for src, tgt, itype, rate in cascade:
        net.connect(ids[src], ids[tgt], itype, rate_constant=rate)

    net.set_node_logic(ids["ERK"], NodeLogic(gate=LogicGate.OR, inhibitor_veto=True))
    return net, ids


def main() -> None:
    net, ids = build_mapk_network()
    issues = net.validate()
    assert not issues, issues

    print("Network:", net.summary())
    print("Feedback loops:", net.detect_feedback_loops())
    print("Hubs:", net.find_hubs(3))
    print("Robustness(ERK):", net.robustness(ids["ERK"]))

    engine = DualEngineSimulator(net)

    bool_traj = engine.run_boolean(SimulationConfig(boolean_steps=30, dt=1.0))
    print("Boolean final ERK:", bool_traj.final_boolean()[ids["ERK"]])
    print("Boolean attractor:", engine.boolean.find_attractor(max_steps=64))

    # Fresh network for ODE + perturbations
    net2, ids2 = build_mapk_network()
    engine2 = DualEngineSimulator(net2)
    mgr = PerturbationManager()
    mgr.knockout(ids2["MEK"], t_start=20.0)
    mgr.dose(ids2["RAF"], concentration=3.0, ki=0.4, t_start=40.0, t_end=70.0)

    ode_traj = engine2.run_ode(
        SimulationConfig(
            t_end=100.0,
            dt=0.05,
            stepper=ODEStepper.RK4,
            record_every=20,
        ),
        perturbation_hooks=mgr.hooks(),
    )
    print("ODE samples:", len(ode_traj))
    print("ODE final concentrations:")
    for name, eid in ids2.items():
        print(f"  {name:4s}  {ode_traj.final_concentrations()[eid]:.4f}")
    print("Perturbations:", mgr.summary())


if __name__ == "__main__":
    main()
