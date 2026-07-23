"""
Multi-omics → MassActionRHS / PatientSignalingNetwork kinetic bridge (Phase 12).

Orchestrates epigenomics, splicing, PTM, and FBA metabolic feedback into a
single stamped signaling network (mirrors Phase 11 docking kinetics bridge).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Union
import copy
import logging

from voidsignal.omics.epigenomics import (
    EpigenomicProfile,
    EpigenomicTransformer,
    TranscriptionScale,
    make_demo_epigenomic_profile,
)
from voidsignal.omics.metabolomics import (
    FBAResult,
    MetabolicCoupler,
    MetabolicFeedbackState,
    MetabolomicProfile,
    make_demo_metabolomic_profile,
)
from voidsignal.omics.proteomics import (
    ProteinActivityState,
    PTMProfile,
    PTMTransformer,
    make_demo_ptm_profile,
)
from voidsignal.omics.splicing import (
    IsoformKineticEffect,
    SplicingProfile,
    SplicingTransformer,
    make_demo_splicing_profile,
)
from voidsignal.patient_profile import PatientSignalingNetwork
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)

NetworkLike = Union[SignalingNetwork, PatientSignalingNetwork]


@dataclass
class MultiOmicsProfile:
    """Unified multi-layer omics bundle for one patient / sample."""

    sample_id: str = "multiomics"
    epigenomics: Optional[EpigenomicProfile] = None
    splicing: Optional[SplicingProfile] = None
    proteomics: Optional[PTMProfile] = None
    metabolomics: Optional[MetabolomicProfile] = None
    gene_aliases: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OmicsBridgeResult:
    """Provenance + layer outputs after applying multi-omics to a network."""

    sample_id: str
    network: SignalingNetwork
    patient: Optional[PatientSignalingNetwork]
    transcription_scales: Dict[str, TranscriptionScale] = field(default_factory=dict)
    splicing_effects: Dict[str, IsoformKineticEffect] = field(default_factory=dict)
    ptm_states: Dict[str, ProteinActivityState] = field(default_factory=dict)
    fba: Optional[FBAResult] = None
    metabolic_feedback: Dict[str, MetabolicFeedbackState] = field(default_factory=dict)
    layers_applied: list[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "layers_applied": list(self.layers_applied),
            "transcription_scales": {
                g: {
                    "scale": ts.scale,
                    "methylation_factor": ts.methylation_factor,
                    "acetylation_factor": ts.acetylation_factor,
                    "accessibility_factor": ts.accessibility_factor,
                }
                for g, ts in self.transcription_scales.items()
            },
            "splicing_effects": {
                g: {
                    "kcat_scale": e.kcat_scale,
                    "binding_scale": e.binding_scale,
                    "production_scale": e.production_scale,
                    "effective_psi": e.effective_psi,
                    "n_isoforms": e.n_isoforms,
                }
                for g, e in self.splicing_effects.items()
            },
            "ptm_states": {
                g: {
                    "active_fraction": s.active_fraction,
                    "inactive_fraction": s.inactive_fraction,
                    "degraded_fraction": s.degraded_fraction,
                    "kcat_scale": s.kcat_scale,
                    "km_scale": s.km_scale,
                }
                for g, s in self.ptm_states.items()
            },
            "fba": None
            if self.fba is None
            else {
                "objective_value": self.fba.objective_value,
                "residual_norm": self.fba.residual_norm,
                "converged": self.fba.converged,
                "iterations": self.fba.iterations,
                "fluxes": dict(self.fba.fluxes),
            },
            "metabolic_feedback": {
                g: {
                    "kcat_scale": s.scales.kcat_scale,
                    "km_scale": s.scales.km_scale,
                    "production_scale": s.scales.production_scale,
                    "multipliers": dict(s.multipliers),
                    "source_fluxes": dict(s.source_fluxes),
                }
                for g, s in self.metabolic_feedback.items()
            },
            "metadata": dict(self.metadata),
        }


def _unwrap_network(target: NetworkLike) -> tuple[SignalingNetwork, Optional[PatientSignalingNetwork]]:
    if isinstance(target, PatientSignalingNetwork):
        return target.network, target
    return target, None


class MultiOmicsBridge:
    """
    Apply multi-omics layers in a stable order:

    1. Epigenomics → transcription / production
    2. Splicing → isoform k_cat / domains
    3. PTMs → active fraction & degradation
    4. Metabolomics FBA → Michaelis–Menten metabolic feedback
    """

    def __init__(
        self,
        *,
        epigenomics: Optional[EpigenomicTransformer] = None,
        splicing: Optional[SplicingTransformer] = None,
        proteomics: Optional[PTMTransformer] = None,
        metabolomics: Optional[MetabolicCoupler] = None,
        clone: bool = False,
    ) -> None:
        self.epigenomics = epigenomics or EpigenomicTransformer()
        self.splicing = splicing or SplicingTransformer()
        self.proteomics = proteomics or PTMTransformer()
        self.metabolomics = metabolomics or MetabolicCoupler()
        self.clone = clone

    def apply(
        self,
        target: NetworkLike,
        profile: MultiOmicsProfile,
        *,
        gene_aliases: Optional[Mapping[str, str]] = None,
    ) -> OmicsBridgeResult:
        network, patient = _unwrap_network(target)
        if self.clone:
            network = copy.deepcopy(network)
            if patient is not None:
                patient = copy.deepcopy(patient)
                patient.network = network

        aliases = dict(profile.gene_aliases)
        if gene_aliases:
            aliases.update(gene_aliases)

        layers: list[str] = []
        transcription: Dict[str, TranscriptionScale] = {}
        splicing_fx: Dict[str, IsoformKineticEffect] = {}
        ptm_states: Dict[str, ProteinActivityState] = {}
        fba: Optional[FBAResult] = None
        metabolic: Dict[str, MetabolicFeedbackState] = {}

        if profile.epigenomics is not None:
            transcription = self.epigenomics.apply(
                network, profile.epigenomics, gene_aliases=aliases
            )
            layers.append("epigenomics")
            logger.info("Applied epigenomics scales for %d genes", len(transcription))

        if profile.splicing is not None:
            splicing_fx = self.splicing.apply(
                network, profile.splicing, gene_aliases=aliases
            )
            layers.append("splicing")
            logger.info("Applied splicing effects for %d genes", len(splicing_fx))

        if profile.proteomics is not None:
            ptm_states = self.proteomics.apply(
                network, profile.proteomics, gene_aliases=aliases
            )
            layers.append("proteomics")
            logger.info("Applied PTM states for %d proteins", len(ptm_states))

        if profile.metabolomics is not None:
            fba, metabolic = self.metabolomics.apply(
                network, profile.metabolomics, gene_aliases=aliases
            )
            layers.append("metabolomics")
            logger.info(
                "Applied FBA feedback (obj=%.4f residual=%.3e) → %d targets",
                fba.objective_value,
                fba.residual_norm,
                len(metabolic),
            )

        if patient is not None:
            patient.metadata = dict(patient.metadata)
            patient.metadata["omics_layers"] = list(layers)
            patient.metadata["omics_sample_id"] = profile.sample_id

        return OmicsBridgeResult(
            sample_id=profile.sample_id,
            network=network,
            patient=patient,
            transcription_scales=transcription,
            splicing_effects=splicing_fx,
            ptm_states=ptm_states,
            fba=fba,
            metabolic_feedback=metabolic,
            layers_applied=layers,
            metadata={"aliases": dict(aliases)},
        )


def make_demo_multiomics_profile(sample_id: str = "OMICS_DEMO") -> MultiOmicsProfile:
    """Bundled demo panel spanning all four omics layers."""
    return MultiOmicsProfile(
        sample_id=sample_id,
        epigenomics=make_demo_epigenomic_profile(sample_id),
        splicing=make_demo_splicing_profile(sample_id),
        proteomics=make_demo_ptm_profile(sample_id),
        metabolomics=make_demo_metabolomic_profile(sample_id),
        gene_aliases={},
        metadata={"source": "voidsignal.omics demo"},
    )
