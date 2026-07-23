"""
Omics feature / profile schemas for Phase 2 high-throughput integration.

Maps differential-expression style features onto Hill-cube initial activities
``y₀ ∈ [0.01, 0.99]`` via a scaled logistic of ``log2_fc``.
"""

from __future__ import annotations

import math
import uuid
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Soft bounds so ODE states never sit exactly at 0 or 1.
Y0_MIN = 0.01
Y0_MAX = 0.99


class OmicsFeature(BaseModel):
    """One gene/protein measurement from a differential-omics table."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., min_length=1, description="Gene / protein symbol (uppercase)")
    uniprot_id: Optional[str] = Field(default=None, description="UniProt accession if present")
    ensembl_id: Optional[str] = Field(default=None, description="Ensembl gene ID if present")
    log2_fc: float = Field(..., description="Log2 fold-change vs reference condition")
    p_value: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Raw / adjusted p-value or FDR when available",
    )
    expression_level: Optional[float] = Field(
        default=None,
        description="Absolute abundance (TPM / FPKM / counts) when available",
    )

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol must be non-empty")
        return s

    @field_validator("uniprot_id", "ensembl_id", mode="before")
    @classmethod
    def _empty_id_to_none(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class OmicsProfile(BaseModel):
    """Cohort / sample omics snapshot keyed by gene symbol."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(
        default_factory=lambda: f"omics_{uuid.uuid4().hex[:12]}",
        description="Stable identifier for this uploaded profile",
    )
    sample_name: str = Field(..., min_length=1)
    condition: str = Field(..., min_length=1, description="Biological condition label")
    features: Dict[str, OmicsFeature] = Field(
        default_factory=dict,
        description="Features keyed by uppercase gene symbol",
    )

    @field_validator("sample_name", "condition")
    @classmethod
    def _strip_label(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("label must be non-empty")
        return s

    def map_to_initial_states(
        self,
        network_nodes: List[str],
        baseline_y0: float = 0.5,
        scaling_factor: float = 1.0,
    ) -> Dict[str, float]:
        """
        Map continuous ``log2_fc`` onto bounded ODE baselines ``y₀``.

        For each network node present in this profile::

            y₀ = 1 / (1 + exp(−k · log2_fc))

        where ``k = scaling_factor``. Results are clipped to
        ``[0.01, 0.99]``. Nodes without an omics feature receive
        ``baseline_y0`` (also clipped).

        Parameters
        ----------
        network_nodes:
            Gene symbols in the active signaling network.
        baseline_y0:
            Default activity for unmapped nodes (default ``0.5``).
        scaling_factor:
            Logistic steepness ``k`` (default ``1.0``).

        Returns
        -------
        Dict[str, float]
            ``{symbol: y0}`` for every entry in ``network_nodes``.
        """
        k = float(scaling_factor)
        baseline = _clip_y0(float(baseline_y0))
        out: Dict[str, float] = {}

        for raw in network_nodes:
            symbol = str(raw).strip().upper()
            if not symbol:
                continue
            feat = self.features.get(symbol)
            if feat is None:
                out[symbol] = baseline
                continue
            # y₀ = 1 / (1 + e^{−k · log2_fc})
            y0 = 1.0 / (1.0 + math.exp(-k * float(feat.log2_fc)))
            out[symbol] = _clip_y0(y0)

        return out


def calculate_alignment_score(
    simulated_steady_states: Dict[str, float],
    omics_profile: "OmicsProfile",
    *,
    baseline_y0: float = 0.5,
    scaling_factor: float = 1.0,
) -> Dict[str, float]:
    """
    Score how well simulated terminal activities ``y(t₆₀)`` match omics-mapped ``y₀``.

    Compares only genes present in ``omics_profile.features`` (measured DE targets).
    Returns::

        {
          "mse": float,
          "r2": float,                 # coefficient of determination (may be < 0)
          "alignment_score": float,    # Omics Fit Score in [0, 100] (%)
          "n_compared": float,
        }
    """
    if not omics_profile.features:
        return {"mse": 0.0, "r2": 0.0, "alignment_score": 0.0, "n_compared": 0.0}

    nodes = list(omics_profile.features.keys())
    y0_map = omics_profile.map_to_initial_states(
        nodes,
        baseline_y0=baseline_y0,
        scaling_factor=scaling_factor,
    )

    preds: List[float] = []
    targets: List[float] = []
    for sym in nodes:
        if sym not in simulated_steady_states:
            continue
        preds.append(float(simulated_steady_states[sym]))
        targets.append(float(y0_map.get(sym, baseline_y0)))

    n = len(preds)
    if n == 0:
        return {"mse": 0.0, "r2": 0.0, "alignment_score": 0.0, "n_compared": 0.0}

    mse = sum((p - t) ** 2 for p, t in zip(preds, targets)) / n
    mean_t = sum(targets) / n
    ss_tot = sum((t - mean_t) ** 2 for t in targets)
    ss_res = sum((p - t) ** 2 for p, t in zip(preds, targets))
    if ss_tot < 1e-12:
        r2 = 1.0 if ss_res < 1e-12 else 0.0
    else:
        r2 = 1.0 - (ss_res / ss_tot)

    # Fit %: prefer R² when informative; blend with MSE softness for small n.
    r2_fit = max(0.0, min(1.0, r2)) * 100.0
    mse_fit = max(0.0, min(100.0, 100.0 * math.exp(-mse / 0.08)))
    alignment = 0.7 * r2_fit + 0.3 * mse_fit if n >= 3 else mse_fit

    return {
        "mse": float(mse),
        "r2": float(r2),
        "alignment_score": float(max(0.0, min(100.0, alignment))),
        "n_compared": float(n),
    }


def _clip_y0(y: float) -> float:
    if not math.isfinite(y):
        return 0.5
    return max(Y0_MIN, min(Y0_MAX, float(y)))


__all__ = [
    "Y0_MIN",
    "Y0_MAX",
    "OmicsFeature",
    "OmicsProfile",
    "calculate_alignment_score",
]
