"""
Headless dashboard session engine for VOIDSIGNAL Phase 9.

Runs DualEngineSimulator scenarios (baseline / disease / treated), computes HSI,
toxicology flags, GNN target rationale, and assembles visualisation models —
usable from Streamlit, tests, or CLI without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import copy
import logging
import tempfile

from voidsignal.components import Protein
from voidsignal.disease_models import CancerSignalingConfig, build_cancer_phenotype
from voidsignal.disease_simulator import InflammationConfig, build_inflammation_phenotype
from voidsignal.explainability import AIScientistReasoner
from voidsignal.graph_ml import build_graph_tensors
from voidsignal.pathology_metrics import HomeostaticShiftReport, homeostatic_shift_index
from voidsignal.patient_profile import ExpressionRecord, build_patient_network
from voidsignal.parsers import VCFParser
from voidsignal.pharmacology import DrugAgent, Mechanism, PharmacokineticProfile
from voidsignal.predictive_models import TargetDiscoveryModel
from voidsignal.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from voidsignal.topology import InteractionType, SignalingNetwork
from voidsignal.toxicology import (
    SafetyPathway,
    SafetyTarget,
    SafetyTargetPanel,
    ThresholdDirection,
    ToxicologyMonitor,
)
from voidsignal.visualization.network_view import (
    NetworkViewConfig,
    NetworkViewModel,
    build_network_view,
    render_network_svg,
)
from voidsignal.visualization.plots import (
    FigureSpec,
    hsi_gauge_figure,
    pk_clearance_figure,
    trajectory_comparison_figure,
)

logger = logging.getLogger(__name__)


def build_demo_mapk() -> Tuple[SignalingNetwork, Dict[str, str]]:
    """Canonical MAPK cascade used by the dashboard and Phase-9 tests."""
    net = SignalingNetwork(name="mapk_dashboard")
    ids: Dict[str, str] = {}
    for name, conc in {
        "EGF": 1.0,
        "EGFR": 0.3,
        "RAS": 0.2,
        "RAF": 0.2,
        "MEK": 0.2,
        "ERK": 0.2,
    }.items():
        p = Protein(name=name, concentration=conc)
        if name == "EGF":
            p.set_boolean(True)
            p.kinetics = p.kinetics.with_updates(production_rate=0.05, degradation_rate=0.01)
        net.add_node(p)
        ids[name] = p.entity_id
    for s, t, it, r in [
        ("EGF", "EGFR", InteractionType.ACTIVATION, 1.2),
        ("EGFR", "RAS", InteractionType.ACTIVATION, 1.0),
        ("RAS", "RAF", InteractionType.ACTIVATION, 1.0),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION, 1.0),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION, 1.0),
        ("ERK", "RAF", InteractionType.INHIBITION, 0.5),
    ]:
        net.connect(ids[s], ids[t], it, rate_constant=r)
    return net, ids


@dataclass
class DashboardControls:
    """User-facing control surface (mirrors Streamlit sliders)."""

    dose_c0: float = 2.0
    t_start: float = 5.0
    t_end: float = 35.0
    t_sim: float = 50.0
    dt: float = 0.25
    cancer: bool = False
    cytokine_storm: bool = False
    drug_target: str = "MEK"
    ki: float = 0.5
    kel: float = 0.12
    vcf_path: Optional[str] = None
    expression: Dict[str, float] = field(default_factory=dict)


@dataclass
class DashboardResult:
    """Bundle of artefacts produced by one dashboard tick."""

    controls: DashboardControls
    ids: Dict[str, str]
    baseline: TrajectoryResult
    disease: TrajectoryResult
    treated: TrajectoryResult
    hsi: HomeostaticShiftReport
    network_view: NetworkViewModel
    network_svg: str
    trajectory_figure: FigureSpec
    pk_figure: FigureSpec
    hsi_figure: FigureSpec
    tox_events: List[Dict[str, Any]]
    ai_panel: Dict[str, Any]
    entity_names: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "controls": {
                "dose_c0": self.controls.dose_c0,
                "t_start": self.controls.t_start,
                "t_end": self.controls.t_end,
                "cancer": self.controls.cancer,
                "cytokine_storm": self.controls.cytokine_storm,
                "drug_target": self.controls.drug_target,
            },
            "hsi": self.hsi.as_dict(),
            "tox_events": list(self.tox_events),
            "ai_panel": self.ai_panel,
            "trajectory": self.trajectory_figure.as_dict(),
            "pk": self.pk_figure.as_dict(),
            "network_nodes": len(self.network_view.nodes),
            "metadata": dict(self.metadata),
        }


class DashboardSession:
    """
    Stateless runner: each ``run(controls)`` deep-copies a fresh network so
    repeated slider updates never leak kinetic state.
    """

    def __init__(
        self,
        *,
        network_factory: Optional[Any] = None,
        readout: str = "ERK",
    ) -> None:
        self.network_factory = network_factory or build_demo_mapk
        self.readout = readout

    def _fresh(self) -> Tuple[SignalingNetwork, Dict[str, str]]:
        net, ids = self.network_factory()
        return net, dict(ids)

    def _clone(self, template: SignalingNetwork, ids: Mapping[str, str]) -> SignalingNetwork:
        """Deep-copy so entity / edge ids stay aligned across scenario arms."""
        return copy.deepcopy(template)

    def _apply_disease(
        self,
        net: SignalingNetwork,
        ids: Mapping[str, str],
        controls: DashboardControls,
        engine: DualEngineSimulator,
    ) -> None:
        if controls.cancer:
            pheno = build_cancer_phenotype(
                net,
                CancerSignalingConfig(
                    oncogenes=("RAS", "EGFR"),
                    expression_level=2.5,
                    attenuate_negative_feedback=True,
                    feedback_scale=0.05,
                    survival_nodes=("ERK",),
                    survival_production_boost=1.5,
                ),
            )
            pheno.load_into(engine)
        if controls.cytokine_storm:
            # Re-use inflammation phenotype with EGF as cytokine seed on MAPK demo
            pheno = build_inflammation_phenotype(
                net,
                InflammationConfig(
                    cytokines=("EGF",),
                    nfkb="ERK",
                    seed_concentration=1.5,
                    ensure_missing=False,
                    storm_alpha=1.2,
                    exhaustion_onset=80.0,
                    attenuate_resolving_feedback=True,
                    t_start=0.0,
                ),
            )
            pheno.load_into(engine)
        if controls.vcf_path:
            self._apply_vcf(net, controls, engine)

    def _apply_vcf(
        self,
        net: SignalingNetwork,
        controls: DashboardControls,
        engine: DualEngineSimulator,
    ) -> None:
        path = Path(controls.vcf_path)
        if not path.is_file():
            logger.warning("VCF path not found: %s", path)
            return
        try:
            _header, records = VCFParser(path).parse()
            expr = [
                ExpressionRecord(symbol=g, fold_change=float(fc))
                for g, fc in (controls.expression or {}).items()
            ]
            patient = build_patient_network(
                net,
                patient_id="dashboard",
                variants=records,
                expression=expr or None,
            )
            # Prefer patient-mutated network: swap entity kinetics/conc into live net
            for ent in patient.network.registry.entities():
                if ent.entity_id in net.registry:
                    live = net.registry.get(ent.entity_id)
                    live.set_concentration(ent.concentration)
                    live.kinetics = ent.kinetics
            patient.load_into(engine)
        except Exception as exc:  # noqa: BLE001 — dashboard must not crash on bad VCF
            logger.exception("VCF ingest failed: %s", exc)

    def _make_drug(
        self,
        ids: Mapping[str, str],
        controls: DashboardControls,
    ) -> DrugAgent:
        target_name = controls.drug_target
        target_id = ids.get(target_name)
        if target_id is None:
            # allow raw entity id
            target_id = target_name
        # Prefer outgoing catalytic edges for rate modulation
        edge_ids: List[str] = []
        return DrugAgent(
            target_id=target_id,
            mechanism=Mechanism.COMPETITIVE,
            name=f"dash_drug[{target_name}]",
            ki=controls.ki,
            plateau_concentration=controls.dose_c0,
            t_start=controls.t_start,
            t_end=controls.t_end,
            edge_ids=edge_ids,
            pk=PharmacokineticProfile(
                dose=controls.dose_c0,
                kel=controls.kel,
                dosing_times=[controls.t_start],
                hard_washout=True,
            ),
        )

    def _tox_panel(self, ids: Mapping[str, str]) -> SafetyTargetPanel:
        panel = SafetyTargetPanel()
        if "ERK" in ids:
            panel.add(
                SafetyTarget(
                    entity_id=ids["ERK"],
                    pathway=SafetyPathway.CUSTOM,
                    threshold=4.0,
                    direction=ThresholdDirection.ABOVE,
                    name="ERK",
                )
            )
        if "EGFR" in ids:
            panel.add(
                SafetyTarget(
                    entity_id=ids["EGFR"],
                    pathway=SafetyPathway.CROSSTALK,
                    threshold=3.0,
                    direction=ThresholdDirection.ABOVE,
                    name="EGFR",
                )
            )
        return panel

    def _ai_panel(
        self,
        net: SignalingNetwork,
        ids: Mapping[str, str],
    ) -> Dict[str, Any]:
        try:
            tensors = build_graph_tensors(net)
            model = TargetDiscoveryModel(seed=7, hidden_dim=12, embed_dim=6)
            # Cheap unsupervised ranks for interactive latency
            scores = model.predict(tensors)
            ranks = {s.entity_id: s.score for s in scores}
            reasoner = AIScientistReasoner(model)
            report = reasoner.recommend(tensors, net, top_k=3, include_links=False)
            return {
                "ranks": ranks,
                "recommendations": report.get("recommendations", []),
                "n_nodes": report.get("n_nodes"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI panel failed: %s", exc)
            return {"ranks": {}, "recommendations": [], "error": str(exc)}

    def run(self, controls: Optional[DashboardControls] = None) -> DashboardResult:
        controls = controls or DashboardControls()
        cfg = SimulationConfig(
            t_end=float(controls.t_sim),
            dt=float(controls.dt),
            record_every=max(1, int(round(1.0 / max(controls.dt, 1e-6)))),
        )

        # Shared template → deep copies keep entity ids identical across arms
        template, ids = self._fresh()

        # --- baseline ---
        base_net = self._clone(template, ids)
        baseline = DualEngineSimulator(base_net).run_ode(cfg)

        # --- disease ---
        dis_net = self._clone(template, ids)
        dis_engine = DualEngineSimulator(dis_net)
        self._apply_disease(dis_net, ids, controls, dis_engine)
        disease = dis_engine.run_ode(cfg)

        # --- treated (disease + drug) ---
        rx_net = self._clone(template, ids)
        rx_engine = DualEngineSimulator(rx_net)
        self._apply_disease(rx_net, ids, controls, rx_engine)
        drug = self._make_drug(ids, controls)
        if drug.target_id not in rx_net.registry:
            for name, eid in ids.items():
                if name == controls.drug_target or rx_net.registry.get(eid).name == controls.drug_target:
                    drug.target_id = eid
                    break
        for edge in rx_net.active_edges():
            if edge.source_id == drug.target_id:
                drug.edge_ids.append(edge.edge_id)

        panel = self._tox_panel(ids)
        tox = ToxicologyMonitor(panel, sample_every=1, cooldown=2.0)
        rx_engine.add_hook(drug.apply)
        rx_engine.add_hook(tox.observe)
        treated = rx_engine.run_ode(cfg)

        hsi = homeostatic_shift_index(baseline, treated, rx_net, threshold=0.75)

        entity_names = {eid: rx_net.registry.get(eid).name for eid in ids.values()}
        readout_id = ids.get(self.readout, next(iter(ids.values())))
        track = [ids[n] for n in ("RAS", "MEK", "ERK") if n in ids]
        if readout_id not in track:
            track.append(readout_id)

        traj_fig = trajectory_comparison_figure(
            {"baseline": baseline, "disease": disease, "treated": treated},
            track,
            title="Concentration profiles (baseline / disease / treated)",
            entity_names=entity_names,
        )

        # PK free concentration from the drug schedule
        pk_times = list(treated.times)
        pk_c = [drug.free_concentration(t) for t in pk_times]
        pk_fig = pk_clearance_figure(
            pk_times,
            pk_c,
            title=f"Drug free C(t) — C0={controls.dose_c0:g}",
            t_start=controls.t_start,
            t_end=controls.t_end,
        )
        hsi_fig = hsi_gauge_figure(hsi.hsi)

        ai = self._ai_panel(rx_net, ids)
        view = build_network_view(
            rx_net,
            values=treated.final_concentrations(),
            value_label="treated final [conc]",
            ranks=ai.get("ranks") or None,
            config=NetworkViewConfig(width=720, height=520, iterations=60),
        )
        svg = render_network_svg(view)

        tox_events = [e.as_dict() for e in tox.events]

        return DashboardResult(
            controls=controls,
            ids=dict(ids),
            baseline=baseline,
            disease=disease,
            treated=treated,
            hsi=hsi,
            network_view=view,
            network_svg=svg,
            trajectory_figure=traj_fig,
            pk_figure=pk_fig,
            hsi_figure=hsi_fig,
            tox_events=tox_events,
            ai_panel=ai,
            entity_names=entity_names,
            metadata={
                "readout": self.readout,
                "n_tox": len(tox_events),
                "collapse": hsi.collapse_flag,
            },
        )


def write_demo_vcf(path: Optional[Path] = None) -> Path:
    """Minimal VCF for dashboard upload demos."""
    target = path or Path(tempfile.gettempdir()) / "voidsignal_demo.vcf"
    target.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\trsDEMO\tA\tG\t60\tPASS\tGENE=RAS\n",
        encoding="utf-8",
    )
    return target
