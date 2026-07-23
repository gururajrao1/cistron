"""
Trajectory & pharmacology plotters for CISTRON Phase 9.

All builders return a :class:`FigureSpec` that serialises to JSON / SVG without
optional plotting libraries. When Plotly is installed, ``to_plotly()`` yields an
interactive figure; otherwise callers receive the SVG/ASCII fallbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import html
import logging
import math

from cistron.hpc_runner import ConfidenceBand, EnsembleResult
from cistron.pharmacology import DoseResponseCurve
from cistron.simulation import TrajectoryResult

logger = logging.getLogger(__name__)


@dataclass
class PlotSeries:
    """One named y-trace aligned to a shared x-axis (or its own x)."""

    name: str
    y: List[float]
    x: Optional[List[float]] = None
    color: Optional[str] = None
    style: str = "solid"
    """``solid`` | ``dash`` | ``dot`` | ``band``"""
    fill_to: Optional[str] = None
    """Name of another series to shade between (for CI bands)."""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FigureSpec:
    """Framework-agnostic plot description."""

    title: str
    xlabel: str
    ylabel: str
    series: List[PlotSeries]
    kind: str = "line"
    """``line`` | ``scatter`` | ``heatmap`` | ``band``"""
    heatmap: Optional[Dict[str, Any]] = None
    annotations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    width: int = 800
    height: int = 420

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "xlabel": self.xlabel,
            "ylabel": self.ylabel,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "annotations": list(self.annotations),
            "metadata": dict(self.metadata),
            "heatmap": self.heatmap,
            "series": [
                {
                    "name": s.name,
                    "x": list(s.x) if s.x is not None else None,
                    "y": list(s.y),
                    "color": s.color,
                    "style": s.style,
                    "fill_to": s.fill_to,
                    "metadata": dict(s.metadata),
                }
                for s in self.series
            ],
        }

    def to_plotly(self) -> Any:
        """Return a Plotly figure or ``None`` if Plotly is unavailable."""
        try:
            import plotly.graph_objects as go  # type: ignore
        except ImportError:
            logger.debug("plotly not installed — FigureSpec.to_plotly() → None")
            return None

        fig = go.Figure()
        if self.kind == "heatmap" and self.heatmap is not None:
            hm = self.heatmap
            fig.add_trace(
                go.Heatmap(
                    z=hm["z"],
                    x=hm.get("x"),
                    y=hm.get("y"),
                    colorscale=hm.get("colorscale", "RdBu_r"),
                    colorbar=dict(title=hm.get("colorbar_title", "")),
                    zmid=hm.get("zmid"),
                )
            )
        else:
            for s in self.series:
                x = s.x if s.x is not None else list(range(len(s.y)))
                dash = {"solid": "solid", "dash": "dash", "dot": "dot"}.get(s.style, "solid")
                if s.style == "band" or s.fill_to:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=s.y,
                        name=s.name,
                        mode="lines",
                        line=dict(color=s.color, dash=dash, width=2),
                    )
                )
            # CI bands: pair low/high via fill_to
            name_to_series = {s.name: s for s in self.series}
            for s in self.series:
                if s.fill_to and s.fill_to in name_to_series:
                    other = name_to_series[s.fill_to]
                    x = s.x if s.x is not None else list(range(len(s.y)))
                    fig.add_trace(
                        go.Scatter(
                            x=x + list(reversed(x)),
                            y=list(s.y) + list(reversed(other.y)),
                            fill="toself",
                            fillcolor=s.color or "rgba(52,152,219,0.25)",
                            line=dict(color="rgba(0,0,0,0)"),
                            name=s.name,
                            hoverinfo="skip",
                            showlegend=True,
                        )
                    )

        fig.update_layout(
            title=self.title,
            xaxis_title=self.xlabel,
            yaxis_title=self.ylabel,
            width=self.width,
            height=self.height,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig

    def to_svg(self) -> str:
        """Pure-Python SVG renderer (headless-safe)."""
        if self.kind == "heatmap" and self.heatmap is not None:
            return _heatmap_svg(self)
        return _line_svg(self)

    def to_ascii(self, width: int = 60, height: int = 18) -> str:
        """Terminal sparklines / heatmap for CI / demos."""
        if self.kind == "heatmap" and self.heatmap is not None:
            return _heatmap_ascii(self)
        return _line_ascii(self, width=width, height=height)


# ---------------------------------------------------------------------------
# Public figure builders
# ---------------------------------------------------------------------------


_PALETTE = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b")


def trajectory_comparison_figure(
    trajectories: Mapping[str, TrajectoryResult],
    entity_ids: Sequence[str],
    *,
    title: str = "Concentration profiles",
    entity_names: Optional[Mapping[str, str]] = None,
) -> FigureSpec:
    """
    Overlay baseline / disease / treated (or any labelled) trajectories.

    ``trajectories`` maps condition label → :class:`TrajectoryResult`.
    """
    series: List[PlotSeries] = []
    names = entity_names or {}
    ci = 0
    for cond, traj in trajectories.items():
        for eid in entity_ids:
            label = f"{cond}:{names.get(eid, eid[:8])}"
            y = traj.series(eid)
            x = list(traj.times[: len(y)])
            series.append(
                PlotSeries(
                    name=label,
                    x=x,
                    y=y,
                    color=_PALETTE[ci % len(_PALETTE)],
                    style="solid",
                    metadata={"condition": cond, "entity_id": eid},
                )
            )
            ci += 1
    return FigureSpec(
        title=title,
        xlabel="time",
        ylabel="concentration",
        series=series,
        kind="line",
        metadata={"n_conditions": len(trajectories), "entities": list(entity_ids)},
    )


def pk_clearance_figure(
    times: Sequence[float],
    concentrations: Sequence[float],
    *,
    title: str = "Pharmacokinetic clearance C(t)",
    dose_label: str = "C(t)",
    t_start: Optional[float] = None,
    t_end: Optional[float] = None,
) -> FigureSpec:
    """Plot a drug plasma / target-site concentration time course."""
    series = [
        PlotSeries(
            name=dose_label,
            x=list(times),
            y=[float(v) for v in concentrations],
            color="#2980b9",
            style="solid",
        )
    ]
    annotations: List[str] = []
    if t_start is not None:
        annotations.append(f"t_start={t_start:g}")
    if t_end is not None:
        annotations.append(f"t_end={t_end:g}")
    return FigureSpec(
        title=title,
        xlabel="time",
        ylabel="drug concentration",
        series=series,
        kind="line",
        annotations=annotations,
        metadata={"t_start": t_start, "t_end": t_end},
    )


def dose_response_figure(
    curve: DoseResponseCurve,
    *,
    title: Optional[str] = None,
) -> FigureSpec:
    """IC50 / EC50 dose–response with potency annotation."""
    ttl = title or f"Dose–response ({curve.readout_id})"
    series = [
        PlotSeries(
            name="response",
            x=[float(d) for d in curve.doses],
            y=[float(r) for r in curve.responses],
            color="#8e44ad",
            style="solid",
        )
    ]
    annotations: List[str] = [f"mode={curve.mode}", f"baseline={curve.baseline:.3g}"]
    if curve.ic50 is not None:
        annotations.append(f"IC50={curve.ic50:.3g}")
    if curve.ec50 is not None:
        annotations.append(f"EC50={curve.ec50:.3g}")
    if curve.hill_estimate is not None:
        annotations.append(f"Hill≈{curve.hill_estimate:.2f}")
    return FigureSpec(
        title=ttl,
        xlabel="dose",
        ylabel="response",
        series=series,
        kind="scatter",
        annotations=annotations,
        metadata=curve.as_dict(),
    )


def synergy_heatmap_figure(
    matrix: Sequence[Sequence[float]],
    *,
    doses_a: Sequence[float],
    doses_b: Sequence[float],
    title: str = "Bliss / Loewe synergy",
    metric_name: str = "synergy score",
    zmid: float = 0.0,
) -> FigureSpec:
    """
    Heatmap of combination synergy scores.

    Positive values (default mid=0) typically indicate synergy for Bliss excess
    or antagonism for Loewe CI > 1 depending on upstream scaling.
    """
    z = [[float(v) for v in row] for row in matrix]
    return FigureSpec(
        title=title,
        xlabel="dose A",
        ylabel="dose B",
        series=[],
        kind="heatmap",
        heatmap={
            "z": z,
            "x": [float(d) for d in doses_a],
            "y": [float(d) for d in doses_b],
            "colorscale": "RdBu_r",
            "colorbar_title": metric_name,
            "zmid": zmid,
        },
        metadata={"n_a": len(doses_a), "n_b": len(doses_b)},
    )


def ensemble_band_figure(
    ensemble: EnsembleResult,
    entity_ids: Sequence[str],
    *,
    title: str = "Ensemble confidence bands",
    entity_names: Optional[Mapping[str, str]] = None,
) -> FigureSpec:
    """Shaded uncertainty bands from :class:`EnsembleResult`."""
    names = entity_names or {}
    series: List[PlotSeries] = []
    for i, eid in enumerate(entity_ids):
        if eid not in ensemble.bands:
            continue
        band: ConfidenceBand = ensemble.bands[eid]
        color = _PALETTE[i % len(_PALETTE)]
        label = names.get(eid, eid[:8])
        low_name = f"{label} low"
        high_name = f"{label} high"
        series.append(
            PlotSeries(
                name=f"{label} mean",
                x=list(band.times),
                y=list(band.mean),
                color=color,
                style="solid",
                metadata={"entity_id": eid, "level": band.level},
            )
        )
        series.append(
            PlotSeries(
                name=low_name,
                x=list(band.times),
                y=list(band.low),
                color=_rgba(color, 0.25),
                style="band",
                fill_to=high_name,
                metadata={"entity_id": eid},
            )
        )
        series.append(
            PlotSeries(
                name=high_name,
                x=list(band.times),
                y=list(band.high),
                color=_rgba(color, 0.25),
                style="band",
                metadata={"entity_id": eid},
            )
        )
    return FigureSpec(
        title=title,
        xlabel="time",
        ylabel="concentration",
        series=series,
        kind="band",
        annotations=[
            f"members={ensemble.n_success}/{ensemble.n_members}",
        ],
        metadata=ensemble.as_dict().get("metadata", {}),
    )


def hsi_gauge_figure(
    hsi: float,
    *,
    title: str = "Homeostatic Shift Index",
    thresholds: Tuple[float, float] = (0.25, 0.55),
) -> FigureSpec:
    """
    Simple 1-D gauge encoded as a single-point series (SVG draws a bar).

    ``thresholds`` = (warn, critical).
    """
    level = "ok"
    if hsi >= thresholds[1]:
        level = "critical"
    elif hsi >= thresholds[0]:
        level = "warn"
    return FigureSpec(
        title=title,
        xlabel="HSI",
        ylabel="",
        series=[PlotSeries(name="HSI", x=[0.0, 1.0], y=[float(hsi), float(hsi)], color="#e74c3c")],
        kind="line",
        annotations=[f"HSI={hsi:.3f}", f"level={level}"],
        metadata={"hsi": float(hsi), "level": level, "thresholds": list(thresholds)},
        height=120,
    )


# ---------------------------------------------------------------------------
# Colour / SVG helpers
# ---------------------------------------------------------------------------


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return f"rgba(52,152,219,{alpha})"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _line_svg(fig: FigureSpec) -> str:
    w, h = fig.width, fig.height
    ml, mr, mt, mb = 56, 24, 40, 48
    plot_w = max(w - ml - mr, 1)
    plot_h = max(h - mt - mb, 1)

    xs_all: List[float] = []
    ys_all: List[float] = []
    for s in fig.series:
        if s.style == "band":
            continue
        x = s.x if s.x is not None else [float(i) for i in range(len(s.y))]
        xs_all.extend(x)
        ys_all.extend(s.y)
    if not xs_all:
        xs_all, ys_all = [0.0, 1.0], [0.0, 1.0]
    xmin, xmax = min(xs_all), max(xs_all)
    ymin, ymax = min(ys_all), max(ys_all)
    if abs(xmax - xmin) < 1e-12:
        xmax = xmin + 1.0
    if abs(ymax - ymin) < 1e-12:
        ymax = ymin + 1.0

    def sx(x: float) -> float:
        return ml + (x - xmin) / (xmax - xmin) * plot_w

    def sy(y: float) -> float:
        return mt + (1.0 - (y - ymin) / (ymax - ymin)) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{ml}" y="24" font-family="Segoe UI, Arial" font-size="14" fill="#222">'
        f"{html.escape(fig.title)}</text>",
        f'<line x1="{ml}" y1="{mt + plot_h}" x2="{ml + plot_w}" y2="{mt + plot_h}" stroke="#333"/>',
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + plot_h}" stroke="#333"/>',
        f'<text x="{ml + plot_w / 2}" y="{h - 8}" text-anchor="middle" '
        f'font-family="Segoe UI, Arial" font-size="12">{html.escape(fig.xlabel)}</text>',
        f'<text x="14" y="{mt + plot_h / 2}" transform="rotate(-90 14,{mt + plot_h / 2})" '
        f'font-family="Segoe UI, Arial" font-size="12">{html.escape(fig.ylabel)}</text>',
    ]

    # bands first
    name_map = {s.name: s for s in fig.series}
    for s in fig.series:
        if s.fill_to and s.fill_to in name_map:
            other = name_map[s.fill_to]
            x = s.x if s.x is not None else [float(i) for i in range(len(s.y))]
            pts = [(sx(xi), sy(yi)) for xi, yi in zip(x, s.y)]
            pts += [(sx(xi), sy(yi)) for xi, yi in zip(reversed(x), reversed(other.y))]
            poly = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            fill = s.color or "rgba(52,152,219,0.25)"
            parts.append(f'<polygon points="{poly}" fill="{fill}" stroke="none"/>')

    for s in fig.series:
        if s.style == "band" or s.fill_to:
            continue
        x = s.x if s.x is not None else [float(i) for i in range(len(s.y))]
        if len(x) != len(s.y) or not x:
            continue
        d = "M " + " L ".join(f"{sx(xi):.1f} {sy(yi):.1f}" for xi, yi in zip(x, s.y))
        dash = ""
        if s.style == "dash":
            dash = ' stroke-dasharray="6,4"'
        elif s.style == "dot":
            dash = ' stroke-dasharray="2,3"'
        color = s.color or "#1f77b4"
        parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash}/>'
        )

    if fig.annotations:
        note = " | ".join(fig.annotations)
        parts.append(
            f'<text x="{ml}" y="{h - 28}" font-family="Segoe UI, Arial" font-size="11" fill="#555">'
            f"{html.escape(note)}</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _heatmap_svg(fig: FigureSpec) -> str:
    assert fig.heatmap is not None
    z = fig.heatmap["z"]
    rows = len(z)
    cols = len(z[0]) if rows else 0
    w, h = fig.width, fig.height
    ml, mr, mt, mb = 56, 24, 40, 40
    cell_w = max((w - ml - mr) / max(cols, 1), 1)
    cell_h = max((h - mt - mb) / max(rows, 1), 1)
    flat = [v for row in z for v in row] or [0.0]
    zmin, zmax = min(flat), max(flat)
    if abs(zmax - zmin) < 1e-12:
        zmax = zmin + 1.0

    def cell_color(v: float) -> str:
        t = (v - zmin) / (zmax - zmin)
        # blue (low) → white → red (high)
        if t < 0.5:
            u = t / 0.5
            r = int(52 + u * (255 - 52))
            g = int(152 + u * (255 - 152))
            b = int(219 + u * (255 - 219))
        else:
            u = (t - 0.5) / 0.5
            r = int(255 - u * (255 - 192))
            g = int(255 - u * (255 - 57))
            b = int(255 - u * (255 - 43))
        return f"#{r:02x}{g:02x}{b:02x}"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">',
        f'<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{ml}" y="24" font-family="Segoe UI, Arial" font-size="14">'
        f"{html.escape(fig.title)}</text>",
    ]
    for i, row in enumerate(z):
        for j, v in enumerate(row):
            parts.append(
                f'<rect x="{ml + j * cell_w:.1f}" y="{mt + i * cell_h:.1f}" '
                f'width="{cell_w:.1f}" height="{cell_h:.1f}" fill="{cell_color(v)}" '
                f'stroke="#eee" stroke-width="0.5"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def _line_ascii(fig: FigureSpec, *, width: int, height: int) -> str:
    plot_series = [s for s in fig.series if s.style != "band" and not s.fill_to]
    if not plot_series:
        return f"{fig.title}\n(no series)"
    s0 = plot_series[0]
    y = s0.y
    if not y:
        return f"{fig.title}\n(empty)"
    ymin, ymax = min(y), max(y)
    if abs(ymax - ymin) < 1e-12:
        ymax = ymin + 1.0
    grid = [[" "] * width for _ in range(height)]
    for i, val in enumerate(y):
        x = int(i / max(len(y) - 1, 1) * (width - 1))
        row = int((1.0 - (val - ymin) / (ymax - ymin)) * (height - 1))
        grid[row][x] = "*"
    lines = [fig.title, f"y∈[{ymin:.3g},{ymax:.3g}]"]
    lines.extend("".join(r) for r in grid)
    if fig.annotations:
        lines.append(" | ".join(fig.annotations))
    return "\n".join(lines)


def _heatmap_ascii(fig: FigureSpec) -> str:
    assert fig.heatmap is not None
    z = fig.heatmap["z"]
    chars = " .:-=+*#%@"
    flat = [v for row in z for v in row] or [0.0]
    zmin, zmax = min(flat), max(flat)
    span = zmax - zmin or 1.0
    lines = [fig.title]
    for row in z:
        line = "".join(chars[min(len(chars) - 1, int((v - zmin) / span * (len(chars) - 1)))] for v in row)
        lines.append(line)
    return "\n".join(lines)


def is_headless() -> bool:
    """Heuristic: true when no interactive display / Streamlit session is present."""
    import os

    if os.environ.get("CISTRON_HEADLESS", "").lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("CI"):
        return True
    try:
        import streamlit as st  # type: ignore

        return not bool(getattr(st, "runtime", None))
    except ImportError:
        return True
