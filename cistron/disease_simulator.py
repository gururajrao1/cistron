"""
Systemic disease dysregulation controllers for CISTRON Phase 7.

Extends Phase-4 :mod:`cistron.disease_models` with multi-pathway programmes:

* Inflammation / immune signaling — cytokine feed-forward storms, NF-κB
  auto-activation, chronic exhaustion.
* Metabolic disorders — insulin-receptor desensitization and glucose-transport
  kinetic collapse.
* Multi-hit oncogenesis — timed driver cascades that unlock genomic instability
  and secondary pathway hits during solver runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import logging
import math

from cistron.components import KineticParameters, Protein
from cistron.disease_models import (
    CancerSignalingConfig,
    DiseasePhenotype,
    DiseasePhenotypingEngine,
    FeedbackAttenuation,
    PhenotypeKind,
    _resolve_entity_id,
    _resolve_many,
)
from cistron.perturbation import Mutation, MutationKind, Perturbation, PerturbationManager
from cistron.simulation import DualEngineSimulator, PerturbationHook, SimulationState
from cistron.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)


class SystemicDiseaseKind(Enum):
    INFLAMMATION = auto()
    METABOLIC = auto()
    MULTI_HIT_ONCOGENESIS = auto()


# ---------------------------------------------------------------------------
# Shared rate clamp (numerical stability under runaway feedback)
# ---------------------------------------------------------------------------


def _clamp_rate(x: float, *, lo: float = 0.0, hi: float = 1e3) -> float:
    if not math.isfinite(x):
        return lo
    return max(lo, min(hi, x))


def _ensure_protein(
    network: SignalingNetwork,
    name: str,
    *,
    concentration: float = 0.2,
    production: float = 0.05,
    degradation: float = 0.08,
    metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    eid = _resolve_entity_id(network, name)
    if eid is not None:
        return eid
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
        metadata=dict(metadata or {"disease_injected": True}),
    )
    network.add_node(node)
    return node.entity_id


# ---------------------------------------------------------------------------
# Inflammation
# ---------------------------------------------------------------------------


@dataclass
class CytokineStorm(Perturbation):
    """
    Feed-forward cytokine amplification with soft saturation::

        drive(t) = base · (1 + α · Σ cytokine) / (1 + Σ cytokine / K_sat)
        production_i ← production_i0 · drive   (clamped)

    After ``exhaustion_onset``, drive is multiplicatively decayed (immune exhaustion).
    """

    cytokine_ids: List[str] = field(default_factory=list)
    name: str = "cytokine_storm"
    alpha: float = 0.8
    k_sat: float = 3.0
    max_drive: float = 12.0
    exhaustion_onset: float = 40.0
    exhaustion_rate: float = 0.04
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base_prod: Dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.alpha < 0.0 or self.k_sat <= 0.0:
            raise ValueError("alpha ≥ 0 and k_sat > 0 required")
        if self.max_drive < 1.0:
            raise ValueError("max_drive must be ≥ 1")
        if self.exhaustion_rate < 0.0:
            raise ValueError("exhaustion_rate must be non-negative")

    def apply(self, state: SimulationState, t: float) -> None:
        if self.t_end is not None and t > self.t_end + 1e-15:
            return
        if not self.is_active(t):
            return
        if not self._base_prod:
            for cid in self.cytokine_ids:
                ent = state.entity(cid)
                self._base_prod[cid] = max(ent.kinetics.production_rate, 1e-6)

        pool = 0.0
        for cid in self.cytokine_ids:
            pool += max(0.0, state.entity(cid).concentration)
        drive = (1.0 + self.alpha * pool) / (1.0 + pool / self.k_sat)
        drive = _clamp_rate(drive, lo=0.0, hi=self.max_drive)
        if t >= self.exhaustion_onset:
            age = t - self.exhaustion_onset
            drive *= math.exp(-self.exhaustion_rate * age)
            drive = max(0.05, drive)

        for cid in self.cytokine_ids:
            ent = state.entity(cid)
            was = ent.locked
            ent.locked = False
            base = self._base_prod[cid]
            ent.kinetics = ent.kinetics.with_updates(
                production_rate=_clamp_rate(base * drive, hi=base * self.max_drive)
            )
            ent.metadata["cytokine_drive"] = drive
            ent.locked = was
        self.applied = True
        state.extras["cytokine_storm"] = {"drive": drive, "pool": pool}


@dataclass
class NFkBAutoActivation(Perturbation):
    """
    NF-κB positive feedback: activity raises its own production and activates
    downstream cytokine nodes, with a soft ceiling to avoid blow-up.
    """

    nfkb_id: str
    cytokine_ids: List[str] = field(default_factory=list)
    name: str = "nfkb_autoactivation"
    feedback_gain: float = 0.6
    max_scale: float = 8.0
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base: Dict[str, KineticParameters] = field(default_factory=dict, init=False, repr=False)

    def apply(self, state: SimulationState, t: float) -> None:
        if self.t_end is not None and t > self.t_end + 1e-15:
            return
        if not self.is_active(t):
            return
        nfkb = state.entity(self.nfkb_id)
        if self.nfkb_id not in self._base:
            self._base[self.nfkb_id] = nfkb.kinetics
            for cid in self.cytokine_ids:
                self._base[cid] = state.entity(cid).kinetics

        level = max(0.0, nfkb.concentration)
        scale = 1.0 + self.feedback_gain * level / (1.0 + level)
        scale = _clamp_rate(scale, lo=1.0, hi=self.max_scale)

        was = nfkb.locked
        nfkb.locked = False
        b = self._base[self.nfkb_id]
        nfkb.kinetics = b.with_updates(
            production_rate=_clamp_rate(b.production_rate * scale, hi=b.production_rate * self.max_scale),
            basal_activity=min(1.0, b.basal_activity + 0.1 * (scale - 1.0)),
        )
        nfkb.metadata["nfkb_autoscale"] = scale
        nfkb.locked = was

        for cid in self.cytokine_ids:
            ent = state.entity(cid)
            was = ent.locked
            ent.locked = False
            cb = self._base[cid]
            ent.kinetics = cb.with_updates(
                production_rate=_clamp_rate(
                    cb.production_rate * (0.5 + 0.5 * scale),
                    hi=cb.production_rate * self.max_scale,
                )
            )
            ent.locked = was
        self.applied = True


@dataclass
class InflammationConfig:
    cytokines: Sequence[str] = ("TNF", "IL6", "IL1B", "CXCL8")
    nfkb: str = "NFKB1"
    seed_concentration: float = 0.4
    ensure_missing: bool = True
    storm_alpha: float = 0.9
    exhaustion_onset: float = 35.0
    attenuate_resolving_feedback: bool = True
    t_start: float = 0.0


def build_inflammation_phenotype(
    network: SignalingNetwork,
    config: Optional[InflammationConfig] = None,
    *,
    name: str = "inflammation_immune",
) -> DiseasePhenotype:
    cfg = config or InflammationConfig()
    perts: List[Perturbation] = []
    cyto_ids: List[str] = []
    for cname in cfg.cytokines:
        if cfg.ensure_missing:
            eid = _ensure_protein(
                network,
                cname,
                concentration=cfg.seed_concentration,
                production=0.08,
                degradation=0.12,
                metadata={"role": "cytokine", "pathway": "inflammation"},
            )
        else:
            eid = _resolve_entity_id(network, cname)
            if eid is None:
                continue
        cyto_ids.append(eid)

    if cfg.ensure_missing:
        nfkb_id = _ensure_protein(
            network,
            cfg.nfkb,
            concentration=0.3,
            production=0.06,
            degradation=0.07,
            metadata={"role": "transcription_factor", "pathway": "nfkb"},
        )
    else:
        nfkb_id = _resolve_entity_id(network, cfg.nfkb)
        if nfkb_id is None and cyto_ids:
            nfkb_id = cyto_ids[0]

    # Wire NF-κB → cytokines if missing
    if nfkb_id is not None:
        existing = {(e.source_id, e.target_id) for e in network.active_edges()}
        for cid in cyto_ids:
            if (nfkb_id, cid) not in existing:
                network.connect(
                    nfkb_id,
                    cid,
                    InteractionType.ACTIVATION,
                    rate_constant=0.7,
                    metadata={"disease_edge": "nfkb_cytokine"},
                )
            if (cid, nfkb_id) not in existing:
                network.connect(
                    cid,
                    nfkb_id,
                    InteractionType.ACTIVATION,
                    rate_constant=0.35,
                    metadata={"disease_edge": "cytokine_nfkb_ff"},
                )

        perts.append(
            NFkBAutoActivation(
                nfkb_id=nfkb_id,
                cytokine_ids=list(cyto_ids),
                t_start=cfg.t_start,
            )
        )

    if cyto_ids:
        perts.append(
            CytokineStorm(
                cytokine_ids=list(cyto_ids),
                alpha=cfg.storm_alpha,
                exhaustion_onset=cfg.exhaustion_onset,
                t_start=cfg.t_start,
            )
        )

    if cfg.attenuate_resolving_feedback:
        # Soften inhibitory edges that would resolve inflammation
        inhib = {
            e.edge_id
            for e in network.active_edges()
            if e.interaction_type.is_inhibitory
            and (e.source_id in cyto_ids or e.target_id in cyto_ids)
        }
        if inhib:
            perts.append(
                FeedbackAttenuation(
                    edge_ids=inhib,
                    scale=0.15,
                    name="inflammation_resolution_break",
                    t_start=cfg.t_start,
                )
            )

    return DiseasePhenotype(
        name=name,
        kind=PhenotypeKind.CUSTOM,
        perturbations=perts,
        metadata={
            "systemic": SystemicDiseaseKind.INFLAMMATION.name,
            "cytokines": list(cfg.cytokines),
            "nfkb": cfg.nfkb,
        },
        network_tags={"phenotype": "inflammation", "cytokine_ids": cyto_ids},
    )


# ---------------------------------------------------------------------------
# Metabolic / insulin resistance
# ---------------------------------------------------------------------------


@dataclass
class ReceptorDesensitization(Perturbation):
    """
    Progressive insulin-receptor desensitization::

        efficiency(t) = ε0 / (1 + α · max(0, t − onset)^p)
        vmax, binding_affinity ← base · efficiency
    """

    receptor_id: str
    name: str = "receptor_desensitization"
    onset: float = 5.0
    alpha: float = 0.08
    power: float = 1.2
    min_efficiency: float = 0.05
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base: Optional[KineticParameters] = field(default=None, init=False, repr=False)

    def efficiency(self, t: float) -> float:
        age = max(0.0, t - self.onset)
        eff = 1.0 / (1.0 + self.alpha * (age**self.power))
        return max(self.min_efficiency, min(1.0, eff))

    def apply(self, state: SimulationState, t: float) -> None:
        if self.t_end is not None and t > self.t_end + 1e-15:
            return
        if not self.is_active(t):
            return
        ent = state.entity(self.receptor_id)
        if self._base is None:
            self._base = ent.kinetics
        eff = self.efficiency(t)
        was = ent.locked
        ent.locked = False
        ent.kinetics = self._base.with_updates(
            vmax=_clamp_rate(self._base.vmax * eff),
            binding_affinity=_clamp_rate(self._base.binding_affinity * eff),
            basal_activity=self._base.basal_activity * eff,
        )
        ent.metadata["desensitization_efficiency"] = eff
        ent.locked = was
        self.applied = True
        state.extras["desensitization"] = {"receptor": self.receptor_id, "efficiency": eff}


@dataclass
class GlucoseTransportCollapse(Perturbation):
    """
    Downregulate glucose-transport nodes as a function of receptor efficiency
    and substrate (glucose) load — models insulin resistance at GLUT level.
    """

    transporter_ids: List[str]
    receptor_id: str
    glucose_id: Optional[str] = None
    name: str = "glucose_transport_collapse"
    load_sensitivity: float = 0.3
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base: Dict[str, KineticParameters] = field(default_factory=dict, init=False, repr=False)

    def apply(self, state: SimulationState, t: float) -> None:
        if self.t_end is not None and t > self.t_end + 1e-15:
            return
        if not self.is_active(t):
            return
        if not self._base:
            for tid in self.transporter_ids:
                self._base[tid] = state.entity(tid).kinetics

        receptor = state.entity(self.receptor_id)
        eff = float(receptor.metadata.get("desensitization_efficiency", 1.0))
        load = 1.0
        if self.glucose_id is not None:
            g = max(0.0, state.entity(self.glucose_id).concentration)
            load = 1.0 + self.load_sensitivity * g / (1.0 + g)
        scale = _clamp_rate(eff / load, lo=0.02, hi=1.0)

        for tid in self.transporter_ids:
            ent = state.entity(tid)
            was = ent.locked
            ent.locked = False
            b = self._base[tid]
            ent.kinetics = b.with_updates(
                vmax=_clamp_rate(b.vmax * scale),
                production_rate=_clamp_rate(b.production_rate * scale),
            )
            ent.metadata["glut_scale"] = scale
            ent.locked = was
        self.applied = True


@dataclass
class MetabolicConfig:
    insulin: str = "INS"
    insulin_receptor: str = "INSR"
    glucose: str = "GLUCOSE"
    transporters: Sequence[str] = ("GLUT4", "SLC2A4")
    ensure_missing: bool = True
    desense_onset: float = 5.0
    desense_alpha: float = 0.1
    t_start: float = 0.0


def build_metabolic_phenotype(
    network: SignalingNetwork,
    config: Optional[MetabolicConfig] = None,
    *,
    name: str = "insulin_resistance",
) -> DiseasePhenotype:
    cfg = config or MetabolicConfig()
    perts: List[Perturbation] = []

    if cfg.ensure_missing:
        ins_id = _ensure_protein(network, cfg.insulin, concentration=1.0, production=0.1, degradation=0.15,
                                 metadata={"role": "hormone", "pathway": "metabolic"})
        insr_id = _ensure_protein(network, cfg.insulin_receptor, concentration=0.5, production=0.05, degradation=0.05,
                                  metadata={"role": "receptor", "pathway": "metabolic"})
        glut_ids = [
            _ensure_protein(network, g, concentration=0.4, production=0.04, degradation=0.06,
                            metadata={"role": "transporter", "pathway": "metabolic"})
            for g in cfg.transporters
        ]
        gluc_id = _ensure_protein(network, cfg.glucose, concentration=1.2, production=0.02, degradation=0.03,
                                  metadata={"role": "metabolite", "pathway": "metabolic"})
        # INS → INSR → GLUT
        for src, tgt, rate in [
            (ins_id, insr_id, 1.0),
            (insr_id, glut_ids[0], 0.8),
        ]:
            if not any(e.source_id == src and e.target_id == tgt for e in network.active_edges()):
                network.connect(src, tgt, InteractionType.ACTIVATION, rate_constant=rate,
                                metadata={"disease_edge": "insulin_axis"})
        if len(glut_ids) > 1:
            for g in glut_ids[1:]:
                if not any(e.source_id == insr_id and e.target_id == g for e in network.active_edges()):
                    network.connect(insr_id, g, InteractionType.ACTIVATION, rate_constant=0.6,
                                    metadata={"disease_edge": "insulin_axis"})
    else:
        insr_id = _resolve_entity_id(network, cfg.insulin_receptor)
        glut_map = _resolve_many(network, list(cfg.transporters))
        glut_ids = list(glut_map.values())
        gluc_id = _resolve_entity_id(network, cfg.glucose)
        if insr_id is None:
            raise KeyError(f"Insulin receptor {cfg.insulin_receptor!r} not found")

    assert insr_id is not None
    perts.append(
        ReceptorDesensitization(
            receptor_id=insr_id,
            onset=cfg.desense_onset,
            alpha=cfg.desense_alpha,
            t_start=cfg.t_start,
        )
    )
    if glut_ids:
        perts.append(
            GlucoseTransportCollapse(
                transporter_ids=glut_ids,
                receptor_id=insr_id,
                glucose_id=gluc_id,
                t_start=cfg.t_start,
            )
        )
    # Mild constitutive glucose load
    if gluc_id is not None:
        perts.append(
            Mutation(
                target_id=gluc_id,
                kind=MutationKind.OVEREXPRESSION,
                expression_level=1.5,
                rate_scale=1.4,
                name="metabolic_glucose_load",
                t_start=cfg.t_start,
                permanent_lock=False,
            )
        )

    return DiseasePhenotype(
        name=name,
        kind=PhenotypeKind.CUSTOM,
        perturbations=perts,
        metadata={
            "systemic": SystemicDiseaseKind.METABOLIC.name,
            "insulin_receptor": cfg.insulin_receptor,
            "transporters": list(cfg.transporters),
        },
        network_tags={"phenotype": "metabolic", "insr_id": insr_id},
    )


# ---------------------------------------------------------------------------
# Multi-hit oncogenesis
# ---------------------------------------------------------------------------


@dataclass
class TimedMutationHit(Perturbation):
    """Apply an inner Mutation once when ``t >= hit_time`` (genomic instability step)."""

    hit_time: float
    mutation: Mutation
    name: str = ""
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _fired: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"hit@{self.hit_time}:{self.mutation.name}"
        self.mutation.t_start = self.hit_time

    def apply(self, state: SimulationState, t: float) -> None:
        if self._fired:
            self.mutation.apply(state, t)
            self.applied = self.mutation.applied
            return
        if t + 1e-15 >= self.hit_time:
            self.mutation.apply(state, t)
            self._fired = True
            self.applied = True
            state.extras[f"oncogenic_hit:{self.name}"] = {"t": t}


@dataclass
class GenomicInstabilityAccelerator(Perturbation):
    """
    After the primary driver locks in, progressively weaken DNA-maintenance /
    checkpoint nodes (secondary dysregulation proxy).
    """

    driver_id: str
    caretaker_ids: List[str]
    name: str = "genomic_instability"
    onset: float = 15.0
    alpha: float = 0.06
    t_start: float = 0.0
    t_end: Optional[float] = None
    applied: bool = field(default=False, init=False)
    _base: Dict[str, KineticParameters] = field(default_factory=dict, init=False, repr=False)

    def apply(self, state: SimulationState, t: float) -> None:
        if self.t_end is not None and t > self.t_end + 1e-15:
            return
        if not self.is_active(t) or t < self.onset:
            return
        driver = state.entity(self.driver_id)
        if not driver.is_active and driver.concentration < 0.5:
            return
        if not self._base:
            for cid in self.caretaker_ids:
                self._base[cid] = state.entity(cid).kinetics
        age = t - self.onset
        scale = _clamp_rate(1.0 / (1.0 + self.alpha * age), lo=0.05, hi=1.0)
        for cid in self.caretaker_ids:
            ent = state.entity(cid)
            was = ent.locked
            ent.locked = False
            b = self._base[cid]
            ent.kinetics = b.with_updates(
                production_rate=_clamp_rate(b.production_rate * scale),
                vmax=_clamp_rate(b.vmax * scale),
            )
            ent.metadata["caretaker_scale"] = scale
            ent.locked = was
        self.applied = True
        state.extras["genomic_instability"] = {"scale": scale}


@dataclass
class MultiHitOncogenesisConfig:
    primary_drivers: Sequence[str] = ("KRAS", "EGFR", "RAS")
    secondary_hits: Sequence[Tuple[str, float]] = (
        ("TP53", 20.0),
        ("PTEN", 30.0),
    )
    """(gene, hit_time) pairs for sequential LoF."""
    caretakers: Sequence[str] = ("TP53", "ATM", "BRCA1")
    ensure_missing: bool = True
    expression_level: float = 2.5
    instability_onset: float = 15.0
    t_start: float = 0.0


def build_multihit_oncogenesis_phenotype(
    network: SignalingNetwork,
    config: Optional[MultiHitOncogenesisConfig] = None,
    *,
    name: str = "multi_hit_oncogenesis",
) -> DiseasePhenotype:
    cfg = config or MultiHitOncogenesisConfig()
    # Seed cancer constitutive programme on primary drivers
    cancer = DiseasePhenotypingEngine(network).cancer_signaling(
        CancerSignalingConfig(
            oncogenes=cfg.primary_drivers,
            expression_level=cfg.expression_level,
            ensure_missing_survival=cfg.ensure_missing,
            t_start=cfg.t_start,
        ),
        name=f"{name}__core",
    )
    perts: List[Perturbation] = list(cancer.perturbations)

    driver_map = _resolve_many(network, list(cfg.primary_drivers))
    primary_id = next(iter(driver_map.values()), None)

    caretaker_ids: List[str] = []
    for cname in cfg.caretakers:
        if cfg.ensure_missing:
            caretaker_ids.append(
                _ensure_protein(
                    network,
                    cname,
                    concentration=0.5,
                    production=0.05,
                    degradation=0.05,
                    metadata={"role": "caretaker", "pathway": "dna_repair"},
                )
            )
        else:
            eid = _resolve_entity_id(network, cname)
            if eid:
                caretaker_ids.append(eid)

    for gene, hit_t in cfg.secondary_hits:
        if cfg.ensure_missing:
            eid = _ensure_protein(
                network,
                gene,
                concentration=0.5,
                production=0.05,
                degradation=0.05,
                metadata={"role": "tumor_suppressor"},
            )
        else:
            eid = _resolve_entity_id(network, gene)
            if eid is None:
                continue
        perts.append(
            TimedMutationHit(
                hit_time=float(hit_t),
                mutation=Mutation(
                    target_id=eid,
                    kind=MutationKind.KNOCKOUT,
                    name=f"secondary_hit:{gene}",
                    permanent_lock=True,
                ),
            )
        )

    if primary_id and caretaker_ids:
        perts.append(
            GenomicInstabilityAccelerator(
                driver_id=primary_id,
                caretaker_ids=caretaker_ids,
                onset=cfg.instability_onset,
                t_start=cfg.t_start,
            )
        )

    return DiseasePhenotype(
        name=name,
        kind=PhenotypeKind.CANCER_SIGNALING,
        perturbations=perts,
        metadata={
            "systemic": SystemicDiseaseKind.MULTI_HIT_ONCOGENESIS.name,
            "primary_drivers": list(driver_map.keys()),
            "secondary_hits": [list(h) for h in cfg.secondary_hits],
            **cancer.metadata,
        },
        network_tags={
            "phenotype": "multi_hit_oncogenesis",
            **cancer.network_tags,
        },
    )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class DiseaseSimulator:
    """
    Orchestrates systemic disease phenotypes onto a network / DualEngine.
    """

    def __init__(self, network: SignalingNetwork) -> None:
        self.network = network
        self.active_phenotype: Optional[DiseasePhenotype] = None

    def inflammation(self, config: Optional[InflammationConfig] = None) -> DiseasePhenotype:
        self.active_phenotype = build_inflammation_phenotype(self.network, config)
        return self.active_phenotype

    def metabolic(self, config: Optional[MetabolicConfig] = None) -> DiseasePhenotype:
        self.active_phenotype = build_metabolic_phenotype(self.network, config)
        return self.active_phenotype

    def multi_hit_cancer(
        self, config: Optional[MultiHitOncogenesisConfig] = None
    ) -> DiseasePhenotype:
        self.active_phenotype = build_multihit_oncogenesis_phenotype(self.network, config)
        return self.active_phenotype

    def load(self, engine: DualEngineSimulator) -> PerturbationManager:
        if self.active_phenotype is None:
            raise RuntimeError("No active phenotype — call inflammation/metabolic/multi_hit_cancer first")
        return self.active_phenotype.load_into(engine)

    def run(
        self,
        engine: DualEngineSimulator,
        config: Any = None,
    ) -> Any:
        """Load active phenotype hooks and run ODE."""
        from cistron.simulation import SimulationConfig

        self.load(engine)
        cfg = config or SimulationConfig(t_end=50.0, dt=0.1, record_every=10)
        return engine.run_ode(cfg)
