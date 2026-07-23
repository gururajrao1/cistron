"""
Docking → pharmacology / MassActionRHS kinetic bridge (Phase 11).

Maps empirical ΔG / K_i poses onto :class:`~voidsignal.pharmacology.DrugAgent`
inhibition constants and continuous k_cat / K_m scales, optionally modulated by
AlphaFold structural disruption δ from Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import logging
import math

from voidsignal.components import KineticParameters, Protein
from voidsignal.docking.parser import Molecule3D, load_structure
from voidsignal.docking.scoring import (
    BindingScorer,
    DockingScore,
    delta_g_to_ki,
    local_pose_search,
)
from voidsignal.pharmacology import DrugAgent, Mechanism, PharmacokineticProfile
from voidsignal.structures import KineticScaleFactors
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)


@dataclass
class DockedDrugSpec:
    """Specification for building a docking-informed DrugAgent."""

    target_id: str
    ligand_name: str = "ligand"
    mechanism: Mechanism = Mechanism.COMPETITIVE
    dose: float = 1.0
    t_start: float = 0.0
    t_end: Optional[float] = 40.0
    plateau: Optional[float] = None
    edge_ids: List[str] = field(default_factory=list)
    kel: float = 0.12
    hill: float = 1.0
    efficacy: float = 1.0


@dataclass
class KineticBridgeResult:
    """Outcome of applying a docking pose to network kinetics + drug agent."""

    score: DockingScore
    agent: DrugAgent
    scales: KineticScaleFactors
    disruption: float
    target_id: str
    applied_to_network: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score.as_dict(),
            "agent": {
                "name": self.agent.name,
                "target_id": self.agent.target_id,
                "ki": self.agent.ki,
                "mechanism": self.agent.mechanism.value,
                "km": self.agent.km,
            },
            "scales": {
                "kcat_scale": self.scales.kcat_scale,
                "km_scale": self.scales.km_scale,
                "binding_scale": self.scales.binding_scale,
                "production_scale": self.scales.production_scale,
            },
            "disruption": self.disruption,
            "target_id": self.target_id,
            "applied_to_network": self.applied_to_network,
            "metadata": dict(self.metadata),
        }


def scales_from_docking(
    score: DockingScore,
    *,
    disruption: float = 0.0,
    ki_ref: float = 1e-6,
) -> KineticScaleFactors:
    """
    Map docking K_i (+ optional structural δ) onto kinetic multipliers.

    Stronger binding (smaller K_i) → stronger catalytic suppression for
    competitive-style inhibition when the ligand occupies the active site.
    Structural disruption δ further weakens residual k_cat and raises K_m.
    """
    delta = max(0.0, min(1.0, float(disruption)))
    # Affinity factor in (0, 1]: 1 = weak binder, →0 as Ki << ki_ref
    ki = max(score.ki, 1e-15)
    affinity = 1.0 / (1.0 + ki_ref / ki)  # ≈0 when Ki << ref, →1 when Ki >> ref
    # Inhibition depth from docking (favourable ΔG → deeper block)
    dg = score.delta_g
    depth = max(0.0, min(1.0, (-dg) / 8.0)) if dg < 0 else 0.05

    kcat = max(0.05, (1.0 - 0.85 * depth) * (1.0 - 0.7 * delta))
    km = (1.0 + 1.5 * depth) * (1.0 + 1.2 * delta)
    bind = max(0.05, (1.0 - 0.5 * depth) * (1.0 - 0.6 * delta))
    prod = max(0.05, 1.0 - 0.35 * delta)
    # Store affinity in metadata via unused path — return scales only
    _ = affinity
    return KineticScaleFactors(
        kcat_scale=kcat,
        km_scale=km,
        binding_scale=bind,
        production_scale=prod,
    )


def apply_scales_to_protein(
    protein: Protein,
    scales: KineticScaleFactors,
    *,
    also_edges: bool = True,
    network: Optional[SignalingNetwork] = None,
) -> None:
    """Mutate protein kinetics (and optional outgoing edge rates) in-place."""
    k = protein.kinetics
    protein.kinetics = k.with_updates(
        vmax=max(0.0, k.vmax * scales.kcat_scale),
        km=max(1e-9, k.km * scales.km_scale),
        binding_affinity=max(0.0, k.binding_affinity * scales.binding_scale),
        production_rate=max(0.0, k.production_rate * scales.production_scale),
    )
    protein.metadata["docking_kcat_scale"] = scales.kcat_scale
    protein.metadata["docking_km_scale"] = scales.km_scale
    if also_edges and network is not None:
        for edge in network.out_edges(protein.entity_id):
            edge.rate_constant = max(0.0, edge.rate_constant * scales.kcat_scale)
            edge.metadata["docking_kcat_scale"] = scales.kcat_scale


def drug_agent_from_score(
    score: DockingScore,
    spec: DockedDrugSpec,
    *,
    km_substrate: float = 1.0,
) -> DrugAgent:
    """
    Build a :class:`DrugAgent` whose ``ki`` is the docking-derived molar constant.
    """
    ki = max(1e-12, float(score.ki))
    # Keep Ki in a practical µM–mM band for ODE numerics if extremely small
    # but preserve true value in metadata
    plateau = spec.plateau if spec.plateau is not None else spec.dose
    agent = DrugAgent(
        target_id=spec.target_id,
        mechanism=spec.mechanism,
        name=f"docked:{spec.ligand_name}",
        ki=ki,
        km=max(1e-9, km_substrate),
        hill=spec.hill,
        efficacy=spec.efficacy,
        edge_ids=list(spec.edge_ids),
        plateau_concentration=plateau,
        t_start=spec.t_start,
        t_end=spec.t_end,
        pk=PharmacokineticProfile(
            dose=spec.dose,
            kel=spec.kel,
            dosing_times=[spec.t_start],
            hard_washout=True,
        ),
    )
    agent.pk  # touch
    return agent


class DockingKineticsBridge:
    """
    End-to-end: structures → score → DrugAgent + optional network kinetic stamp.
    """

    def __init__(
        self,
        *,
        scorer: Optional[BindingScorer] = None,
        pose_search: bool = True,
    ) -> None:
        self.scorer = scorer or BindingScorer()
        self.pose_search = pose_search

    def dock(
        self,
        receptor: Molecule3D,
        ligand: Molecule3D,
    ) -> DockingScore:
        if self.pose_search:
            return local_pose_search(receptor, ligand, scorer=self.scorer, step=0.75, grid=2)
        return self.scorer.score(receptor, ligand)

    def bridge(
        self,
        network: SignalingNetwork,
        receptor: Molecule3D,
        ligand: Molecule3D,
        spec: DockedDrugSpec,
        *,
        disruption: float = 0.0,
        apply_network_scales: bool = True,
        read_disruption_from_target: bool = True,
    ) -> KineticBridgeResult:
        """
        Score the pose, create a DrugAgent, and optionally rescale the target
        protein's k_cat / K_m for MassActionRHS.
        """
        if spec.target_id not in network.registry:
            raise KeyError(f"target_id {spec.target_id!r} not in network")

        score = self.dock(receptor, ligand)
        target = network.registry.get(spec.target_id)
        delta = disruption
        if read_disruption_from_target:
            raw = target.metadata.get("structure_disruption")
            if raw is not None:
                try:
                    delta = max(delta, float(raw))
                except (TypeError, ValueError):
                    pass

        scales = scales_from_docking(score, disruption=delta)
        applied = False
        if apply_network_scales and isinstance(target, Protein):
            apply_scales_to_protein(target, scales, also_edges=True, network=network)
            target.metadata["docking_delta_g"] = score.delta_g
            target.metadata["docking_ki"] = score.ki
            target.metadata["docking_ligand"] = ligand.name
            applied = True

        # Attach outgoing edges if not provided
        edge_ids = list(spec.edge_ids)
        if not edge_ids:
            edge_ids = [e.edge_id for e in network.out_edges(spec.target_id)]
        spec_local = DockedDrugSpec(
            target_id=spec.target_id,
            ligand_name=spec.ligand_name or ligand.name,
            mechanism=spec.mechanism,
            dose=spec.dose,
            t_start=spec.t_start,
            t_end=spec.t_end,
            plateau=spec.plateau,
            edge_ids=edge_ids,
            kel=spec.kel,
            hill=spec.hill,
            efficacy=spec.efficacy,
        )
        km0 = target.kinetics.km if hasattr(target, "kinetics") else 1.0
        agent = drug_agent_from_score(score, spec_local, km_substrate=km0)
        # Annotate agent name with affinity
        agent.name = f"docked:{spec_local.ligand_name}[Ki={score.ki_uM:.3g}uM]"

        return KineticBridgeResult(
            score=score,
            agent=agent,
            scales=scales,
            disruption=delta,
            target_id=spec.target_id,
            applied_to_network=applied,
            metadata={
                "ligand": ligand.as_dict(),
                "receptor_atoms": receptor.n_atoms,
            },
        )

    def bridge_from_files(
        self,
        network: SignalingNetwork,
        receptor_source: Any,
        ligand_source: Any,
        spec: DockedDrugSpec,
        **kwargs: Any,
    ) -> KineticBridgeResult:
        """Load receptor/ligand via :func:`load_structure` then :meth:`bridge`."""
        receptor = load_structure(receptor_source, name="receptor")
        ligand = load_structure(ligand_source, name=spec.ligand_name or "ligand")
        return self.bridge(network, receptor, ligand, spec, **kwargs)


def make_demo_receptor_ligand(
    *,
    pocket_center: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Tuple[Molecule3D, Molecule3D]:
    """
    Tiny synthetic pocket + ligand for tests / demos (no external files).

    Geometry is arranged so the ligand forms favourable H-bonds with the pocket
    (negative ΔG) for kinetic-bridge demos.
    """
    from voidsignal.docking.parser import Atom3D, Bond

    cx, cy, cz = pocket_center
    # Pocket: donors / acceptors on a ring ~3 Å from centre
    rec_atoms = [
        Atom3D(1, "N1", "N", cx + 3.0, cy, cz, residue="POC", charge=-0.35, atom_type="NA"),
        Atom3D(2, "O1", "O", cx, cy + 3.0, cz, residue="POC", charge=-0.45, atom_type="OA"),
        Atom3D(3, "O2", "O", cx - 3.0, cy, cz, residue="POC", charge=-0.45, atom_type="OA"),
        Atom3D(4, "N2", "N", cx, cy - 3.0, cz, residue="POC", charge=-0.35, atom_type="NA"),
        Atom3D(5, "C1", "C", cx + 2.2, cy + 2.2, cz + 0.5, residue="POC", charge=0.05, atom_type="A"),
        Atom3D(6, "C2", "C", cx - 2.2, cy + 2.2, cz - 0.5, residue="POC", charge=0.05, atom_type="A"),
        Atom3D(7, "C3", "C", cx - 2.2, cy - 2.2, cz + 0.4, residue="POC", charge=0.0, atom_type="A"),
        Atom3D(8, "C4", "C", cx + 2.2, cy - 2.2, cz - 0.4, residue="POC", charge=0.0, atom_type="A"),
    ]
    receptor = Molecule3D(name="demo_pocket", atoms=rec_atoms, source_format="synthetic")
    receptor.ensure_box(padding=6.0)

    # Ligand centred with H-bond partners aimed at pocket O/N (~2.8 Å)
    lig_atoms = [
        Atom3D(1, "C1", "C", cx, cy, cz, residue="LIG", charge=0.15, atom_type="A", is_hetero=True),
        # Donor/acceptor toward O1 at (0, 3, 0)
        Atom3D(2, "N1", "N", cx, cy + 1.35, cz, residue="LIG", charge=0.25, atom_type="N", is_hetero=True),
        Atom3D(3, "H1", "H", cx, cy + 2.15, cz, residue="LIG", charge=0.15, atom_type="HD", is_hetero=True),
        # Acceptor toward N1 at (3, 0, 0)
        Atom3D(4, "O1", "O", cx + 1.35, cy, cz, residue="LIG", charge=-0.5, atom_type="OA", is_hetero=True),
        Atom3D(5, "C2", "C", cx - 1.2, cy - 0.3, cz + 0.2, residue="LIG", charge=0.0, atom_type="A", is_hetero=True),
    ]
    ligand = Molecule3D(
        name="demo_inhibitor",
        atoms=lig_atoms,
        bonds=[
            Bond(1, 2, 1, True),
            Bond(2, 3, 1, False),
            Bond(1, 4, 1, True),
            Bond(1, 5, 1, True),
        ],
        smiles="C(N)O",
        source_format="synthetic",
    )
    ligand.ensure_box(padding=3.0)
    return receptor, ligand
