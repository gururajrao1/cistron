"""
VoidSignal platform lifecycle orchestrator.

Ingest → perturb → Hill-cube ODE → 61-keyframe scrubber → GAT attention /
5D features → BioReasoner discovery brief.

Also provides the CLI used by ``python -m voidsignal.pipeline``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union
import argparse
import time

from pydantic import BaseModel, ConfigDict, Field

from voidsignal.ai import prioritize
from voidsignal.data import hypoxia_network_preset, offline_mapk_activity_graph
from voidsignal.engine import DrugDose, HillCubeConfig, HillCubeEngine
from voidsignal.models.graph import CausalActivityGraph
from voidsignal.models.prioritization import PrioritizationResult
from voidsignal.models.reasoner import CausalContextPayload
from voidsignal.models.serialization import ScrubberPayload
from voidsignal.reasoner import (
    build_causal_context,
    generate_discovery_brief_prompt,
    synthesize_deterministic_brief,
)
from voidsignal.serialization import scrub_simulation

PLATFORM_PRESETS: Dict[str, Callable[[], CausalActivityGraph]] = {
    "hypoxia": hypoxia_network_preset,
    "mapk": offline_mapk_activity_graph,
}


def load_activity_graph(preset: str = "hypoxia") -> CausalActivityGraph:
    """Resolve a named activity-flow scaffold (hypoxia / mapk)."""
    key = preset.strip().lower()
    factory = PLATFORM_PRESETS.get(key)
    if factory is None:
        raise ValueError(
            f"Unknown network preset {preset!r}. Available: {sorted(PLATFORM_PRESETS)}"
        )
    return factory()


class DrugPerturbation(BaseModel):
    """CLI / API drug dose against one target."""

    model_config = ConfigDict(extra="forbid")

    target: str
    c_drug: float = Field(..., ge=0.0)
    ki: float = Field(..., gt=0.0)


class VoidSignalPipelineConfig(BaseModel):
    """User-facing configuration for one platform run."""

    model_config = ConfigDict(extra="forbid")

    preset: str = "hypoxia"
    t_end: float = Field(default=60.0, gt=0.0)
    dense_output_points: int = Field(default=61, ge=2, le=501)
    knockouts: List[str] = Field(default_factory=list)
    clamps: Dict[str, float] = Field(default_factory=dict)
    drugs: List[DrugPerturbation] = Field(default_factory=list)
    source_node: Optional[str] = None
    target_node: Optional[str] = None
    path_k: int = Field(default=3, ge=1, le=20)
    simulation_id: Optional[str] = None


class VoidSignalPipelineResult(BaseModel):
    """Validated end-to-end artefacts from :class:`VoidSignalPipeline`."""

    model_config = ConfigDict(extra="forbid")

    graph_name: str
    preset: str
    scrubber: ScrubberPayload
    prioritization: PrioritizationResult
    causal_context: Optional[CausalContextPayload] = None
    discovery_brief: str = ""
    discovery_prompt: str = ""
    elapsed_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def to_markdown(self) -> str:
        """Human-readable Markdown report for CLI export."""
        lines = [
            "# VoidSignal Discovery Report",
            "",
            f"- **preset**: `{self.preset}`",
            f"- **graph**: `{self.graph_name}`",
            f"- **simulation_id**: `{self.scrubber.simulation_id}`",
            f"- **elapsed_ms**: {self.elapsed_ms:.3f}",
            f"- **keyframes**: {len(self.scrubber.time_steps)}",
            "",
            "## Master regulators",
            "",
        ]
        for name, score in self.prioritization.master_regulators[:8]:
            lines.append(f"- `{name}` — S = {score:.6g}")
        lines.extend(["", "## Discovery brief", "", self.discovery_brief or "_(empty)_", ""])
        if self.causal_context and self.causal_context.extracted_paths:
            lines.extend(["## Causal paths", ""])
            for i, path in enumerate(self.causal_context.extracted_paths, start=1):
                chain = " → ".join(path.nodes)
                lines.append(
                    f"{i}. `{chain}` (Σα={path.cumulative_attention:.4f}; "
                    f"mechanisms={path.mechanisms})"
                )
            lines.append("")
        return "\n".join(lines)


class VoidSignalPipeline:
    """
    Master orchestrator for the VoidSignal platform lifecycle.

    Ingest → perturb → Hill-cube ODE → 61-keyframe scrubber → GAT attention
    / 5D features → BioReasoner paths + grounded discovery brief.
    """

    def __init__(
        self,
        config: Optional[Union[VoidSignalPipelineConfig, Mapping[str, Any]]] = None,
        *,
        graph: Optional[CausalActivityGraph] = None,
    ) -> None:
        if config is None:
            self.config = VoidSignalPipelineConfig()
        elif isinstance(config, VoidSignalPipelineConfig):
            self.config = config
        else:
            self.config = VoidSignalPipelineConfig.model_validate(dict(config))
        self._graph_override = graph

    def ingest(self) -> CausalActivityGraph:
        """Load the activity-flow scaffold (preset or injected graph)."""
        if self._graph_override is not None:
            return self._graph_override
        return load_activity_graph(self.config.preset)

    def _default_path_endpoints(
        self, graph: CausalActivityGraph
    ) -> Tuple[Optional[str], Optional[str]]:
        cfg = self.config
        src = cfg.source_node
        tgt = cfg.target_node
        if src and tgt:
            return src, tgt
        preset = cfg.preset.strip().lower()
        if preset == "hypoxia":
            return src or "O2", tgt or "VEGFA"
        if preset == "mapk":
            return src or "EGF", tgt or "MAPK1"
        symbols = graph.node_symbols()
        if len(symbols) >= 2:
            return src or symbols[0], tgt or symbols[-1]
        return src, tgt

    def run(self) -> VoidSignalPipelineResult:
        """Execute the full validated platform cycle."""
        t0 = time.perf_counter()
        cfg = self.config
        graph = self.ingest()

        eng = HillCubeEngine(
            graph,
            config=HillCubeConfig(
                t_end=float(cfg.t_end),
                dense_output_points=int(cfg.dense_output_points),
            ),
        )
        for sym, val in cfg.clamps.items():
            if sym not in eng.symbols:
                raise KeyError(f"Clamp target {sym!r} not in graph")
            eng.clamp(sym, float(val))
        if cfg.knockouts:
            eng.knockout(cfg.knockouts)
        if cfg.drugs:
            eng.apply_drugs(
                [
                    DrugDose(target=d.target, c_drug=d.c_drug, ki=d.ki)
                    for d in cfg.drugs
                ]
            )

        scrubber = scrub_simulation(
            eng,
            t_end=float(cfg.t_end),
            simulation_id=cfg.simulation_id,
            metadata={
                "preset": cfg.preset.strip().lower(),
                "pipeline": "VoidSignalPipeline",
            },
        )
        prioritization = prioritize(graph, scrubber)

        src, tgt = self._default_path_endpoints(graph)
        causal_context: Optional[CausalContextPayload] = None
        brief = ""
        prompt = ""
        if src and tgt and src in graph.nodes and tgt in graph.nodes:
            causal_context = build_causal_context(
                graph,
                scrubber,
                source_node=src,
                target_node=tgt,
                k=cfg.path_k,
                prioritization=prioritization,
            )
            brief = synthesize_deterministic_brief(causal_context)
            prompt = generate_discovery_brief_prompt(causal_context)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return VoidSignalPipelineResult(
            graph_name=graph.name,
            preset=cfg.preset.strip().lower(),
            scrubber=scrubber,
            prioritization=prioritization,
            causal_context=causal_context,
            discovery_brief=brief,
            discovery_prompt=prompt,
            elapsed_ms=elapsed_ms,
            metadata={
                "source_node": src,
                "target_node": tgt,
                "n_nodes": len(graph.nodes),
                "n_edges": len(graph.edges),
                "knockouts": list(cfg.knockouts),
                "clamps": dict(cfg.clamps),
            },
        )


def _parse_clamp(raw: str) -> Tuple[str, float]:
    if "=" not in raw:
        raise ValueError(f"Clamp must be NODE=VALUE, got {raw!r}")
    node, val = raw.split("=", 1)
    return node.strip(), float(val)


def _parse_drug(raw: str) -> DrugPerturbation:
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(f"Drug must be TARGET:C_DRUG:KI, got {raw!r}")
    return DrugPerturbation(
        target=parts[0].strip(),
        c_drug=float(parts[1]),
        ki=float(parts[2]),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="voidsignal.pipeline",
        description=(
            "VoidSignal end-to-end runner: ingest → perturb → Hill-cube ODE → "
            "scrubber → attention → BioReasoner brief."
        ),
    )
    p.add_argument(
        "--preset",
        default="hypoxia",
        choices=sorted(PLATFORM_PRESETS),
        help="Activity-flow network scaffold",
    )
    p.add_argument(
        "--knockout",
        "-k",
        action="append",
        default=[],
        dest="knockouts",
        help="Gene knockout (repeatable)",
    )
    p.add_argument(
        "--clamp",
        "-c",
        action="append",
        default=[],
        dest="clamps",
        help="Clamp NODE=VALUE (repeatable), e.g. O2=0.0",
    )
    p.add_argument(
        "--drug",
        "-d",
        action="append",
        default=[],
        dest="drugs",
        help="Drug dose TARGET:C_DRUG:KI (repeatable)",
    )
    p.add_argument("--source", default=None, help="Causal path source node")
    p.add_argument("--target", default=None, help="Causal path target node")
    p.add_argument("--path-k", type=int, default=3, help="Top-k causal paths")
    p.add_argument("--t-end", type=float, default=60.0, help="Integration horizon (min)")
    p.add_argument(
        "--format",
        choices=("json", "markdown", "md", "brief"),
        default="markdown",
        help="Stdout / file export format",
    )
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Optional output path (otherwise print to stdout)",
    )
    p.add_argument("--simulation-id", default=None)
    return p


def config_from_args(args: Any) -> VoidSignalPipelineConfig:
    clamps: Dict[str, float] = {}
    for raw in args.clamps or []:
        n, v = _parse_clamp(raw)
        clamps[n] = v
    drugs = [_parse_drug(raw) for raw in (args.drugs or [])]
    return VoidSignalPipelineConfig(
        preset=args.preset,
        t_end=float(args.t_end),
        knockouts=list(args.knockouts or []),
        clamps=clamps,
        drugs=drugs,
        source_node=args.source,
        target_node=args.target,
        path_k=int(args.path_k),
        simulation_id=args.simulation_id,
    )


def render_export(result: VoidSignalPipelineResult, fmt: str) -> str:
    f = fmt.lower()
    if f in ("markdown", "md"):
        return result.to_markdown()
    if f == "brief":
        return result.discovery_brief
    return result.model_dump_json(indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry: ``python -m voidsignal.pipeline`` / ``voidsignal-run``."""
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    cfg = config_from_args(args)
    result = VoidSignalPipeline(cfg).run()
    text = render_export(result, args.format)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


__all__ = [
    "PLATFORM_PRESETS",
    "DrugPerturbation",
    "VoidSignalPipeline",
    "VoidSignalPipelineConfig",
    "VoidSignalPipelineResult",
    "build_arg_parser",
    "config_from_args",
    "load_activity_graph",
    "main",
    "render_export",
]
