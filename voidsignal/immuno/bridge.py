"""
Immunoinformatics → PatientSignalingNetwork / MassActionRHS bridge (Phase 13).

Neoantigen burden → checkpoint exhaustion → TME population kinetics, with
optional DiseaseSimulator-compatible perturbation hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
import copy
import logging

from voidsignal.immuno.checkpoints import (
    CheckpointConfig,
    CheckpointPerturbation,
    CheckpointState,
    evaluate_checkpoints,
    inject_checkpoint_nodes,
    make_demo_checkpoint_config,
)
from voidsignal.immuno.neoantigens import (
    CodingMutation,
    NeoantigenPanel,
    NeoantigenPredictor,
    PatientHLAProfile,
    make_demo_hla_profile,
    make_demo_mutations,
)
from voidsignal.immuno.tme_kinetics import (
    TMEParameters,
    TMEPerturbation,
    TMESimulator,
    TMEState,
    TMETrajectory,
    inject_tme_nodes,
    make_demo_tme_params,
)
from voidsignal.patient_profile import PatientSignalingNetwork
from voidsignal.perturbation import PerturbationManager
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)

NetworkLike = Union[SignalingNetwork, PatientSignalingNetwork]


@dataclass
class ImmunoOncologyProfile:
    """Unified immuno-oncology patient bundle."""

    patient_id: str = "immuno"
    hla: Optional[PatientHLAProfile] = None
    mutations: List[CodingMutation] = field(default_factory=list)
    checkpoint: CheckpointConfig = field(default_factory=CheckpointConfig)
    tme: TMEParameters = field(default_factory=TMEParameters)
    tme_initial: TMEState = field(default_factory=TMEState)
    protein_sequences: Dict[str, str] = field(default_factory=dict)
    apply_checkpoint_blockade: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImmunoBridgeResult:
    """Outputs from applying the immuno-oncology stack."""

    patient_id: str
    network: SignalingNetwork
    patient: Optional[PatientSignalingNetwork]
    neoantigens: NeoantigenPanel
    checkpoint: CheckpointState
    tme_trajectory: Optional[TMETrajectory]
    checkpoint_hook: Optional[CheckpointPerturbation]
    tme_hook: Optional[TMEPerturbation]
    node_ids: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def load_into(self, engine: Any) -> PerturbationManager:
        """Attach checkpoint + TME hooks to a DualEngineSimulator."""
        mgr = PerturbationManager()
        if self.checkpoint_hook is not None:
            mgr.add(self.checkpoint_hook)
        if self.tme_hook is not None:
            mgr.add(self.tme_hook)
        for hook in mgr.hooks():
            engine.add_hook(hook)
        return mgr

    def as_dict(self) -> Dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "n_neoantigens": len(self.neoantigens.candidates),
            "n_strong": len(self.neoantigens.strong_binders()),
            "top_neoantigens": [
                {
                    "gene": c.gene,
                    "peptide": c.mutant_peptide,
                    "allele": c.best.allele,
                    "ic50_nM": c.ic50_nM,
                    "immunogenicity": c.immunogenicity,
                }
                for c in self.neoantigens.top(5)
            ],
            "checkpoint": self.checkpoint.as_dict(),
            "tme_final": None if self.tme_trajectory is None else self.tme_trajectory.final().as_dict(),
            "node_ids": dict(self.node_ids),
            "metadata": dict(self.metadata),
        }


def neoantigen_burden_score(panel: NeoantigenPanel) -> float:
    """Normalize neoantigen load to [0, 1] antigenic burden."""
    if not panel.candidates:
        return 0.0
    strong = len(panel.strong_binders())
    immuno = sum(c.immunogenicity for c in panel.candidates) / len(panel.candidates)
    # 5+ strong binders → saturate burden
    return max(0.0, min(1.0, 0.55 * min(1.0, strong / 5.0) + 0.45 * immuno))


def _unwrap(target: NetworkLike) -> tuple[SignalingNetwork, Optional[PatientSignalingNetwork]]:
    if isinstance(target, PatientSignalingNetwork):
        return target.network, target
    return target, None


class ImmunoOncologyBridge:
    """
    Orchestrate neoantigen prediction, checkpoint exhaustion, and TME kinetics.

    1. Predict neoantigens from coding mutations × HLA
    2. Set checkpoint ``neoantigen_burden`` and evaluate ε_exhaustion
    3. Inject checkpoint + TME nodes; build mid-sim perturbation hooks
    4. Optionally pre-simulate TME trajectory for reporting
    """

    def __init__(
        self,
        *,
        predictor: Optional[NeoantigenPredictor] = None,
        clone: bool = False,
        presimulate_tme: bool = True,
        tme_t_end: float = 30.0,
    ) -> None:
        self.predictor = predictor or NeoantigenPredictor()
        self.clone = clone
        self.presimulate_tme = presimulate_tme
        self.tme_t_end = tme_t_end

    def apply(
        self,
        target: NetworkLike,
        profile: ImmunoOncologyProfile,
    ) -> ImmunoBridgeResult:
        network, patient = _unwrap(target)
        if self.clone:
            network = copy.deepcopy(network)
            if patient is not None:
                patient = copy.deepcopy(patient)
                patient.network = network

        hla = profile.hla or make_demo_hla_profile(profile.patient_id)
        mutations = list(profile.mutations) or make_demo_mutations()
        panel = self.predictor.predict_panel(
            mutations, hla, sequences=profile.protein_sequences
        )
        burden = neoantigen_burden_score(panel)

        ck_cfg = CheckpointConfig(**{**profile.checkpoint.__dict__})
        ck_cfg.neoantigen_burden = burden
        if profile.apply_checkpoint_blockade:
            ck_cfg.blockade_pd1 = max(ck_cfg.blockade_pd1, 0.7)
            ck_cfg.blockade_ctla4 = max(ck_cfg.blockade_ctla4, 0.35)
        ck_state = evaluate_checkpoints(ck_cfg)

        ck_ids = inject_checkpoint_nodes(network, ck_cfg)
        tme_params = TMEParameters(**{**profile.tme.__dict__})
        tme_params.epsilon_exhaustion = ck_state.epsilon_exhaustion
        tme_params.antigen_drive = max(tme_params.antigen_drive, 0.3 + 0.7 * burden)
        tme_ids = inject_tme_nodes(network, profile.tme_initial)
        node_ids = {**ck_ids, **tme_ids}

        ck_hook = CheckpointPerturbation(
            network=network,
            config=ck_cfg,
            tumor_ids=[node_ids["TUMOR"]],
            ctl_id=node_ids["CTL"],
            node_ids=ck_ids,
        )
        tme_hook = TMEPerturbation(
            network=network,
            params=tme_params,
            initial=profile.tme_initial,
            node_ids=tme_ids,
            checkpoint_config=ck_cfg,
        )

        traj = None
        if self.presimulate_tme:
            traj = TMESimulator(tme_params).run(
                profile.tme_initial,
                t_end=self.tme_t_end,
                checkpoint=ck_state,
                antigen_drive=tme_params.antigen_drive,
            )

        if patient is not None:
            patient.metadata = dict(patient.metadata)
            patient.metadata["immuno"] = {
                "n_neoantigens": len(panel.candidates),
                "burden": burden,
                "epsilon_exhaustion": ck_state.epsilon_exhaustion,
            }

        logger.info(
            "Immuno bridge: %d neoantigens (burden=%.3f) ε=%.3f",
            len(panel.candidates),
            burden,
            ck_state.epsilon_exhaustion,
        )

        return ImmunoBridgeResult(
            patient_id=profile.patient_id,
            network=network,
            patient=patient,
            neoantigens=panel,
            checkpoint=ck_state,
            tme_trajectory=traj,
            checkpoint_hook=ck_hook,
            tme_hook=tme_hook,
            node_ids=node_ids,
            metadata={"neoantigen_burden": burden, "n_mutations": len(mutations)},
        )


def make_demo_immuno_profile(
    patient_id: str = "IMMUNO_DEMO",
    *,
    with_blockade: bool = False,
) -> ImmunoOncologyProfile:
    return ImmunoOncologyProfile(
        patient_id=patient_id,
        hla=make_demo_hla_profile(patient_id),
        mutations=make_demo_mutations(),
        checkpoint=make_demo_checkpoint_config(with_blockade=with_blockade),
        tme=make_demo_tme_params(exhausted=not with_blockade),
        apply_checkpoint_blockade=with_blockade,
        metadata={"source": "voidsignal.immuno demo"},
    )
