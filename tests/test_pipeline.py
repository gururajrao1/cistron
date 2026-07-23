"""End-to-end VoidSignalPipeline integration tests (<100 ms warm)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from voidsignal.lifecycle import (
    VoidSignalPipeline,
    VoidSignalPipelineConfig,
    build_arg_parser,
    config_from_args,
    main,
    render_export,
)

LATENCY_BUDGET_MS = 100.0


@pytest.fixture(scope="module")
def warmed_pipeline() -> VoidSignalPipeline:
    """Prime SciPy / NumPy so latency asserts measure orchestration work."""
    VoidSignalPipeline(
        VoidSignalPipelineConfig(
            preset="hypoxia",
            clamps={"O2": 0.0},
            simulation_id="warmup",
        )
    ).run()
    return VoidSignalPipeline(
        VoidSignalPipelineConfig(
            preset="hypoxia",
            clamps={"O2": 0.0},
            source_node="O2",
            target_node="VEGFA",
            simulation_id="e2e_hypoxia",
        )
    )


def test_full_cycle_under_100ms(warmed_pipeline: VoidSignalPipeline) -> None:
    t0 = time.perf_counter()
    result = warmed_pipeline.run()
    elapsed = (time.perf_counter() - t0) * 1000.0

    assert result.elapsed_ms < LATENCY_BUDGET_MS
    assert elapsed < LATENCY_BUDGET_MS, f"pipeline took {elapsed:.2f} ms"
    assert len(result.scrubber.time_steps) == 61
    assert "HIF1A" in result.scrubber.nodes
    assert "EGLN1->HIF1A" in result.scrubber.edges
    assert result.prioritization.master_regulators
    assert result.causal_context is not None
    assert result.causal_context.extracted_paths[0].nodes == [
        "O2",
        "EGLN1",
        "HIF1A",
        "VEGFA",
    ]
    assert "VEGFA" in result.discovery_brief
    assert "Do not infer unlisted" in result.discovery_prompt
    blob = result.model_dump_json()
    restored = type(result).model_validate_json(blob)
    assert restored.scrubber.simulation_id == "e2e_hypoxia"


def test_cli_args_to_brief_under_100ms(tmp_path: Path, warmed_pipeline: VoidSignalPipeline) -> None:
    # Reuse module warm-up from fixture
    _ = warmed_pipeline
    out = tmp_path / "report.md"
    argv = [
        "--preset",
        "hypoxia",
        "--clamp",
        "O2=0.0",
        "--source",
        "O2",
        "--target",
        "VEGFA",
        "--format",
        "markdown",
        "--output",
        str(out),
        "--simulation-id",
        "cli_e2e",
    ]
    t0 = time.perf_counter()
    rc = main(argv)
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert rc == 0
    assert elapsed < LATENCY_BUDGET_MS, f"CLI cycle took {elapsed:.2f} ms"
    text = out.read_text(encoding="utf-8")
    assert "VoidSignal Discovery Report" in text
    assert "O2" in text and "VEGFA" in text
    assert "Discovery brief" in text


def test_cli_json_and_perturbations() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--preset",
            "hypoxia",
            "--clamp",
            "O2=0.0",
            "--knockout",
            "MTOR",
            "--drug",
            "HIF1A:5:1",
            "--format",
            "json",
        ]
    )
    cfg = config_from_args(args)
    assert cfg.clamps["O2"] == 0.0
    assert cfg.knockouts == ["MTOR"]
    assert cfg.drugs[0].target == "HIF1A"

    result = VoidSignalPipeline(cfg).run()
    data = json.loads(render_export(result, "json"))
    assert data["preset"] == "hypoxia"
    assert data["scrubber"]["nodes"]["MTOR"][-1] == 0.0
    assert data["discovery_brief"]
    assert data["scrubber"]["metadata"]["weights"]["HIF1A"] < 1.0
