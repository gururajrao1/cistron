"""
Pathway & network graph renderer for VOIDSIGNAL Phase 9.

Builds interactive SVG / HTML views of a :class:`~voidsignal.topology.SignalingNetwork`
with concentration- or fold-change colouring, interaction-typed edges, hub / loop
highlights, and optional GNN target-rank badges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import html
import logging
import math

from voidsignal.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _clamp01(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return max(0.0, min(1.0, x))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def value_to_color(value: float, *, vmin: float = 0.0, vmax: float = 1.0) -> str:
    """
    Map a scalar onto a blue→cyan→yellow→red ramp (SVG-safe hex).
    """
    if vmax <= vmin:
        t = 0.0
    else:
        t = _clamp01((value - vmin) / (vmax - vmin))
    # piecewise RGB
    if t < 0.33:
        u = t / 0.33
        r, g, b = 30, int(_lerp(80, 200, u)), int(_lerp(200, 220, u))
    elif t < 0.66:
        u = (t - 0.33) / 0.33
        r, g, b = int(_lerp(30, 240, u)), int(_lerp(200, 200, u)), int(_lerp(220, 40, u))
    else:
        u = (t - 0.66) / 0.34
        r, g, b = int(_lerp(240, 200, u)), int(_lerp(200, 40, u)), int(_lerp(40, 40, u))
    return f"#{r:02x}{g:02x}{b:02x}"


def edge_color(interaction: InteractionType) -> str:
    if interaction.is_inhibitory:
        return "#c0392b"
    if interaction.is_catalytic:
        return "#8e44ad"
    if interaction is InteractionType.BINDING:
        return "#2980b9"
    if interaction is InteractionType.TRANSLOCATION:
        return "#16a085"
    return "#2c3e50"


def edge_dash(interaction: InteractionType) -> str:
    if interaction.is_inhibitory:
        return "6,4"
    if interaction.is_catalytic:
        return "2,3"
    return "none"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


@dataclass
class NodeLayout:
    entity_id: str
    name: str
    x: float
    y: float
    value: float
    color: str
    radius: float
    is_hub: bool = False
    in_feedback: bool = False
    rank: Optional[int] = None
    rank_score: Optional[float] = None


@dataclass
class EdgeLayout:
    edge_id: str
    source_id: str
    target_id: str
    interaction: str
    color: str
    dash: str
    width: float
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class NetworkViewConfig:
    width: float = 900.0
    height: float = 640.0
    margin: float = 48.0
    base_radius: float = 18.0
    hub_radius_boost: float = 8.0
    iterations: int = 80
    seed_layout: str = "circular"
    """``circular`` | ``grid``"""


@dataclass
class NetworkViewModel:
    """Serializable view model for SVG/HTML/Plotly consumers."""

    nodes: List[NodeLayout]
    edges: List[EdgeLayout]
    width: float
    height: float
    value_label: str
    vmin: float
    vmax: float
    feedback_loops: List[List[str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "value_label": self.value_label,
            "vmin": self.vmin,
            "vmax": self.vmax,
            "nodes": [
                {
                    "entity_id": n.entity_id,
                    "name": n.name,
                    "x": n.x,
                    "y": n.y,
                    "value": n.value,
                    "color": n.color,
                    "radius": n.radius,
                    "is_hub": n.is_hub,
                    "in_feedback": n.in_feedback,
                    "rank": n.rank,
                    "rank_score": n.rank_score,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "edge_id": e.edge_id,
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "interaction": e.interaction,
                    "color": e.color,
                    "dash": e.dash,
                    "width": e.width,
                    "x1": e.x1,
                    "y1": e.y1,
                    "x2": e.x2,
                    "y2": e.y2,
                }
                for e in self.edges
            ],
            "feedback_loops": self.feedback_loops,
            "metadata": dict(self.metadata),
        }


def _initial_positions(
    n: int,
    width: float,
    height: float,
    margin: float,
    mode: str,
) -> List[Tuple[float, float]]:
    cx, cy = width / 2.0, height / 2.0
    if n == 0:
        return []
    if mode == "grid":
        cols = max(1, int(math.ceil(math.sqrt(n))))
        rows = max(1, int(math.ceil(n / cols)))
        dx = (width - 2 * margin) / max(cols - 1, 1)
        dy = (height - 2 * margin) / max(rows - 1, 1)
        pts = []
        for i in range(n):
            r, c = divmod(i, cols)
            pts.append((margin + c * dx, margin + r * dy))
        return pts
    # circular
    radius = min(width, height) / 2.0 - margin
    pts = []
    for i in range(n):
        ang = 2.0 * math.pi * i / n - math.pi / 2.0
        pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    return pts


def _force_layout(
    n: int,
    edges: Sequence[Tuple[int, int]],
    width: float,
    height: float,
    margin: float,
    positions: List[Tuple[float, float]],
    iterations: int,
) -> List[Tuple[float, float]]:
    """Lightweight Fruchterman–Reingold-style relaxation (pure Python)."""
    if n <= 1:
        return positions
    pos = [[p[0], p[1]] for p in positions]
    area = max((width - 2 * margin) * (height - 2 * margin), 1.0)
    k = math.sqrt(area / n)
    temp = min(width, height) / 10.0
    for _ in range(max(1, iterations)):
        disp = [[0.0, 0.0] for _ in range(n)]
        # repulsion
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.sqrt(dx * dx + dy * dy) + 1e-6
                force = (k * k) / dist
                fx, fy = force * dx / dist, force * dy / dist
                disp[i][0] += fx
                disp[i][1] += fy
                disp[j][0] -= fx
                disp[j][1] -= fy
        # attraction
        for i, j in edges:
            dx = pos[i][0] - pos[j][0]
            dy = pos[i][1] - pos[j][1]
            dist = math.sqrt(dx * dx + dy * dy) + 1e-6
            force = (dist * dist) / k
            fx, fy = force * dx / dist, force * dy / dist
            disp[i][0] -= fx
            disp[i][1] -= fy
            disp[j][0] += fx
            disp[j][1] += fy
        # move
        for i in range(n):
            dx, dy = disp[i]
            norm = math.sqrt(dx * dx + dy * dy) + 1e-6
            pos[i][0] += (dx / norm) * min(norm, temp)
            pos[i][1] += (dy / norm) * min(norm, temp)
            pos[i][0] = max(margin, min(width - margin, pos[i][0]))
            pos[i][1] = max(margin, min(height - margin, pos[i][1]))
        temp *= 0.92
    return [(p[0], p[1]) for p in pos]


def build_network_view(
    network: SignalingNetwork,
    *,
    values: Optional[Mapping[str, float]] = None,
    value_label: str = "concentration",
    ranks: Optional[Mapping[str, float]] = None,
    config: Optional[NetworkViewConfig] = None,
) -> NetworkViewModel:
    """
    Compile a layout model from ``network``.

    Parameters
    ----------
    values :
        entity_id → scalar used for node colour (concentrations or fold-changes).
        Defaults to live registry concentrations.
    ranks :
        entity_id → GNN prioritization score (higher = better target). Top ranks
        receive badges 1..k.
    """
    cfg = config or NetworkViewConfig()
    node_ids = list(network.nodes())
    # drop pure compartment markers if present
    from voidsignal.components import EntityType

    node_ids = [
        nid
        for nid in node_ids
        if network.registry.get(nid).entity_type is not EntityType.COMPARTMENT
    ]
    n = len(node_ids)
    index = {nid: i for i, nid in enumerate(node_ids)}

    vals = dict(values) if values is not None else network.registry.concentrations()
    series = [float(vals.get(nid, 0.0)) for nid in node_ids]
    vmin = min(series) if series else 0.0
    vmax = max(series) if series else 1.0
    if abs(vmax - vmin) < 1e-12:
        vmax = vmin + 1.0

    hubs = {hid for hid, _ in network.find_hubs(top_k=max(1, min(5, n)))}
    loops = network.detect_feedback_loops(max_length=8)
    in_loop = {nid for cycle in loops for nid in cycle}

    rank_order: List[Tuple[str, float]] = []
    if ranks:
        rank_order = sorted(ranks.items(), key=lambda kv: kv[1], reverse=True)
    rank_map = {eid: (i + 1, score) for i, (eid, score) in enumerate(rank_order[:8])}

    edge_pairs: List[Tuple[int, int]] = []
    active_edges = []
    for edge in network.active_edges():
        if edge.source_id not in index or edge.target_id not in index:
            continue
        edge_pairs.append((index[edge.source_id], index[edge.target_id]))
        active_edges.append(edge)

    positions = _initial_positions(n, cfg.width, cfg.height, cfg.margin, cfg.seed_layout)
    positions = _force_layout(
        n, edge_pairs, cfg.width, cfg.height, cfg.margin, positions, cfg.iterations
    )

    nodes: List[NodeLayout] = []
    for i, nid in enumerate(node_ids):
        ent = network.registry.get(nid)
        val = float(vals.get(nid, 0.0))
        is_hub = nid in hubs
        r = cfg.base_radius + (cfg.hub_radius_boost if is_hub else 0.0)
        rk = rank_map.get(nid)
        nodes.append(
            NodeLayout(
                entity_id=nid,
                name=ent.name,
                x=positions[i][0],
                y=positions[i][1],
                value=val,
                color=value_to_color(val, vmin=vmin, vmax=vmax),
                radius=r,
                is_hub=is_hub,
                in_feedback=nid in in_loop,
                rank=rk[0] if rk else None,
                rank_score=rk[1] if rk else None,
            )
        )

    pos_by_id = {node_ids[i]: positions[i] for i in range(n)}
    edges_out: List[EdgeLayout] = []
    for edge in active_edges:
        x1, y1 = pos_by_id[edge.source_id]
        x2, y2 = pos_by_id[edge.target_id]
        # shorten to node radii
        dx, dy = x2 - x1, y2 - y1
        dist = math.sqrt(dx * dx + dy * dy) + 1e-6
        r1 = next(nd.radius for nd in nodes if nd.entity_id == edge.source_id)
        r2 = next(nd.radius for nd in nodes if nd.entity_id == edge.target_id)
        x1s = x1 + dx / dist * r1
        y1s = y1 + dy / dist * r1
        x2s = x2 - dx / dist * r2
        y2s = y2 - dy / dist * r2
        edges_out.append(
            EdgeLayout(
                edge_id=edge.edge_id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                interaction=edge.interaction_type.value,
                color=edge_color(edge.interaction_type),
                dash=edge_dash(edge.interaction_type),
                width=max(1.2, min(4.0, 1.0 + edge.weight)),
                x1=x1s,
                y1=y1s,
                x2=x2s,
                y2=y2s,
            )
        )

    return NetworkViewModel(
        nodes=nodes,
        edges=edges_out,
        width=cfg.width,
        height=cfg.height,
        value_label=value_label,
        vmin=vmin,
        vmax=vmax,
        feedback_loops=loops,
        metadata={"n_hubs": len(hubs), "n_loops": len(loops)},
    )


def render_network_svg(model: NetworkViewModel) -> str:
    """Return a self-contained SVG string (works headless)."""
    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{model.width:.0f}" '
        f'height="{model.height:.0f}" viewBox="0 0 {model.width:.0f} {model.height:.0f}">',
        "<defs>",
        '<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#2c3e50"/>',
        "</marker>",
        '<marker id="arrow-inh" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#c0392b"/>',
        "</marker>",
        "</defs>",
        f'<rect width="100%" height="100%" fill="#f7f9fb"/>',
        f'<text x="16" y="24" font-family="Segoe UI, Arial" font-size="14" fill="#333">'
        f"{html.escape(model.value_label)} "
        f"[{model.vmin:.2f}, {model.vmax:.2f}]</text>",
    ]
    for e in model.edges:
        marker = "arrow-inh" if e.interaction in {"inhibition", "degradation", "dephosphorylation"} else "arrow"
        dash = f' stroke-dasharray="{e.dash}"' if e.dash != "none" else ""
        parts.append(
            f'<line x1="{e.x1:.1f}" y1="{e.y1:.1f}" x2="{e.x2:.1f}" y2="{e.y2:.1f}" '
            f'stroke="{e.color}" stroke-width="{e.width:.1f}"{dash} '
            f'marker-end="url(#{marker})" opacity="0.85"/>'
        )
    for n in model.nodes:
        stroke = "#f39c12" if n.is_hub else ("#27ae60" if n.in_feedback else "#2c3e50")
        sw = 3.0 if n.is_hub or n.in_feedback else 1.5
        parts.append(
            f'<circle cx="{n.x:.1f}" cy="{n.y:.1f}" r="{n.radius:.1f}" '
            f'fill="{n.color}" stroke="{stroke}" stroke-width="{sw}"/>'
        )
        parts.append(
            f'<text x="{n.x:.1f}" y="{n.y + n.radius + 14:.1f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial" font-size="12" fill="#222">'
            f"{html.escape(n.name)}</text>"
        )
        if n.rank is not None:
            parts.append(
                f'<circle cx="{n.x + n.radius * 0.7:.1f}" cy="{n.y - n.radius * 0.7:.1f}" '
                f'r="9" fill="#111" stroke="#fff" stroke-width="1"/>'
                f'<text x="{n.x + n.radius * 0.7:.1f}" y="{n.y - n.radius * 0.7 + 3.5:.1f}" '
                f'text-anchor="middle" font-family="Segoe UI, Arial" font-size="10" fill="#fff">'
                f"{n.rank}</text>"
            )
    parts.append("</svg>")
    return "\n".join(parts)


def render_network_html(model: NetworkViewModel, *, title: str = "VOIDSIGNAL Network") -> str:
    """Minimal HTML document embedding the SVG (browser-ready)."""
    svg = render_network_svg(model)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:16px;background:#eef2f5;}"
        ".card{background:#fff;padding:12px;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08);}"
        "</style></head><body>"
        f"<h2>{html.escape(title)}</h2>"
        f"<div class='card'>{svg}</div>"
        f"<p>Hubs highlighted gold; feedback nodes green stroke; badges = GNN rank.</p>"
        "</body></html>"
    )


def try_plotly_network(model: NetworkViewModel) -> Any:
    """
    Optional Plotly figure. Returns ``None`` if Plotly is unavailable (headless OK).
    """
    try:
        import plotly.graph_objects as go  # type: ignore
    except ImportError:
        logger.debug("plotly not installed — skipping interactive network figure")
        return None

    edge_x: List[Optional[float]] = []
    edge_y: List[Optional[float]] = []
    for e in model.edges:
        edge_x += [e.x1, e.x2, None]
        edge_y += [e.y1, e.y2, None]
    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=1.5, color="#7f8c8d"),
        hoverinfo="none",
        name="edges",
    )
    node_trace = go.Scatter(
        x=[n.x for n in model.nodes],
        y=[n.y for n in model.nodes],
        mode="markers+text",
        text=[n.name for n in model.nodes],
        textposition="bottom center",
        marker=dict(
            size=[n.radius for n in model.nodes],
            color=[n.value for n in model.nodes],
            colorscale="Turbo",
            showscale=True,
            colorbar=dict(title=model.value_label),
            line=dict(width=2, color="#2c3e50"),
        ),
        customdata=[[n.value, n.rank, n.is_hub] for n in model.nodes],
        hovertemplate="%{text}<br>value=%{customdata[0]:.3f}<br>rank=%{customdata[1]}<extra></extra>",
        name="nodes",
    )
    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title="Signaling network",
        showlegend=False,
        width=int(model.width),
        height=int(model.height),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        plot_bgcolor="#f7f9fb",
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig
