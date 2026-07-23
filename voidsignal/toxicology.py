"""
Toxicology & safety forecasting for VOIDSIGNAL Phase 4.

Monitors pathway-level adverse-event nodes (DNA damage response, necrosis,
stress crosstalk) during drug simulation runs and flags threshold crossings
when intervention doses drive off-target concentrations past critical bounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import logging

from voidsignal.simulation import (
    DualEngineSimulator,
    PerturbationHook,
    SimulationState,
    TrajectoryResult,
)
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)


class SafetyPathway(Enum):
    """Canonical off-target / toxicity pathway categories."""

    DNA_DAMAGE = "dna_damage"
    NECROSIS = "necrosis"
    APOPTOSIS_STRESS = "apoptosis_stress"
    OXIDATIVE_STRESS = "oxidative_stress"
    CROSSTALK = "crosstalk"
    CARDIOTOX = "cardiotox"
    HEPATOTOX = "hepatotox"
    CUSTOM = "custom"


class ThresholdDirection(Enum):
    """Which side of the threshold constitutes a safety breach."""

    ABOVE = auto()
    BELOW = auto()


# Default symbol synonyms used when auto-annotating MAPK / stress networks
DEFAULT_SAFETY_SYMBOLS: Dict[SafetyPathway, Tuple[str, ...]] = {
    SafetyPathway.DNA_DAMAGE: ("TP53", "P53", "ATM", "ATR", "H2AX", "CHEK1", "CHEK2", "GAMMAH2AX"),
    SafetyPathway.NECROSIS: ("MLKL", "RIPK1", "RIPK3", "TNFA", "TNF"),
    SafetyPathway.APOPTOSIS_STRESS: ("BAX", "BAK", "CASP3", "CASP8", "CASP9", "CYCS"),
    SafetyPathway.OXIDATIVE_STRESS: ("NFE2L2", "NRF2", "SOD1", "SOD2", "CAT", "HMOX1"),
    SafetyPathway.CROSSTALK: ("SRC", "STAT3", "NFKB1", "RELA", "MYC"),
    SafetyPathway.CARDIOTOX: ("HERG", "KCNH2", "TNNT2", "MYH6"),
    SafetyPathway.HEPATOTOX: ("ALT", "AST", "CYP3A4", "CYP2E1"),
}


@dataclass(frozen=True)
class SafetyTarget:
    """Single monitored off-target species."""

    entity_id: str
    pathway: SafetyPathway
    threshold: float
    direction: ThresholdDirection = ThresholdDirection.ABOVE
    name: str = ""
    weight: float = 1.0
    """Relative severity weight for aggregate tox scores."""

    def __post_init__(self) -> None:
        if self.threshold < 0.0:
            raise ValueError("threshold must be non-negative")
        if self.weight < 0.0:
            raise ValueError("weight must be non-negative")

    def is_breach(self, concentration: float) -> bool:
        if self.direction is ThresholdDirection.ABOVE:
            return concentration > self.threshold + 1e-15
        return concentration < self.threshold - 1e-15

    def excess(self, concentration: float) -> float:
        """Signed magnitude past the threshold (positive ⇒ breach severity)."""
        if self.direction is ThresholdDirection.ABOVE:
            return max(0.0, concentration - self.threshold)
        return max(0.0, self.threshold - concentration)


@dataclass
class AdverseEvent:
    """One threshold crossing observation."""

    time: float
    entity_id: str
    name: str
    pathway: SafetyPathway
    concentration: float
    threshold: float
    direction: ThresholdDirection
    excess: float
    weight: float
    step_index: int = -1

    def severity(self) -> float:
        return self.weight * self.excess / max(self.threshold, 1e-12)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "time": self.time,
            "entity_id": self.entity_id,
            "name": self.name,
            "pathway": self.pathway.value,
            "concentration": self.concentration,
            "threshold": self.threshold,
            "direction": self.direction.name,
            "excess": self.excess,
            "weight": self.weight,
            "severity": self.severity(),
            "step_index": self.step_index,
        }


@dataclass
class ToxicologyReport:
    """Aggregated safety outlook for a run or post-hoc trajectory audit."""

    events: List[AdverseEvent] = field(default_factory=list)
    max_concentrations: Dict[str, float] = field(default_factory=dict)
    pathway_scores: Dict[str, float] = field(default_factory=dict)
    tox_index: float = 0.0
    breached_targets: List[str] = field(default_factory=list)
    safe: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "tox_index": self.tox_index,
            "breached_targets": list(self.breached_targets),
            "pathway_scores": dict(self.pathway_scores),
            "max_concentrations": dict(self.max_concentrations),
            "n_events": len(self.events),
            "events": [e.as_dict() for e in self.events],
        }


def _resolve_name(network: SignalingNetwork, name_or_id: str) -> Optional[str]:
    if name_or_id in network.registry:
        return name_or_id
    upper = name_or_id.upper()
    for ent in network.registry.entities():
        if ent.name.upper() == upper:
            return ent.entity_id
        if str(ent.metadata.get("gene_symbol", "")).upper() == upper:
            return ent.entity_id
    return None


class SafetyTargetPanel:
    """Collection of safety targets with auto-discovery helpers."""

    def __init__(self, targets: Optional[Sequence[SafetyTarget]] = None) -> None:
        self.targets: List[SafetyTarget] = list(targets or [])

    def add(self, target: SafetyTarget) -> "SafetyTargetPanel":
        self.targets.append(target)
        return self

    def extend(self, targets: Sequence[SafetyTarget]) -> "SafetyTargetPanel":
        self.targets.extend(targets)
        return self

    def by_pathway(self, pathway: SafetyPathway) -> List[SafetyTarget]:
        return [t for t in self.targets if t.pathway is pathway]

    @classmethod
    def from_symbols(
        cls,
        network: SignalingNetwork,
        *,
        thresholds: Optional[Mapping[SafetyPathway, float]] = None,
        default_threshold: float = 1.5,
        pathways: Optional[Sequence[SafetyPathway]] = None,
        symbol_map: Optional[Mapping[SafetyPathway, Sequence[str]]] = None,
    ) -> "SafetyTargetPanel":
        """
        Bind default stress / DDR symbols present in ``network`` to thresholds.
        """
        thr = dict(thresholds or {})
        sym = dict(symbol_map or DEFAULT_SAFETY_SYMBOLS)
        wanted = list(pathways) if pathways is not None else list(DEFAULT_SAFETY_SYMBOLS.keys())
        panel = cls()
        for pathway in wanted:
            cutoff = thr.get(pathway, default_threshold)
            for symbol in sym.get(pathway, ()):
                eid = _resolve_name(network, symbol)
                if eid is None:
                    continue
                ent = network.registry.get(eid)
                panel.add(
                    SafetyTarget(
                        entity_id=eid,
                        pathway=pathway,
                        threshold=cutoff,
                        name=ent.name or symbol,
                    )
                )
        return panel

    @classmethod
    def core_array(
        cls,
        network: SignalingNetwork,
        *,
        dna_threshold: float = 1.2,
        necrosis_threshold: float = 1.5,
        crosstalk_threshold: float = 2.0,
    ) -> "SafetyTargetPanel":
        """Compact panel covering DDR, necrosis, and crosstalk interference."""
        return cls.from_symbols(
            network,
            pathways=(
                SafetyPathway.DNA_DAMAGE,
                SafetyPathway.NECROSIS,
                SafetyPathway.CROSSTALK,
                SafetyPathway.APOPTOSIS_STRESS,
            ),
            thresholds={
                SafetyPathway.DNA_DAMAGE: dna_threshold,
                SafetyPathway.NECROSIS: necrosis_threshold,
                SafetyPathway.CROSSTALK: crosstalk_threshold,
                SafetyPathway.APOPTOSIS_STRESS: dna_threshold,
            },
        )


class ToxicologyMonitor:
    """
    Live hook + offline trajectory auditor for safety boundary crossings.
    """

    def __init__(
        self,
        panel: SafetyTargetPanel,
        *,
        sample_every: int = 1,
        cooldown: float = 0.0,
    ) -> None:
        if sample_every < 1:
            raise ValueError("sample_every must be ≥ 1")
        if cooldown < 0.0:
            raise ValueError("cooldown must be non-negative")
        self.panel = panel
        self.sample_every = sample_every
        self.cooldown = cooldown
        self.events: List[AdverseEvent] = []
        self._last_fire: Dict[str, float] = {}
        self._max_seen: Dict[str, float] = {}

    def reset(self) -> None:
        self.events.clear()
        self._last_fire.clear()
        self._max_seen.clear()

    def _record(
        self,
        target: SafetyTarget,
        concentration: float,
        t: float,
        step_index: int,
    ) -> None:
        if not target.is_breach(concentration):
            return
        last = self._last_fire.get(target.entity_id)
        if last is not None and (t - last) < self.cooldown:
            return
        event = AdverseEvent(
            time=t,
            entity_id=target.entity_id,
            name=target.name or target.entity_id,
            pathway=target.pathway,
            concentration=concentration,
            threshold=target.threshold,
            direction=target.direction,
            excess=target.excess(concentration),
            weight=target.weight,
            step_index=step_index,
        )
        self.events.append(event)
        self._last_fire[target.entity_id] = t
        logger.warning(
            "Toxicity flag %s %s=%.4f threshold=%.4f at t=%.3f",
            target.pathway.value,
            target.name or target.entity_id,
            concentration,
            target.threshold,
            t,
        )

    def observe(self, state: SimulationState, t: float) -> None:
        if state.step_index % self.sample_every != 0:
            return
        flags: List[Dict[str, Any]] = []
        for target in self.panel.targets:
            if target.entity_id not in state.network.registry:
                continue
            conc = max(0.0, state.entity(target.entity_id).concentration)
            prev = self._max_seen.get(target.entity_id, 0.0)
            if conc > prev:
                self._max_seen[target.entity_id] = conc
            before = len(self.events)
            self._record(target, conc, t, state.step_index)
            if len(self.events) > before:
                flags.append(self.events[-1].as_dict())
        if flags:
            state.extras["toxicology_flags"] = flags

    def as_hook(self) -> PerturbationHook:
        def hook(state: SimulationState, t: float) -> None:
            self.observe(state, t)

        return hook

    def attach(self, engine: DualEngineSimulator) -> PerturbationHook:
        hook = self.as_hook()
        engine.add_hook(hook)
        return hook

    def evaluate_trajectory(self, trajectory: TrajectoryResult) -> ToxicologyReport:
        """Offline scan of a completed trajectory (does not mutate ``events``)."""
        events: List[AdverseEvent] = []
        maxima: Dict[str, float] = {}
        for t, sample in zip(trajectory.times, trajectory.concentrations):
            for target in self.panel.targets:
                if target.entity_id not in sample:
                    continue
                conc = max(0.0, float(sample[target.entity_id]))
                maxima[target.entity_id] = max(maxima.get(target.entity_id, 0.0), conc)
                if target.is_breach(conc):
                    events.append(
                        AdverseEvent(
                            time=t,
                            entity_id=target.entity_id,
                            name=target.name or target.entity_id,
                            pathway=target.pathway,
                            concentration=conc,
                            threshold=target.threshold,
                            direction=target.direction,
                            excess=target.excess(conc),
                            weight=target.weight,
                        )
                    )
        return self._finalize(events, maxima)

    def report(self) -> ToxicologyReport:
        """Summarise events collected by the live hook."""
        return self._finalize(list(self.events), dict(self._max_seen))

    def _finalize(
        self,
        events: List[AdverseEvent],
        maxima: Mapping[str, float],
    ) -> ToxicologyReport:
        pathway_scores: Dict[str, float] = {}
        breached: Set[str] = set()
        for ev in events:
            key = ev.pathway.value
            pathway_scores[key] = pathway_scores.get(key, 0.0) + ev.severity()
            breached.add(ev.entity_id)
        tox_index = sum(pathway_scores.values())
        return ToxicologyReport(
            events=events,
            max_concentrations=dict(maxima),
            pathway_scores=pathway_scores,
            tox_index=tox_index,
            breached_targets=sorted(breached),
            safe=len(breached) == 0,
        )


class ToxicologyForecaster:
    """
    Convenience façade: build a core panel, attach monitor, score dose risk.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        panel: Optional[SafetyTargetPanel] = None,
        cooldown: float = 1.0,
    ) -> None:
        self.network = network
        self.panel = panel or SafetyTargetPanel.core_array(network)
        self.monitor = ToxicologyMonitor(self.panel, cooldown=cooldown)

    def load_into(self, engine: DualEngineSimulator) -> ToxicologyMonitor:
        self.monitor.reset()
        self.monitor.attach(engine)
        return self.monitor

    def add_target(
        self,
        name_or_id: str,
        *,
        pathway: SafetyPathway = SafetyPathway.CUSTOM,
        threshold: float,
        direction: ThresholdDirection = ThresholdDirection.ABOVE,
        weight: float = 1.0,
    ) -> SafetyTarget:
        eid = _resolve_name(self.network, name_or_id)
        if eid is None:
            raise KeyError(f"Safety target {name_or_id!r} not found")
        ent = self.network.registry.get(eid)
        target = SafetyTarget(
            entity_id=eid,
            pathway=pathway,
            threshold=threshold,
            direction=direction,
            name=ent.name,
            weight=weight,
        )
        self.panel.add(target)
        return target

    def risk_index(self, trajectory: TrajectoryResult) -> float:
        return self.monitor.evaluate_trajectory(trajectory).tox_index
