"""
Cistron Virtual Cellular Laboratory — polished Streamlit dashboard.

Launch::

    streamlit run cistron/ui/app.py
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import math

from cistron.lifecycle import (
    PLATFORM_PRESETS,
    DrugPerturbation,
    CistronPipeline,
    CistronPipelineConfig,
    CistronPipelineResult,
    load_activity_graph,
)
from cistron.models.graph import CausalActivityGraph
from cistron.models.serialization import ScrubberPayload


# ---------------------------------------------------------------------------
# Design system (injected on every page load)
# ---------------------------------------------------------------------------

_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --vs-bg: #0B0F17;
    --vs-panel: rgba(255, 255, 255, 0.03);
    --vs-panel-strong: rgba(255, 255, 255, 0.055);
    --vs-border: #1E293B;
    --vs-border-soft: rgba(30, 41, 59, 0.85);
    --vs-emerald: #10B981;
    --vs-emerald-glow: rgba(16, 185, 129, 0.35);
    --vs-coral: #FF5252;
    --vs-coral-glow: rgba(255, 82, 82, 0.28);
    --vs-text: #F1F5F9;
    --vs-muted: #94A3B8;
    --vs-subtle: #64748B;
  }

  html, body, [class*="css"] {
    font-family: "Inter", system-ui, -apple-system, sans-serif !important;
  }

  .stApp {
    background:
      radial-gradient(1200px 600px at 12% -10%, rgba(16, 185, 129, 0.08), transparent 55%),
      radial-gradient(900px 500px at 90% 0%, rgba(255, 82, 82, 0.06), transparent 50%),
      var(--vs-bg) !important;
    color: var(--vs-text);
  }

  .block-container {
    padding-top: 1.1rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1440px !important;
  }

  h1, h2, h3, h4, .vcl-heading {
    font-family: "Plus Jakarta Sans", "Inter", sans-serif !important;
    color: var(--vs-text) !important;
    letter-spacing: -0.03em;
    font-weight: 700 !important;
  }

  p, label, .stMarkdown, .stCaption {
    color: var(--vs-muted);
  }

  /* Sidebar dock */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0C121C 0%, #0B0F17 100%) !important;
    border-right: 1px solid var(--vs-border) !important;
  }
  [data-testid="stSidebar"] > div:first-child {
    padding-top: 0.75rem;
  }

  /* Glass cards */
  .glass-card {
    background: var(--vs-panel);
    border: 1px solid var(--vs-border);
    border-radius: 14px;
    padding: 0.95rem 1.05rem 1.05rem;
    margin: 0.55rem 0 0.9rem;
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    box-shadow: 0 0 0 1px rgba(255,255,255,0.02) inset,
                0 12px 40px rgba(0, 0, 0, 0.28);
  }
  .glass-card h3, .glass-card .card-title {
    font-family: "Plus Jakarta Sans", Inter, sans-serif !important;
    font-size: 0.78rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--vs-text) !important;
    margin: 0 0 0.65rem 0 !important;
  }
  .glass-card .card-hint {
    font-size: 0.78rem;
    color: var(--vs-subtle);
    margin: -0.35rem 0 0.75rem;
  }

  /* Header bar */
  .vcl-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.85rem 1.15rem;
    margin-bottom: 1.1rem;
    background: var(--vs-panel);
    border: 1px solid var(--vs-border);
    border-radius: 16px;
    backdrop-filter: blur(16px);
  }
  .vcl-brand-wrap { display: flex; align-items: center; gap: 0.85rem; }
  .vcl-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 10px;
    background: linear-gradient(145deg, rgba(16,185,129,0.25), rgba(255,82,82,0.18));
    border: 1px solid rgba(16, 185, 129, 0.35);
    color: #ECFDF5;
    font-family: "Plus Jakarta Sans", Inter, sans-serif;
    font-weight: 800;
    font-size: 0.95rem;
    box-shadow: 0 0 24px var(--vs-emerald-glow);
  }
  .vcl-brand-text { display: flex; flex-direction: column; gap: 0.05rem; }
  .vcl-brand-name {
    font-family: "Plus Jakarta Sans", Inter, sans-serif;
    font-weight: 800;
    font-size: 1.15rem;
    color: var(--vs-text);
    letter-spacing: -0.03em;
    line-height: 1.1;
  }
  .vcl-brand-sub {
    font-size: 0.75rem;
    color: var(--vs-subtle);
    letter-spacing: 0.02em;
  }
  .vcl-header-meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .vcl-status {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    border: 1px solid rgba(16, 185, 129, 0.35);
    background: rgba(16, 185, 129, 0.08);
    color: #6EE7B7;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.06em;
  }
  .vcl-status .dot {
    width: 0.45rem;
    height: 0.45rem;
    border-radius: 50%;
    background: var(--vs-emerald);
    box-shadow: 0 0 10px var(--vs-emerald-glow);
  }
  .vcl-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    border: 1px solid var(--vs-border);
    background: var(--vs-panel-strong);
    color: var(--vs-muted);
    font-size: 0.72rem;
    font-weight: 500;
  }
  .vcl-pill strong { color: var(--vs-text); font-weight: 600; margin-left: 0.25rem; }

  /* Metric strip */
  .metric-strip {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    margin-bottom: 1rem;
  }
  .metric-tile {
    background: var(--vs-panel);
    border: 1px solid var(--vs-border);
    border-radius: 14px;
    padding: 0.85rem 1rem;
  }
  .metric-tile .label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--vs-subtle);
    margin-bottom: 0.35rem;
  }
  .metric-tile .value {
    font-family: "Plus Jakarta Sans", Inter, sans-serif;
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--vs-text);
    letter-spacing: -0.03em;
  }
  .metric-tile .value.emerald { color: #34D399; }
  .metric-tile .value.coral { color: #FF8A80; }

  .section-label {
    font-family: "Plus Jakarta Sans", Inter, sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--vs-text);
    margin: 0.4rem 0 0.35rem;
  }
  .section-hint {
    font-size: 0.78rem;
    color: var(--vs-subtle);
    margin-bottom: 0.55rem;
  }

  .scrub-rail {
    background: var(--vs-panel);
    border: 1px solid var(--vs-border);
    border-radius: 14px;
    padding: 0.85rem 1rem 0.35rem;
    margin-bottom: 0.85rem;
  }
  .scrub-labels {
    display: flex;
    justify-content: space-between;
    font-size: 0.72rem;
    color: var(--vs-subtle);
    font-family: "Plus Jakarta Sans", Inter, sans-serif;
    letter-spacing: 0.04em;
    margin-bottom: 0.15rem;
  }
  .path-chip {
    display: inline-block;
    padding: 0.35rem 0.65rem;
    margin: 0.2rem 0.25rem 0.2rem 0;
    border-radius: 8px;
    background: rgba(16, 185, 129, 0.1);
    border: 1px solid rgba(16, 185, 129, 0.28);
    color: #A7F3D0;
    font-size: 0.78rem;
    font-weight: 500;
  }
  .narrative-box {
    background: var(--vs-panel-strong);
    border: 1px solid var(--vs-border);
    border-radius: 12px;
    padding: 0.9rem 1rem;
    color: #CBD5E1;
    font-size: 0.9rem;
    line-height: 1.55;
  }
  .empty-hero {
    background: var(--vs-panel);
    border: 1px dashed var(--vs-border);
    border-radius: 16px;
    padding: 2.5rem 1.5rem;
    text-align: center;
  }
  .empty-hero h2 {
    margin-bottom: 0.4rem !important;
  }

  /* Widgets */
  .stButton > button {
    border-radius: 10px !important;
    font-family: "Plus Jakarta Sans", Inter, sans-serif !important;
    font-weight: 650 !important;
    letter-spacing: 0.02em;
    border: 1px solid rgba(255, 82, 82, 0.45) !important;
    background: linear-gradient(180deg, #FF6B6B 0%, #FF5252 100%) !important;
    color: white !important;
    box-shadow: 0 8px 24px var(--vs-coral-glow);
    transition: transform 0.12s ease, box-shadow 0.12s ease;
  }
  .stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 12px 28px var(--vs-coral-glow);
  }
  .stButton > button[kind="secondary"] {
    background: var(--vs-panel-strong) !important;
    border: 1px solid var(--vs-border) !important;
    color: var(--vs-text) !important;
    box-shadow: none !important;
  }

  div[data-baseweb="select"] > div,
  div[data-baseweb="input"] > div,
  .stMultiSelect > div > div {
    background-color: rgba(15, 23, 42, 0.75) !important;
    border-color: var(--vs-border) !important;
    border-radius: 10px !important;
  }

  [data-testid="stSlider"] > div {
    padding-top: 0.2rem;
  }
  [data-testid="stThumbValue"] {
    color: #6EE7B7 !important;
  }

  div[data-testid="stTabs"] button {
    font-family: "Plus Jakarta Sans", Inter, sans-serif !important;
    font-weight: 600 !important;
    color: var(--vs-muted) !important;
  }
  div[data-testid="stTabs"] button[aria-selected="true"] {
    color: #6EE7B7 !important;
  }

  [data-testid="stMetricValue"] {
    font-family: "Plus Jakarta Sans", Inter, sans-serif !important;
    color: #34D399 !important;
  }

  /* Hide default chrome noise */
  #MainMenu { visibility: hidden; }
  footer { visibility: hidden; }
  header[data-testid="stHeader"] { background: transparent; }
</style>
"""

FOCUS_SERIES: Dict[str, Tuple[str, ...]] = {
    "hypoxia": ("O2", "EGLN1", "HIF1A", "VEGFA", "GLUT1"),
    "mapk": ("EGF", "EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1"),
}

NODE_COLORS: Dict[str, str] = {
    "O2": "#38BDF8",
    "EGLN1": "#A78BFA",
    "HIF1A": "#FF5252",
    "VEGFA": "#10B981",
    "GLUT1": "#FBBF24",
    "MTOR": "#FB7185",
    "EGF": "#38BDF8",
    "EGFR": "#A78BFA",
    "KRAS": "#FF5252",
    "BRAF": "#FBBF24",
    "MAP2K1": "#34D399",
    "MAPK1": "#10B981",
    "FOS": "#F472B6",
}

DEFAULT_CLAMPS: Dict[str, float] = {"hypoxia": 0.0, "mapk": 0.8}
CLAMP_NODE: Dict[str, str] = {"hypoxia": "O2", "mapk": "EGF"}
DEFAULT_PATH: Dict[str, Tuple[str, str]] = {
    "hypoxia": ("O2", "VEGFA"),
    "mapk": ("EGF", "MAPK1"),
}


def _require_streamlit() -> Any:
    try:
        import streamlit as st  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Streamlit is required for the Virtual Cellular Laboratory.\n"
            "Install with:  pip install 'cistron[ui]'"
        ) from exc
    return st


def _require_plotly() -> Any:
    try:
        import plotly.graph_objects as go  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Plotly is required for laboratory charts.\n"
            "Install with:  pip install 'cistron[ui]'"
        ) from exc
    return go


def _plotly_chart(st: Any, fig: Any, *, key: str) -> None:
    try:
        st.plotly_chart(fig, key=key, width="stretch", config={"displayModeBar": False})
    except TypeError:
        try:
            st.plotly_chart(fig, use_container_width=True, key=key, config={"displayModeBar": False})
        except TypeError:
            st.plotly_chart(fig, use_container_width=True, key=key)


def _glass_open(title: str, hint: str = "") -> str:
    hint_html = f'<div class="card-hint">{hint}</div>' if hint else ""
    return f'<div class="glass-card"><div class="card-title">{title}</div>{hint_html}'


def _glass_close() -> str:
    return "</div>"


# ---------------------------------------------------------------------------
# Scrubber lerp (client-side equivalent; no ODE re-run)
# ---------------------------------------------------------------------------


def lerp_at_time(
    payload: ScrubberPayload,
    t: float,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Linearly interpolate node activities and edge fluxes at time ``t``."""
    times = payload.time_steps
    if not times:
        return {}, {}
    if t <= times[0]:
        return (
            {k: float(v[0]) for k, v in payload.nodes.items()},
            {k: float(v[0]) for k, v in payload.edges.items()},
        )
    if t >= times[-1]:
        return (
            {k: float(v[-1]) for k, v in payload.nodes.items()},
            {k: float(v[-1]) for k, v in payload.edges.items()},
        )

    i1 = 1
    while i1 < len(times) and times[i1] < t:
        i1 += 1
    i0 = i1 - 1
    t0, t1 = times[i0], times[i1]
    w = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)

    def _lerp_series(series: Sequence[float]) -> float:
        return float(series[i0]) + w * (float(series[i1]) - float(series[i0]))

    return (
        {k: _lerp_series(v) for k, v in payload.nodes.items()},
        {k: _lerp_series(v) for k, v in payload.edges.items()},
    )


def _activity_color(y: float) -> str:
    y = max(0.0, min(1.0, y))
    if y < 0.33:
        return f"rgba(100, 116, 139, {0.4 + 0.35 * (y / 0.33)})"
    if y < 0.66:
        u = (y - 0.33) / 0.33
        return f"rgba(16, 185, 129, {0.45 + 0.4 * u})"
    u = (y - 0.66) / 0.34
    return f"rgba(255, 82, 82, {0.5 + 0.4 * u})"


def _layout_positions(symbols: Sequence[str]) -> Dict[str, Tuple[float, float]]:
    n = max(1, len(symbols))
    pos: Dict[str, Tuple[float, float]] = {}
    for i, sym in enumerate(sorted(symbols)):
        ang = 2.0 * math.pi * i / n - math.pi / 2.0
        pos[sym] = (math.cos(ang), math.sin(ang))
    return pos


def _plotly_dark_layout(**kwargs: Any) -> Dict[str, Any]:
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 42, 0.55)",
        font=dict(family="Inter, sans-serif", color="#94A3B8", size=12),
        margin=dict(l=36, r=16, t=44, b=36),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            font=dict(color="#E2E8F0", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    base.update(kwargs)
    return base


def build_network_figure(
    graph: CausalActivityGraph,
    node_y: Dict[str, float],
    edge_f: Dict[str, float],
    *,
    t: float,
    path_nodes: Optional[Sequence[str]] = None,
) -> Any:
    go = _require_plotly()
    symbols = list(graph.nodes.keys())
    pos = _layout_positions(symbols)
    path_set = set(path_nodes or ())

    edge_traces = []
    for edge in graph.edges:
        key = f"{edge.source}->{edge.target}"
        flux = float(edge_f.get(key, 0.0))
        x0, y0 = pos[edge.source]
        x1, y1 = pos[edge.target]
        on_path = edge.source in path_set and edge.target in path_set
        width = 1.4 + 5.5 * flux
        if on_path:
            color = f"rgba(16, 185, 129, {0.45 + 0.5 * flux})"
        elif edge.sign > 0:
            color = f"rgba(56, 189, 248, {0.2 + 0.65 * flux})"
        else:
            color = f"rgba(255, 82, 82, {0.22 + 0.65 * flux})"
        edge_traces.append(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(width=width, color=color),
                hoverinfo="text",
                text=f"{key}<br>flux F={flux:.3f} @ t={t:.1f} min",
                showlegend=False,
            )
        )

    xs, ys, texts, colors, sizes, outlines, outline_w = [], [], [], [], [], [], []
    for sym in symbols:
        x, y = pos[sym]
        act = float(node_y.get(sym, 0.0))
        xs.append(x)
        ys.append(y)
        texts.append(f"<b>{sym}</b><br>y={act:.3f}")
        colors.append(NODE_COLORS.get(sym, _activity_color(act)))
        sizes.append(20 + 26 * act)
        outlines.append("#10B981" if sym in path_set else "#1E293B")
        outline_w.append(3 if sym in path_set else 1.5)

    node_trace = go.Scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        text=list(symbols),
        textposition="top center",
        textfont=dict(color="#F1F5F9", size=11, family="Plus Jakarta Sans, Inter, sans-serif"),
        marker=dict(
            size=sizes,
            color=colors,
            opacity=0.92,
            line=dict(width=outline_w, color=outlines),
        ),
        hovertext=texts,
        hoverinfo="text",
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        **_plotly_dark_layout(
            title=dict(
                text=f"Causal activity flow · t = {t:.0f} min",
                font=dict(color="#F1F5F9", size=14, family="Plus Jakarta Sans, Inter"),
            ),
            xaxis=dict(visible=False, scaleanchor="y", scaleratio=1),
            yaxis=dict(visible=False),
            height=400,
            margin=dict(l=12, r=12, t=48, b=12),
        )
    )
    return fig


def build_trajectory_figure(
    payload: ScrubberPayload,
    *,
    focus: Sequence[str],
    playhead: float,
) -> Any:
    go = _require_plotly()
    fig = go.Figure()
    times = payload.time_steps
    shown = [s for s in focus if s in payload.nodes] or list(payload.nodes.keys())[:6]
    fallback = ["#38BDF8", "#10B981", "#FF5252", "#FBBF24", "#A78BFA", "#F472B6"]
    for i, sym in enumerate(shown):
        color = NODE_COLORS.get(sym, fallback[i % len(fallback)])
        fig.add_trace(
            go.Scatter(
                x=times,
                y=payload.nodes[sym],
                mode="lines",
                name=sym,
                line=dict(color=color, width=2.4, shape="spline"),
                hovertemplate=f"{sym}: %{{y:.3f}}<extra></extra>",
            )
        )
    fig.add_vline(
        x=playhead,
        line_width=1.8,
        line_dash="dot",
        line_color="#10B981",
        annotation_text=f"t={playhead:.0f}",
        annotation_font_color="#6EE7B7",
        annotation_font_size=11,
    )
    fig.update_layout(
        **_plotly_dark_layout(
            title=dict(
                text="Activation trajectories  yᵢ(t)",
                font=dict(color="#F1F5F9", size=14, family="Plus Jakarta Sans, Inter"),
            ),
            xaxis=dict(
                title="Time (min)",
                color="#64748B",
                gridcolor="rgba(30, 41, 59, 0.9)",
                zeroline=False,
                range=[0, 60],
            ),
            yaxis=dict(
                title="Activity",
                color="#64748B",
                gridcolor="rgba(30, 41, 59, 0.9)",
                zeroline=False,
                range=[0, 1.05],
            ),
            height=340,
        )
    )
    return fig


# ---------------------------------------------------------------------------
# Session / pipeline
# ---------------------------------------------------------------------------


def _init_state(st: Any) -> None:
    defaults = {
        "pipeline_result": None,
        "pipeline_graph": None,
        "run_fingerprint": None,
        "scrub_t": 0.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _fingerprint(cfg: CistronPipelineConfig) -> str:
    return cfg.model_dump_json()


def run_pipeline(cfg: CistronPipelineConfig) -> Tuple[CistronPipelineResult, CausalActivityGraph]:
    graph = load_activity_graph(cfg.preset)
    result = CistronPipeline(cfg, graph=graph).run()
    return result, graph


def _max_flux(edge_f: Dict[str, float]) -> float:
    return max(edge_f.values()) if edge_f else 0.0


def _top_regulator(result: CistronPipelineResult) -> str:
    regs = result.prioritization.master_regulators
    return regs[0][0] if regs else "—"


# ---------------------------------------------------------------------------
# Layout sections
# ---------------------------------------------------------------------------


def render_header(st: Any, result: Optional[CistronPipelineResult]) -> None:
    ready = result is not None
    status = "ENGINE READY" if ready else "AWAITING RUN"
    runtime = f"{result.elapsed_ms:.1f} ms" if result else "—"
    sim_id = result.scrubber.simulation_id if result else "—"
    st.markdown(
        f"""
        <div class="vcl-header">
          <div class="vcl-brand-wrap">
            <div class="vcl-badge">VS</div>
            <div class="vcl-brand-text">
              <div class="vcl-brand-name">Cistron</div>
              <div class="vcl-brand-sub">Virtual Cellular Laboratory</div>
            </div>
          </div>
          <div class="vcl-header-meta">
            <div class="vcl-status"><span class="dot"></span> {status}</div>
            <div class="vcl-pill">Runtime<strong>{runtime}</strong></div>
            <div class="vcl-pill">Sim<strong>{sim_id}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_control_dock(st: Any) -> Tuple[CistronPipelineConfig, bool]:
    """Left sidebar — glass-grouped experiment controls."""
    st.sidebar.markdown(
        '<div style="font-family:Plus Jakarta Sans,Inter,sans-serif;font-weight:800;'
        'font-size:1.05rem;color:#F1F5F9;letter-spacing:-0.02em;margin:0.2rem 0 0.15rem;">'
        "Control Dock</div>"
        '<div style="color:#64748B;font-size:0.78rem;margin-bottom:0.85rem;">'
        "Configure stress, knockouts, and pharmacology</div>",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown(
        _glass_open("Stress Scenario", "Network scaffold and environmental driver"),
        unsafe_allow_html=True,
    )
    preset = st.sidebar.selectbox(
        "Network preset",
        options=sorted(PLATFORM_PRESETS.keys()),
        index=0,
        label_visibility="collapsed",
        help="Activity-flow scaffold",
    )
    scenario = st.sidebar.selectbox(
        "Scenario profile",
        options={
            "hypoxia": ["Hypoxia stress (low O₂)", "Normoxia (high O₂)", "Custom"],
            "mapk": ["Ligand pulse", "Custom"],
        }.get(preset, ["Custom"]),
    )
    st.sidebar.markdown(_glass_close(), unsafe_allow_html=True)

    graph_preview = load_activity_graph(preset)
    symbols = graph_preview.node_symbols()
    clamp_node = CLAMP_NODE.get(preset, symbols[0] if symbols else "O2")

    default_clamp = DEFAULT_CLAMPS.get(preset, 0.5)
    if "Normoxia" in scenario:
        default_clamp = 1.0
    elif "Hypoxia" in scenario:
        default_clamp = 0.0

    st.sidebar.markdown(
        _glass_open("Gene Knockouts & Clamps", "LoF knockouts (wᵢ=0) and fixed node clamps"),
        unsafe_allow_html=True,
    )
    clamp_val = st.sidebar.slider(
        f"Clamp · {clamp_node}",
        min_value=0.0,
        max_value=1.0,
        value=float(default_clamp),
        step=0.05,
        help="Fixed environmental / ligand activity",
    )
    ko_candidates = [s for s in symbols if s != clamp_node]
    knockouts = st.sidebar.multiselect(
        "Knockouts",
        options=ko_candidates,
        default=[],
        placeholder="Select genes…",
    )
    st.sidebar.markdown(_glass_close(), unsafe_allow_html=True)

    st.sidebar.markdown(
        _glass_open("Pharmacology (PK/PD)", "Inhibitor occupancy via C / (C + Ki)"),
        unsafe_allow_html=True,
    )
    enable_drug = st.sidebar.checkbox("Enable inhibitor", value=False)
    drug_target = st.sidebar.selectbox(
        "Target",
        options=symbols,
        index=min(2, max(0, len(symbols) - 1)),
        disabled=not enable_drug,
    )
    c_drug = st.sidebar.slider("Concentration C", 0.0, 50.0, 5.0, 0.5, disabled=not enable_drug)
    ki = st.sidebar.slider("Ki", 0.1, 20.0, 1.0, 0.1, disabled=not enable_drug)
    st.sidebar.markdown(_glass_close(), unsafe_allow_html=True)

    src_default, tgt_default = DEFAULT_PATH.get(preset, (symbols[0], symbols[-1]))
    with st.sidebar.expander("Causal path endpoints", expanded=False):
        source_node = st.selectbox(
            "Source",
            options=symbols,
            index=symbols.index(src_default) if src_default in symbols else 0,
        )
        target_node = st.selectbox(
            "Target",
            options=symbols,
            index=symbols.index(tgt_default) if tgt_default in symbols else len(symbols) - 1,
        )

    drugs: List[DrugPerturbation] = []
    if enable_drug:
        drugs.append(DrugPerturbation(target=drug_target, c_drug=c_drug, ki=ki))

    cfg = CistronPipelineConfig(
        preset=preset,
        clamps={clamp_node: clamp_val},
        knockouts=list(knockouts),
        drugs=drugs,
        source_node=source_node,
        target_node=target_node,
        simulation_id=f"lab_{preset}",
    )

    run = st.sidebar.button("Run Simulation", type="primary", use_container_width=True)
    if st.session_state.pipeline_result is not None:
        st.sidebar.caption("Cached trajectory · scrubbing never re-integrates the ODE.")
    return cfg, run


def render_metric_strip(
    st: Any,
    result: CistronPipelineResult,
    node_y: Dict[str, float],
    edge_f: Dict[str, float],
) -> None:
    n_active = sum(1 for v in node_y.values() if v >= 0.35)
    flux = _max_flux(edge_f)
    top = _top_regulator(result)
    st.markdown(
        f"""
        <div class="metric-strip">
          <div class="metric-tile">
            <div class="label">Active nodes</div>
            <div class="value emerald">{n_active}<span style="font-size:0.85rem;color:#64748B">
            / {len(node_y)}</span></div>
          </div>
          <div class="metric-tile">
            <div class="label">Max dynamic flux</div>
            <div class="value">{flux:.3f}</div>
          </div>
          <div class="metric-tile">
            <div class="label">Master regulator</div>
            <div class="value coral">{top}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_intelligence_drawer(st: Any, result: CistronPipelineResult) -> None:
    st.markdown('<div class="section-label">Intelligence Drawer</div>', unsafe_allow_html=True)
    tab_gat, tab_path, tab_prompt = st.tabs(
        ["Master Regulators (GAT)", "Causal Path Narrative", "LLM Prompt Grounding"]
    )

    with tab_gat:
        rows = []
        for name, score in result.prioritization.master_regulators[:12]:
            vec = result.prioritization.node_vectors.get(name)
            rows.append(
                {
                    "node": name,
                    "Sᵢ": round(score, 5),
                    "y₀": round(vec.y_init, 4) if vec else None,
                    "y₆₀": round(vec.y_final, 4) if vec else None,
                    "Δy": round(vec.delta_y, 4) if vec else None,
                    "w": round(vec.capacity, 4) if vec else None,
                    "KO": bool(vec.is_knocked_out) if vec else False,
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with tab_path:
        brief = result.discovery_brief or "No causal narrative available for this run."
        st.markdown(f'<div class="narrative-box">{brief}</div>', unsafe_allow_html=True)
        if result.causal_context and result.causal_context.extracted_paths:
            path = result.causal_context.extracted_paths[0]
            st.markdown(
                f'<span class="path-chip">{" → ".join(path.nodes)}</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"Σα = {path.cumulative_attention:.4f} · mechanisms = {path.mechanisms} · "
                f"signs = {path.signs}"
            )

    with tab_prompt:
        st.caption("Grounded, hallucination-free prompt payload for downstream LLM synthesis.")
        st.code(result.discovery_prompt or "(empty)", language="markdown")


def render_studio(
    st: Any,
    result: CistronPipelineResult,
    graph: CausalActivityGraph,
) -> None:
    payload = result.scrubber
    focus = FOCUS_SERIES.get(result.preset, tuple(payload.nodes.keys())[:5])

    st.markdown(
        '<div class="scrub-rail">'
        '<div class="scrub-labels"><span>t₀ · 0 min</span>'
        "<span>KEYFRAME PLAYBACK · LERP ONLY</span>"
        "<span>t₆₀ · 60 min</span></div>",
        unsafe_allow_html=True,
    )
    t = st.slider(
        "Timeline scrubber",
        min_value=0.0,
        max_value=60.0,
        value=float(st.session_state.get("scrub_t", 0.0)),
        step=1.0,
        key="scrub_t",
        label_visibility="collapsed",
        help="Scrubbing interpolates cached keyframes — the ODE is never re-run.",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    node_y, edge_f = lerp_at_time(payload, t)
    render_metric_strip(st, result, node_y, edge_f)

    path_nodes: List[str] = []
    if result.causal_context and result.causal_context.extracted_paths:
        path_nodes = list(result.causal_context.extracted_paths[0].nodes)

    left, right = st.columns([1.15, 0.95], gap="medium")
    with left:
        st.markdown('<div class="section-label">Network canvas</div>', unsafe_allow_html=True)
        fig_net = build_network_figure(graph, node_y, edge_f, t=t, path_nodes=path_nodes)
        _plotly_chart(st, fig_net, key="net_fig")
        spotlight = [s for s in focus if s in node_y][:5]
        if spotlight:
            chips = " · ".join(f"**{s}** `{node_y[s]:.3f}`" for s in spotlight)
            st.caption(f"Playhead · {chips}")

        st.markdown('<div class="section-label">ODE trajectories</div>', unsafe_allow_html=True)
        fig_traj = build_trajectory_figure(payload, focus=focus, playhead=t)
        _plotly_chart(st, fig_traj, key="traj_fig")

    with right:
        render_intelligence_drawer(st, result)


def render_empty_state(st: Any, cfg: CistronPipelineConfig) -> None:
    preview = load_activity_graph(cfg.preset)
    st.markdown(
        f"""
        <div class="empty-hero">
          <h2>Ready when you are</h2>
          <p style="color:#94A3B8;max-width:32rem;margin:0.4rem auto 0.9rem;">
            Configure a stress scenario in the control dock, then run the Hill-cube
            engine to populate the studio canvas, GAT rankings, and BioReasoner brief.
          </p>
          <div class="vcl-pill" style="display:inline-flex;">
            Scaffold<strong>{preview.name}</strong>
            &nbsp;·&nbsp; {len(preview.nodes)} nodes · {len(preview.edges)} edges
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st = _require_streamlit()
    st.set_page_config(
        page_title="Cistron Laboratory",
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_state(st)

    cfg, run_clicked = render_control_dock(st)

    if run_clicked:
        fp = _fingerprint(cfg)
        with st.spinner("Integrating Hill-cube ODE · GAT attention · BioReasoner…"):
            result, graph = run_pipeline(cfg)
        st.session_state.pipeline_result = result
        st.session_state.pipeline_graph = graph
        st.session_state.run_fingerprint = fp
        st.session_state.scrub_t = 0.0
        st.toast(f"Simulation ready in {result.elapsed_ms:.1f} ms", icon="⚡")

    result: Optional[CistronPipelineResult] = st.session_state.pipeline_result
    graph: Optional[CausalActivityGraph] = st.session_state.pipeline_graph

    render_header(st, result)

    if result is None or graph is None:
        render_empty_state(st, cfg)
        return

    render_studio(st, result, graph)


if __name__ == "__main__":
    main()
