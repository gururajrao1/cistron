"""
Visual pathway translator — ODE trajectories → animated canvas state frames.

Converts SignalingNetwork + TrajectoryResult into node color states, edge flux
velocity vectors, and animation parameters for the Research Studio canvas.
Raw numerics stay available only via inspect payloads (hover / right-click).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

from voidsignal.simulation import TrajectoryResult
from voidsignal.topology import InteractionType, SignalingNetwork


class NodeVisualState(str, Enum):
    """Primary visual legend states (no raw numbers in the main view)."""

    OVERACTIVE = "overactive"
    """🔴 Oncogenic / hyperactive drive."""

    HOMEOSTATIC = "homeostatic"
    """🟢 Normal / balanced signal."""

    INHIBITED = "inhibited"
    """🔵 Suppressed / knocked-down / drug-blocked."""

    QUIESCENT = "quiescent"
    """Dim blue-gray residual activity."""

    MUTATED = "mutated"
    """Structural / genomic highlight ring."""


class EdgeVisualState(str, Enum):
    FLOWING = "flowing"
    """Active signal with particle pulses."""

    BLOCKED = "blocked"
    """Drug / KO severed edge — dashed gray, zero particles."""

    INHIBITORY = "inhibitory"
    """Native inhibition edge (still may pulse weakly)."""


# Visual legend (exportable to frontend)
VISUAL_LEGEND: Dict[str, Dict[str, str]] = {
    "overactive": {
        "emoji": "🔴",
        "label": "Overactive / Oncogenic Drive",
        "color": "#FB7185",
        "fill": "rgba(251, 113, 133, 0.55)",
    },
    "homeostatic": {
        "emoji": "🟢",
        "label": "Homeostatic / Normal Signal",
        "color": "#A3E635",
        "fill": "rgba(163, 230, 53, 0.45)",
    },
    "inhibited": {
        "emoji": "🔵",
        "label": "Inhibited / Suppressed",
        "color": "#38BDF8",
        "fill": "rgba(56, 189, 248, 0.45)",
    },
    "quiescent": {
        "emoji": "⚪",
        "label": "Quiescent / Low Activity",
        "color": "#64748B",
        "fill": "rgba(100, 116, 139, 0.35)",
    },
    "mutated": {
        "emoji": "🟣",
        "label": "Mutated Node",
        "color": "#C084FC",
        "fill": "rgba(192, 132, 252, 0.25)",
    },
    "flowing": {
        "emoji": "⚡",
        "label": "Active Signal Pulse",
        "color": "#00E5FF",
        "fill": "#00E5FF",
    },
    "blocked": {
        "emoji": "⛔",
        "label": "Blocked / Severed Edge",
        "color": "#64748B",
        "fill": "#64748B",
    },
}


@dataclass(frozen=True)
class NodeVisual:
    """Per-node visual state at one time frame."""

    node_id: str
    label: str
    state: NodeVisualState
    activity: float
    """Normalized activity ∈ [0, 1] driving glow / radius (not shown as text)."""
    color: str
    fill: str
    radius_scale: float
    mutated: bool = False
    inspect: Dict[str, Any] = field(default_factory=dict)
    """Raw telemetry exposed only on Inspect Node."""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "state": self.state.value,
            "activity": self.activity,
            "color": self.color,
            "fill": self.fill,
            "radius_scale": self.radius_scale,
            "mutated": self.mutated,
            "inspect": dict(self.inspect),
        }


@dataclass(frozen=True)
class EdgeVisual:
    """Per-edge flux animation parameters at one time frame."""

    edge_id: str
    source_id: str
    target_id: str
    state: EdgeVisualState
    flux: float
    """Signed kinetic flux proxy k_cat · [S] · weight (model units)."""
    thickness: float
    """SVG stroke width from |flux|."""
    pulse_speed: float
    """Particle animation speed (px-normalized units / s). 0 = no particles."""
    dash: str
    color: str
    kind: str
    blocked: bool = False
    inspect: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "state": self.state.value,
            "flux": self.flux,
            "thickness": self.thickness,
            "pulse_speed": self.pulse_speed,
            "dash": self.dash,
            "color": self.color,
            "kind": self.kind,
            "blocked": self.blocked,
            "velocity": {"vx": self.pulse_speed, "vy": 0.0, "magnitude": abs(self.flux)},
            "inspect": dict(self.inspect),
        }


@dataclass(frozen=True)
class VisualFrame:
    """One scrubber frame of the animated pathway canvas."""

    t: float
    frame_index: int
    nodes: List[NodeVisual]
    edges: List[EdgeVisual]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t": self.t,
            "frame_index": self.frame_index,
            "nodes": [n.as_dict() for n in self.nodes],
            "edges": [e.as_dict() for e in self.edges],
            "metadata": dict(self.metadata),
        }

    def node_map(self) -> Dict[str, NodeVisual]:
        return {n.node_id: n for n in self.nodes}

    def edge_map(self) -> Dict[str, EdgeVisual]:
        return {e.edge_id: e for e in self.edges}


@dataclass
class VisualTimeline:
    """Full scrubber timeline for play/pause/rewind."""

    frames: List[VisualFrame]
    t_start: float
    t_end: float
    legend: Dict[str, Dict[str, str]] = field(default_factory=lambda: dict(VISUAL_LEGEND))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.frames)

    def at_time(self, t: float) -> VisualFrame:
        if not self.frames:
            raise ValueError("empty timeline")
        best = self.frames[0]
        best_d = abs(best.t - t)
        for fr in self.frames[1:]:
            d = abs(fr.t - t)
            if d < best_d:
                best, best_d = fr, d
        return best

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t_start": self.t_start,
            "t_end": self.t_end,
            "n_frames": len(self.frames),
            "frames": [f.as_dict() for f in self.frames],
            "legend": dict(self.legend),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_node_activity(
    activity: float,
    *,
    baseline: float = 0.35,
    over_threshold: float = 0.7,
    inhibited: bool = False,
    knocked_out: bool = False,
) -> NodeVisualState:
    if knocked_out or inhibited:
        return NodeVisualState.INHIBITED if activity < 0.35 else NodeVisualState.QUIESCENT
    if activity >= over_threshold:
        return NodeVisualState.OVERACTIVE
    if activity <= 0.15:
        return NodeVisualState.QUIESCENT
    if abs(activity - baseline) < 0.25 or 0.25 <= activity < over_threshold:
        return NodeVisualState.HOMEOSTATIC
    return NodeVisualState.HOMEOSTATIC


def _norm_series(values: Sequence[float]) -> List[float]:
    xs = [float(v) for v in values if math.isfinite(float(v))]
    if not xs:
        return [0.0] * len(values)
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-12:
        return [0.5 for _ in values]
    return [(float(v) - lo) / (hi - lo) for v in values]


def flux_to_thickness(flux: float, *, lo: float = 1.2, hi: float = 7.0) -> float:
    mag = abs(float(flux))
    # soft saturation
    t = mag / (1.0 + mag)
    return lo + (hi - lo) * t


def flux_to_pulse_speed(flux: float, *, blocked: bool = False) -> float:
    if blocked or abs(flux) < 1e-9:
        return 0.0
    # Hyperactive MAPK edges → fast pulses
    return max(0.15, min(4.0, 0.4 + 2.2 * abs(flux) / (1.0 + abs(flux))))


# ---------------------------------------------------------------------------
# Core translator
# ---------------------------------------------------------------------------


@dataclass
class VisualTranslatorConfig:
    over_threshold: float = 0.72
    homeostatic_center: float = 0.4
    blocked_edge_ids: Tuple[str, ...] = ()
    knocked_out_ids: Tuple[str, ...] = ()
    inhibited_ids: Tuple[str, ...] = ()
    mutated_ids: Tuple[str, ...] = ()
    drug_blocked_targets: Tuple[str, ...] = ()
    """Entity ids whose outgoing edges are severed by drug."""
    max_frames: int = 120


class VisualPathwayTranslator:
    """
    Export animated topology state from live ODE trajectories.

    Flux on edge s→t approximated as::

        flux ≈ rate_constant · weight · [S] · vmax_S
    """

    def __init__(self, config: Optional[VisualTranslatorConfig] = None) -> None:
        self.config = config or VisualTranslatorConfig()

    def frame_from_concentrations(
        self,
        network: SignalingNetwork,
        concentrations: Mapping[str, float],
        *,
        t: float = 0.0,
        frame_index: int = 0,
        activity_lookup: Optional[Mapping[str, float]] = None,
    ) -> VisualFrame:
        cfg = self.config
        knocked = {x.upper() for x in cfg.knocked_out_ids}
        inhibited = {x.upper() for x in cfg.inhibited_ids}
        mutated = {x.upper() for x in cfg.mutated_ids}
        blocked_edges = set(cfg.blocked_edge_ids)
        drug_targets = {x.upper() for x in cfg.drug_blocked_targets}

        # Build activity map (prefer normalized lookup)
        acts: Dict[str, float] = {}
        for eid in network.nodes():
            ent = network.registry.get(eid)
            if activity_lookup and eid in activity_lookup:
                acts[eid] = float(activity_lookup[eid])
            else:
                c = float(concentrations.get(eid, ent.concentration))
                acts[eid] = max(0.0, min(1.0, c / (1.0 + c)))

        nodes: List[NodeVisual] = []
        for eid in network.nodes():
            ent = network.registry.get(eid)
            name_u = ent.name.upper()
            ko = eid.upper() in knocked or name_u in knocked
            inh = eid.upper() in inhibited or name_u in inhibited or ko
            mut = eid.upper() in mutated or name_u in mutated or bool(ent.metadata.get("mutated"))
            act = 0.02 if ko else acts.get(eid, 0.0)
            state = classify_node_activity(
                act,
                baseline=cfg.homeostatic_center,
                over_threshold=cfg.over_threshold,
                inhibited=inh,
                knocked_out=ko,
            )
            if mut and state is NodeVisualState.HOMEOSTATIC:
                # keep mutated ring without forcing overactive
                pass
            legend = VISUAL_LEGEND[state.value]
            nodes.append(
                NodeVisual(
                    node_id=eid,
                    label=ent.name,
                    state=state,
                    activity=act,
                    color=legend["color"],
                    fill=legend["fill"],
                    radius_scale=0.7 + 0.8 * act,
                    mutated=mut,
                    inspect={
                        "concentration": float(concentrations.get(eid, ent.concentration)),
                        "activity_norm": act,
                        "vmax": ent.kinetics.vmax,
                        "km": ent.kinetics.km,
                        "production_rate": ent.kinetics.production_rate,
                        "degradation_rate": ent.kinetics.degradation_rate,
                        "state": state.value,
                    },
                )
            )

        edges: List[EdgeVisual] = []
        for edge in network.edges():
            src = network.registry.get(edge.source_id)
            src_conc = float(concentrations.get(edge.source_id, src.concentration))
            flux = float(edge.rate_constant) * float(edge.weight) * src_conc * max(src.kinetics.vmax, 0.0)
            src_blocked = (
                edge.source_id.upper() in drug_targets
                or src.name.upper() in drug_targets
                or edge.source_id.upper() in knocked
                or src.name.upper() in knocked
            )
            blocked = (
                edge.edge_id in blocked_edges
                or src_blocked
                or (not edge.active)
                or abs(edge.rate_constant) < 1e-12
            )
            kind = edge.interaction_type.value
            if blocked:
                estate = EdgeVisualState.BLOCKED
                color = VISUAL_LEGEND["blocked"]["color"]
                dash = "6,5"
                pulse = 0.0
                thickness = 1.5
            elif edge.interaction_type.is_inhibitory:
                estate = EdgeVisualState.INHIBITORY
                color = "#FB7185"
                dash = "5,4"
                pulse = flux_to_pulse_speed(flux * 0.35)
                thickness = flux_to_thickness(flux * 0.5)
            else:
                estate = EdgeVisualState.FLOWING
                color = "#00E5FF" if edge.interaction_type.is_catalytic else "#2DD4BF"
                dash = "2,3" if edge.interaction_type is InteractionType.PHOSPHORYLATION else "none"
                pulse = flux_to_pulse_speed(flux)
                thickness = flux_to_thickness(flux)

            edges.append(
                EdgeVisual(
                    edge_id=edge.edge_id,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    state=estate,
                    flux=0.0 if blocked else flux,
                    thickness=thickness,
                    pulse_speed=pulse,
                    dash=dash,
                    color=color,
                    kind=kind,
                    blocked=blocked,
                    inspect={
                        "rate_constant": edge.rate_constant,
                        "weight": edge.weight,
                        "source_concentration": src_conc,
                        "flux": 0.0 if blocked else flux,
                        "interaction": kind,
                        "blocked": blocked,
                    },
                )
            )

        return VisualFrame(
            t=float(t),
            frame_index=int(frame_index),
            nodes=nodes,
            edges=edges,
            metadata={"n_nodes": len(nodes), "n_edges": len(edges)},
        )

    def timeline_from_trajectory(
        self,
        network: SignalingNetwork,
        trajectory: TrajectoryResult,
        *,
        stride: int = 1,
    ) -> VisualTimeline:
        cfg = self.config
        times = list(trajectory.times)
        if not times:
            raise ValueError("trajectory has no time points")

        # Per-node concentration series for normalization
        series: Dict[str, List[float]] = {eid: [] for eid in network.nodes()}
        for conc in trajectory.concentrations:
            for eid in network.nodes():
                series[eid].append(float(conc.get(eid, 0.0)))
        norms = {eid: _norm_series(vals) for eid, vals in series.items()}

        n = len(times)
        step = max(1, int(stride))
        # Cap frames
        max_f = max(2, cfg.max_frames)
        if n // step > max_f:
            step = max(1, n // max_f)

        frames: List[VisualFrame] = []
        fi = 0
        for i in range(0, n, step):
            conc = trajectory.concentrations[i]
            act = {eid: norms[eid][i] for eid in network.nodes()}
            frames.append(
                self.frame_from_concentrations(
                    network,
                    conc,
                    t=times[i],
                    frame_index=fi,
                    activity_lookup=act,
                )
            )
            fi += 1
        # Ensure last frame
        if frames[-1].t < times[-1] - 1e-12:
            i = n - 1
            act = {eid: norms[eid][i] for eid in network.nodes()}
            frames.append(
                self.frame_from_concentrations(
                    network,
                    trajectory.concentrations[i],
                    t=times[i],
                    frame_index=fi,
                    activity_lookup=act,
                )
            )

        return VisualTimeline(
            frames=frames,
            t_start=float(times[0]),
            t_end=float(times[-1]),
            legend=dict(VISUAL_LEGEND),
            metadata={"source": "trajectory", "stride": step, "n_raw": n},
        )


def apply_knockout_visual(
    network: SignalingNetwork,
    entity_id: str,
) -> VisualTranslatorConfig:
    """Helper: KO a node → fade downstream via blocked outgoing edges."""
    return VisualTranslatorConfig(
        knocked_out_ids=(entity_id,),
        drug_blocked_targets=(entity_id,),
    )


def apply_drug_block_visual(
    network: SignalingNetwork,
    target_id: str,
) -> VisualTranslatorConfig:
    """Helper: drug on target severs outgoing edges (edge severance visual)."""
    return VisualTranslatorConfig(
        inhibited_ids=(target_id,),
        drug_blocked_targets=(target_id,),
    )


# ---------------------------------------------------------------------------
# TME spatial visual export
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellAgentVisual:
    cell_id: str
    kind: str
    """tumor | ctl | macrophage | treg"""
    x: float
    y: float
    state: NodeVisualState
    color: str
    inspect: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "state": self.state.value,
            "color": self.color,
            "inspect": dict(self.inspect),
        }


@dataclass(frozen=True)
class CytokineFieldFrame:
    """Spatial heatmap for one cytokine at time t."""

    cytokine: str
    t: float
    grid_w: int
    grid_h: int
    values: List[List[float]]
    """Row-major normalized field ∈ [0, 1]."""
    color: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cytokine": self.cytokine,
            "t": self.t,
            "grid_w": self.grid_w,
            "grid_h": self.grid_h,
            "values": self.values,
            "color": self.color,
        }


@dataclass
class MicroenvironmentVisual:
    cells: List[CellAgentVisual]
    fields: List[CytokineFieldFrame]
    t: float
    legend: Dict[str, Dict[str, str]] = field(default_factory=lambda: dict(VISUAL_LEGEND))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t": self.t,
            "cells": [c.as_dict() for c in self.cells],
            "fields": [f.as_dict() for f in self.fields],
            "legend": dict(self.legend),
        }


def build_tme_visual(
    *,
    t: float = 0.0,
    grid: int = 12,
    tumor_xy: Sequence[Tuple[float, float]] = ((0.35, 0.4), (0.55, 0.45), (0.45, 0.6)),
    ctl_xy: Sequence[Tuple[float, float]] = ((0.15, 0.2), (0.8, 0.3), (0.7, 0.75)),
    macro_xy: Sequence[Tuple[float, float]] = ((0.25, 0.7), (0.6, 0.2)),
    tgfb_center: Tuple[float, float] = (0.45, 0.5),
    il6_center: Tuple[float, float] = (0.3, 0.65),
    diffusion: float = 0.22,
) -> MicroenvironmentVisual:
    """
    Build a spatial TME snapshot with expanding cytokine Gaussians.

    Coordinates are normalized to the unit square for the React grid canvas.
    """
    cells: List[CellAgentVisual] = []
    for i, (x, y) in enumerate(tumor_xy):
        cells.append(
            CellAgentVisual(
                cell_id=f"tumor_{i}",
                kind="tumor",
                x=x,
                y=y,
                state=NodeVisualState.OVERACTIVE,
                color=VISUAL_LEGEND["overactive"]["color"],
                inspect={"population": "tumor", "x": x, "y": y},
            )
        )
    for i, (x, y) in enumerate(ctl_xy):
        cells.append(
            CellAgentVisual(
                cell_id=f"ctl_{i}",
                kind="ctl",
                x=x,
                y=y,
                state=NodeVisualState.HOMEOSTATIC,
                color="#00E5FF",
                inspect={"population": "ctl", "x": x, "y": y},
            )
        )
    for i, (x, y) in enumerate(macro_xy):
        cells.append(
            CellAgentVisual(
                cell_id=f"macro_{i}",
                kind="macrophage",
                x=x,
                y=y,
                state=NodeVisualState.HOMEOSTATIC,
                color="#FBBF24",
                inspect={"population": "macrophage", "x": x, "y": y},
            )
        )

    def _field(cx: float, cy: float, amp: float) -> List[List[float]]:
        sigma = max(0.05, diffusion)
        rows: List[List[float]] = []
        for gy in range(grid):
            row: List[float] = []
            for gx in range(grid):
                x = (gx + 0.5) / grid
                y = (gy + 0.5) / grid
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                row.append(amp * math.exp(-d2 / (2 * sigma**2)))
            rows.append(row)
        return rows

    # Time-expanding diffusion radius proxy
    amp_t = 0.55 + 0.35 * math.sin(t / 8.0) ** 2
    fields = [
        CytokineFieldFrame("TGFb", t, grid, grid, _field(*tgfb_center, amp_t), "#FB923C"),
        CytokineFieldFrame("IL6", t, grid, grid, _field(*il6_center, amp_t * 0.85), "#A78BFA"),
    ]
    return MicroenvironmentVisual(cells=cells, fields=fields, t=t)


def make_demo_visual_timeline(
    network: SignalingNetwork,
    trajectory: TrajectoryResult,
    *,
    mutated: Sequence[str] = ("EGFR",),
    drug_target: Optional[str] = "MEK",
) -> VisualTimeline:
    """Convenience demo export used by tests and the Streamlit/React bridge."""
    # Resolve names → ids
    name_to_id = {network.registry.get(n).name.upper(): n for n in network.nodes()}
    mut_ids = tuple(name_to_id[m] for m in mutated if m.upper() in name_to_id)
    drug_ids = ()
    if drug_target and drug_target.upper() in name_to_id:
        drug_ids = (name_to_id[drug_target.upper()],)
    cfg = VisualTranslatorConfig(mutated_ids=mut_ids, drug_blocked_targets=drug_ids)
    return VisualPathwayTranslator(cfg).timeline_from_trajectory(network, trajectory)
