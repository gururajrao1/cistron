"""
Immune checkpoint signaling — PD-1/PD-L1, CTLA-4, LAG-3 engagement & T-cell exhaustion.

Computes dynamic exhaustion coefficients ε and couples immune suppression into
tumor / target apoptosis (degradation) rates for MassActionRHS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import math

from voidsignal.components import KineticParameters, Protein
from voidsignal.perturbation import Perturbation
from voidsignal.simulation import SimulationState
from voidsignal.topology import InteractionType, SignalingNetwork


class CheckpointAxis(str, Enum):
    PD1_PDL1 = "PD1_PDL1"
    CTLA4_B7 = "CTLA4_B7"
    LAG3_MHCII = "LAG3_MHCII"


@dataclass(frozen=True)
class CheckpointEngagement:
    """Steady / instantaneous receptor–ligand occupancy for one axis."""

    axis: CheckpointAxis
    receptor: str
    ligand: str
    occupancy: float
    """Fraction of receptors engaged ∈ [0, 1]."""
    kd_nM: float
    ki_signal: float
    """Downstream signaling suppression factor ∈ (0, 1]."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.occupancy <= 1.0:
            raise ValueError("occupancy must be in [0, 1]")


@dataclass
class CheckpointState:
    """Aggregate checkpoint pressure and exhaustion coefficient."""

    engagements: List[CheckpointEngagement] = field(default_factory=list)
    epsilon_exhaustion: float = 0.0
    """ε_exhaustion ∈ [0, 1]; 0 = fully competent CTL, 1 = fully exhausted."""
    apoptosis_scale: float = 1.0
    """Multiplier on tumor / target degradation (apoptosis proxy)."""
    ctl_activity_scale: float = 1.0
    """Multiplier on CTL effector production / vmax."""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "epsilon_exhaustion": self.epsilon_exhaustion,
            "apoptosis_scale": self.apoptosis_scale,
            "ctl_activity_scale": self.ctl_activity_scale,
            "engagements": [
                {
                    "axis": e.axis.value,
                    "receptor": e.receptor,
                    "ligand": e.ligand,
                    "occupancy": e.occupancy,
                    "kd_nM": e.kd_nM,
                    "ki_signal": e.ki_signal,
                }
                for e in self.engagements
            ],
        }


def ligand_receptor_occupancy(
    receptor_conc: float,
    ligand_conc: float,
    *,
    kd: float,
    n_hill: float = 1.0,
) -> float:
    """
    Fractional occupancy via Hill–Langmuir::

        θ = L^n / (K_d^n + L^n)   (receptor saturating form)
    """
    L = max(0.0, float(ligand_conc))
    R = max(0.0, float(receptor_conc))
    kd = max(1e-12, float(kd))
    n = max(0.1, float(n_hill))
    # Effective ligand boosted mildly by receptor presence
    Leff = L * (1.0 + 0.15 * math.tanh(R))
    return Leff**n / (kd**n + Leff**n)


def compute_exhaustion(
    engagements: Sequence[CheckpointEngagement],
    *,
    weights: Optional[Mapping[CheckpointAxis, float]] = None,
    neoantigen_burden: float = 0.0,
) -> CheckpointState:
    """
    Map checkpoint occupancies → ε_exhaustion and kinetic scales.

    High PD-1 / CTLA-4 / LAG-3 engagement raises exhaustion and suppresses CTL
    activity; tumor apoptosis scale falls as CTLs exhaust (immune evasion).
    Neoantigen burden partially offsets exhaustion (antigen-driven priming).
    """
    w = {
        CheckpointAxis.PD1_PDL1: 1.0,
        CheckpointAxis.CTLA4_B7: 0.85,
        CheckpointAxis.LAG3_MHCII: 0.7,
    }
    if weights:
        w.update(weights)

    pressure = 0.0
    wsum = 0.0
    for e in engagements:
        ww = w.get(e.axis, 0.5)
        pressure += ww * e.occupancy * (2.0 - e.ki_signal)
        wsum += ww
    if wsum > 0:
        pressure /= wsum

    # Antigen offset (0–1 burden → reduce exhaustion up to 35%)
    burden = max(0.0, min(1.0, float(neoantigen_burden)))
    eps = max(0.0, min(1.0, pressure * (1.0 - 0.35 * burden)))

    ctl_scale = max(0.05, 1.0 - 0.85 * eps)
    # Tumor apoptosis from CTL killing: high when CTLs competent
    apoptosis = max(0.15, 0.25 + 0.9 * ctl_scale * (0.4 + 0.6 * burden))

    return CheckpointState(
        engagements=list(engagements),
        epsilon_exhaustion=eps,
        apoptosis_scale=apoptosis,
        ctl_activity_scale=ctl_scale,
    )


@dataclass
class CheckpointConfig:
    """Concentrations / K_d for checkpoint axes (model-relative or nM-scaled)."""

    pd1: float = 1.0
    pdl1: float = 1.2
    kd_pd1: float = 0.8
    ctla4: float = 0.7
    b7: float = 1.0
    kd_ctla4: float = 1.0
    lag3: float = 0.5
    mhc_ii: float = 0.9
    kd_lag3: float = 1.1
    neoantigen_burden: float = 0.0
    """Normalized 0–1 antigenic burden from neoantigen panel."""
    blockade_pd1: float = 0.0
    """0–1 therapeutic PD-1 blockade (reduces effective occupancy)."""
    blockade_ctla4: float = 0.0
    blockade_lag3: float = 0.0


def evaluate_checkpoints(config: CheckpointConfig) -> CheckpointState:
    """Compute engagement + exhaustion from a static checkpoint config."""
    engagements = [
        CheckpointEngagement(
            axis=CheckpointAxis.PD1_PDL1,
            receptor="PD1",
            ligand="PDL1",
            occupancy=max(
                0.0,
                ligand_receptor_occupancy(config.pd1, config.pdl1, kd=config.kd_pd1)
                * (1.0 - max(0.0, min(1.0, config.blockade_pd1))),
            ),
            kd_nM=config.kd_pd1 * 100.0,
            ki_signal=max(0.1, 1.0 - 0.7 * config.blockade_pd1),
        ),
        CheckpointEngagement(
            axis=CheckpointAxis.CTLA4_B7,
            receptor="CTLA4",
            ligand="B7",
            occupancy=max(
                0.0,
                ligand_receptor_occupancy(config.ctla4, config.b7, kd=config.kd_ctla4)
                * (1.0 - max(0.0, min(1.0, config.blockade_ctla4))),
            ),
            kd_nM=config.kd_ctla4 * 100.0,
            ki_signal=max(0.1, 1.0 - 0.65 * config.blockade_ctla4),
        ),
        CheckpointEngagement(
            axis=CheckpointAxis.LAG3_MHCII,
            receptor="LAG3",
            ligand="MHCII",
            occupancy=max(
                0.0,
                ligand_receptor_occupancy(config.lag3, config.mhc_ii, kd=config.kd_lag3)
                * (1.0 - max(0.0, min(1.0, config.blockade_lag3))),
            ),
            kd_nM=config.kd_lag3 * 100.0,
            ki_signal=max(0.1, 1.0 - 0.6 * config.blockade_lag3),
        ),
    ]
    return compute_exhaustion(engagements, neoantigen_burden=config.neoantigen_burden)


def _ensure_node(
    network: SignalingNetwork,
    name: str,
    *,
    concentration: float,
    production: float = 0.04,
    degradation: float = 0.06,
) -> str:
    for ent in network.registry.entities():
        if ent.name.upper() == name.upper():
            return ent.entity_id
    node = Protein(
        name=name,
        concentration=concentration,
        kinetics=KineticParameters(
            production_rate=production,
            degradation_rate=degradation,
            basal_activity=0.05,
            vmax=1.0,
            km=1.0,
        ),
        metadata={"immuno_injected": True},
    )
    network.add_node(node)
    return node.entity_id


def inject_checkpoint_nodes(
    network: SignalingNetwork,
    config: Optional[CheckpointConfig] = None,
) -> Dict[str, str]:
    """Ensure PD-1/PD-L1/CTLA-4/LAG-3 nodes exist; return name→entity_id map."""
    cfg = config or CheckpointConfig()
    ids = {
        "PD1": _ensure_node(network, "PD1", concentration=cfg.pd1),
        "PDL1": _ensure_node(network, "PDL1", concentration=cfg.pdl1, production=0.06),
        "CTLA4": _ensure_node(network, "CTLA4", concentration=cfg.ctla4),
        "B7": _ensure_node(network, "B7", concentration=cfg.b7),
        "LAG3": _ensure_node(network, "LAG3", concentration=cfg.lag3),
        "MHCII": _ensure_node(network, "MHCII", concentration=cfg.mhc_ii),
        "CTL": _ensure_node(network, "CTL", concentration=0.8, production=0.05),
        "TUMOR": _ensure_node(network, "TUMOR", concentration=1.2, production=0.08, degradation=0.04),
    }
    # Wire suppression edges if missing
    def _maybe_connect(src: str, tgt: str, kind: InteractionType, rate: float) -> None:
        s, t = ids[src], ids[tgt]
        for e in network.out_edges(s):
            if e.target_id == t:
                return
        network.connect(s, t, kind, rate_constant=rate)

    _maybe_connect("PDL1", "PD1", InteractionType.INHIBITION, 0.9)
    _maybe_connect("B7", "CTLA4", InteractionType.INHIBITION, 0.7)
    _maybe_connect("MHCII", "LAG3", InteractionType.INHIBITION, 0.6)
    _maybe_connect("PD1", "CTL", InteractionType.INHIBITION, 0.8)
    _maybe_connect("CTLA4", "CTL", InteractionType.INHIBITION, 0.7)
    _maybe_connect("CTL", "TUMOR", InteractionType.INHIBITION, 1.0)
    return ids


@dataclass
class CheckpointPerturbation(Perturbation):
    """
    Mid-simulation checkpoint → exhaustion → apoptosis coupling.

    Each step:
    * Reads live PD-1/PD-L1/… concentrations when nodes exist
    * Updates ε_exhaustion
    * Scales CTL vmax/production and TUMOR (or ``tumor_ids``) degradation
    """

    network: SignalingNetwork = field(repr=False)
    config: CheckpointConfig = field(default_factory=CheckpointConfig)
    tumor_ids: List[str] = field(default_factory=list)
    ctl_id: Optional[str] = None
    node_ids: Dict[str, str] = field(default_factory=dict)
    name: str = "checkpoint_exhaustion"
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base_tumor: Dict[str, KineticParameters] = field(default_factory=dict, init=False, repr=False)
    _base_ctl: Optional[KineticParameters] = field(default=None, init=False, repr=False)
    _last_state: Optional[CheckpointState] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.node_ids:
            self.node_ids = inject_checkpoint_nodes(self.network, self.config)
        if not self.tumor_ids:
            self.tumor_ids = [self.node_ids["TUMOR"]]
        if self.ctl_id is None:
            self.ctl_id = self.node_ids["CTL"]

    @property
    def last_state(self) -> Optional[CheckpointState]:
        return self._last_state

    def apply(self, state: SimulationState, t: float) -> None:
        if t < self.t_start:
            return
        if self.t_end is not None and t > self.t_end:
            self._restore()
            return

        cfg = self.config
        # Live concentrations when available
        def _c(name: str, fallback: float) -> float:
            eid = self.node_ids.get(name)
            if eid is None:
                return fallback
            try:
                return max(0.0, float(self.network.registry.get(eid).concentration))
            except Exception:
                return fallback

        live = CheckpointConfig(
            pd1=_c("PD1", cfg.pd1),
            pdl1=_c("PDL1", cfg.pdl1),
            kd_pd1=cfg.kd_pd1,
            ctla4=_c("CTLA4", cfg.ctla4),
            b7=_c("B7", cfg.b7),
            kd_ctla4=cfg.kd_ctla4,
            lag3=_c("LAG3", cfg.lag3),
            mhc_ii=_c("MHCII", cfg.mhc_ii),
            kd_lag3=cfg.kd_lag3,
            neoantigen_burden=cfg.neoantigen_burden,
            blockade_pd1=cfg.blockade_pd1,
            blockade_ctla4=cfg.blockade_ctla4,
            blockade_lag3=cfg.blockade_lag3,
        )
        ck = evaluate_checkpoints(live)
        self._last_state = ck
        self.applied = True

        # Cache bases once
        if self.ctl_id and self._base_ctl is None:
            self._base_ctl = self.network.registry.get(self.ctl_id).kinetics
        for tid in self.tumor_ids:
            if tid not in self._base_tumor:
                self._base_tumor[tid] = self.network.registry.get(tid).kinetics

        if self.ctl_id and self._base_ctl is not None:
            ctl = self.network.registry.get(self.ctl_id)
            b = self._base_ctl
            ctl.kinetics = b.with_updates(
                vmax=max(0.0, b.vmax * ck.ctl_activity_scale),
                production_rate=max(0.0, b.production_rate * ck.ctl_activity_scale),
            )
            ctl.metadata["epsilon_exhaustion"] = ck.epsilon_exhaustion

        for tid in self.tumor_ids:
            tumor = self.network.registry.get(tid)
            b = self._base_tumor[tid]
            tumor.kinetics = b.with_updates(
                degradation_rate=max(1e-6, b.degradation_rate * ck.apoptosis_scale),
            )
            tumor.metadata["apoptosis_scale"] = ck.apoptosis_scale
            tumor.metadata["epsilon_exhaustion"] = ck.epsilon_exhaustion

    def _restore(self) -> None:
        if self.ctl_id and self._base_ctl is not None:
            self.network.registry.get(self.ctl_id).kinetics = self._base_ctl
        for tid, base in self._base_tumor.items():
            self.network.registry.get(tid).kinetics = base


def make_demo_checkpoint_config(*, with_blockade: bool = False) -> CheckpointConfig:
    return CheckpointConfig(
        pd1=1.1,
        pdl1=1.4,
        ctla4=0.8,
        b7=1.0,
        lag3=0.6,
        mhc_ii=0.9,
        neoantigen_burden=0.55,
        blockade_pd1=0.75 if with_blockade else 0.0,
        blockade_ctla4=0.4 if with_blockade else 0.0,
    )
