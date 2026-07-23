"""AI prioritization, XAI attributions, and live scientist reasoning."""

from voidsignal.ai.prioritizer import (
    ATTENTION_EPS,
    CombinationCandidate,
    NodeFeatureVector,
    PrioritizationResult,
    build_node_feature_vector,
    compute_attention_matrix,
    compute_driver_scores,
    node_feature_array,
    output_sum_at_final,
    prioritize,
    rank_combination_targets,
    resolve_output_nodes,
)
from voidsignal.ai.scientist import generate_scientist_reasoning, snapshot_state_summary
from voidsignal.ai.xai import compute_xai_attributions, decompose_attentive_flow

__all__ = [
    "ATTENTION_EPS",
    "CombinationCandidate",
    "NodeFeatureVector",
    "PrioritizationResult",
    "build_node_feature_vector",
    "compute_attention_matrix",
    "compute_driver_scores",
    "compute_xai_attributions",
    "decompose_attentive_flow",
    "generate_scientist_reasoning",
    "node_feature_array",
    "output_sum_at_final",
    "prioritize",
    "rank_combination_targets",
    "resolve_output_nodes",
    "snapshot_state_summary",
]
