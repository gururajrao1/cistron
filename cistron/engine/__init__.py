"""ODE / hybrid simulation engines (Hill-cube, …)."""

from cistron.engine.solver import (
    DEFAULT_EC50,
    DEFAULT_HILL_N,
    DEFAULT_REGULONS,
    DEFAULT_T_END_MIN,
    DrugDose,
    FootprintPriors,
    HillCubeConfig,
    HillCubeEngine,
    HillCubeResult,
    MASTER_REGULATORS,
    STRUCTURAL_OUTPUT_GENES,
    combine_inputs,
    hill_activation,
    hill_inhibition,
    inhibitory_dominance,
    logic_and,
    logic_or,
    simulate_graph,
)

# Alias for serialization / scrubber contract
SimulationResult = HillCubeResult

__all__ = [
    "DEFAULT_EC50",
    "DEFAULT_HILL_N",
    "DEFAULT_REGULONS",
    "DEFAULT_T_END_MIN",
    "DrugDose",
    "FootprintPriors",
    "HillCubeConfig",
    "HillCubeEngine",
    "HillCubeResult",
    "MASTER_REGULATORS",
    "STRUCTURAL_OUTPUT_GENES",
    "SimulationResult",
    "combine_inputs",
    "hill_activation",
    "hill_inhibition",
    "inhibitory_dominance",
    "logic_and",
    "logic_or",
    "simulate_graph",
]
