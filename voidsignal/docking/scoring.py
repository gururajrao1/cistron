"""
Empirical binding-energy scoring for VOIDSIGNAL Phase 11.

Estimates Gibbs free energy of binding (ΔG, kcal/mol) from steric (van der
Waals), hydrogen-bond, electrostatic, desolvation, and torsional terms, then
converts to equilibrium inhibition / dissociation constants:

    ΔG = R · T · ln(K_i)     ⇒     K_i = exp(ΔG / R T)

with K_i expressed in molar units.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import math

from voidsignal.docking.parser import (
    Atom3D,
    BindingBox,
    Molecule3D,
    extract_binding_pocket,
    normalize_element,
    vdw_radius,
)

# Gas constant in kcal·mol⁻¹·K⁻¹
R_KCAL = 1.987204258e-3
DEFAULT_TEMPERATURE_K = 298.15


@dataclass
class ScoreTerms:
    """Decomposed empirical score contributions (kcal/mol, more negative = better)."""

    vdw: float = 0.0
    hbond: float = 0.0
    electrostatic: float = 0.0
    desolvation: float = 0.0
    torsional: float = 0.0
    hydrophobic: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.vdw
            + self.hbond
            + self.electrostatic
            + self.desolvation
            + self.torsional
            + self.hydrophobic
        )

    def as_dict(self) -> Dict[str, float]:
        return {
            "vdw": self.vdw,
            "hbond": self.hbond,
            "electrostatic": self.electrostatic,
            "desolvation": self.desolvation,
            "torsional": self.torsional,
            "hydrophobic": self.hydrophobic,
            "total": self.total,
        }


@dataclass
class DockingScore:
    """Full docking affinity report."""

    delta_g: float
    """ΔG_bind in kcal/mol (empirical; typically negative for favourable poses)."""
    ki: float
    """Inhibition / dissociation constant in molar (M)."""
    ki_uM: float
    """Convenience: K_i in µM."""
    temperature: float
    terms: ScoreTerms
    n_contacts: int = 0
    n_hbonds: int = 0
    ligand_name: str = ""
    receptor_name: str = ""
    box: Optional[BindingBox] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "delta_g": self.delta_g,
            "ki": self.ki,
            "ki_uM": self.ki_uM,
            "temperature": self.temperature,
            "terms": self.terms.as_dict(),
            "n_contacts": self.n_contacts,
            "n_hbonds": self.n_hbonds,
            "ligand_name": self.ligand_name,
            "receptor_name": self.receptor_name,
            "box": self.box.as_dict() if self.box else None,
            "metadata": dict(self.metadata),
        }


def delta_g_to_ki(delta_g: float, *, temperature: float = DEFAULT_TEMPERATURE_K) -> float:
    """
    Convert ΔG (kcal/mol) → K_i (M) via ΔG = R T ln(K_i).

    Clamps extreme values to keep ODE solvers numerically stable.
    """
    if temperature <= 0.0:
        raise ValueError("temperature must be positive")
    rt = R_KCAL * temperature
    # Avoid overflow
    arg = max(-80.0, min(80.0, delta_g / rt))
    ki = math.exp(arg)
    return max(1e-15, min(1e3, ki))


def ki_to_delta_g(ki: float, *, temperature: float = DEFAULT_TEMPERATURE_K) -> float:
    """Convert K_i (M) → ΔG (kcal/mol)."""
    if ki <= 0.0:
        raise ValueError("ki must be positive")
    if temperature <= 0.0:
        raise ValueError("temperature must be positive")
    return R_KCAL * temperature * math.log(ki)


def _is_donor(atom: Atom3D) -> bool:
    e = normalize_element(atom.element)
    t = (atom.atom_type or "").upper()
    if t in {"HD", "HS"}:
        return True
    if e == "H":
        return True
    if e in {"N", "O"} and atom.charge > 0.05:
        return True
    return False


def _is_acceptor(atom: Atom3D) -> bool:
    e = normalize_element(atom.element)
    t = (atom.atom_type or "").upper()
    if t in {"OA", "NA", "SA", "N", "O"}:
        return True
    return e in {"O", "N"} and atom.charge <= 0.0


def _is_hydrophobic(atom: Atom3D) -> bool:
    e = normalize_element(atom.element)
    t = (atom.atom_type or "").upper()
    if t in {"A", "C", "CL", "BR"}:
        return True
    return e in {"C", "CL", "BR", "I", "F", "S"}


def _lj_energy(dist: float, r_sum: float, eps: float = 0.12) -> float:
    """Soft 12-6 Lennard-Jones with capped repulsion (pose-tolerant)."""
    if dist < 1e-6:
        return 8.0
    sigma = max(r_sum * 0.75, 0.8)
    if dist < 0.7 * sigma:
        # Soft linear steric clash (capped)
        return min(8.0, eps * 12.0 * (0.7 * sigma - dist) / max(0.7 * sigma, 1e-6) + eps)
    ratio = sigma / dist
    r6 = ratio ** 6
    r12 = r6 * r6
    return eps * (r12 - 2.0 * r6)


def _hbond_energy(dist: float) -> float:
    """Ideal H-bond well centred near 1.9 Å (donor–acceptor heavy-atom proxy 2.8 Å)."""
    ideal = 2.8
    if dist > 3.6 or dist < 2.2:
        return 0.0
    # Gaussian-like well
    return -3.5 * math.exp(-((dist - ideal) ** 2) / (2.0 * 0.25 ** 2))


def _electrostatic(qi: float, qj: float, dist: float, *, dielectric: float = 20.0) -> float:
    """Screened Coulomb (kcal/mol) with distance-dependent dielectric."""
    if dist < 0.8:
        dist = 0.8
    # 332.0636 converts e²/Å → kcal/mol
    return 332.0636 * qi * qj / (dielectric * dist)


class BindingScorer:
    """
    Empirical / force-field-inspired pose scorer.

    Parameters mirror AutoDock Vina-style weights but are deliberately simple so
    the engine stays dependency-free and numerically stable for ODE bridging.
    """

    def __init__(
        self,
        *,
        w_vdw: float = 0.8,
        w_hbond: float = 1.6,
        w_elec: float = 0.35,
        w_desolv: float = 0.2,
        w_tors: float = 0.2,
        w_hydrophobic: float = 0.5,
        temperature: float = DEFAULT_TEMPERATURE_K,
        contact_cutoff: float = 5.0,
    ) -> None:
        self.w_vdw = w_vdw
        self.w_hbond = w_hbond
        self.w_elec = w_elec
        self.w_desolv = w_desolv
        self.w_tors = w_tors
        self.w_hydrophobic = w_hydrophobic
        self.temperature = temperature
        self.contact_cutoff = contact_cutoff

    def score_pair(
        self,
        receptor_atoms: Sequence[Atom3D],
        ligand_atoms: Sequence[Atom3D],
        *,
        n_rotatable: int = 0,
    ) -> Tuple[ScoreTerms, int, int]:
        terms = ScoreTerms()
        n_contacts = 0
        n_hbonds = 0
        for lig in ligand_atoms:
            if normalize_element(lig.element) == "H" and (lig.atom_type or "").upper() not in {"HD", "HS"}:
                # Skip non-polar hydrogens for speed
                continue
            for rec in receptor_atoms:
                dx = lig.x - rec.x
                dy = lig.y - rec.y
                dz = lig.z - rec.z
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist > self.contact_cutoff:
                    continue
                n_contacts += 1
                r_sum = vdw_radius(lig.element) + vdw_radius(rec.element)
                terms.vdw += self.w_vdw * _lj_energy(dist, r_sum)

                # H-bonds (donor–acceptor)
                hb = 0.0
                if (_is_donor(lig) and _is_acceptor(rec)) or (_is_donor(rec) and _is_acceptor(lig)):
                    hb = _hbond_energy(dist)
                    if hb < -0.5:
                        n_hbonds += 1
                terms.hbond += self.w_hbond * hb

                terms.electrostatic += self.w_elec * _electrostatic(lig.charge, rec.charge, dist)

                # Desolvation proxy: bury polar atoms
                if normalize_element(lig.element) in {"N", "O"} and dist < 4.0:
                    terms.desolvation += self.w_desolv * 0.15
                if normalize_element(rec.element) in {"N", "O"} and dist < 4.0:
                    terms.desolvation += self.w_desolv * 0.05

                if _is_hydrophobic(lig) and _is_hydrophobic(rec) and 3.2 < dist < 4.5:
                    terms.hydrophobic += self.w_hydrophobic * (-0.2)

        terms.torsional = self.w_tors * (0.3 * max(0, n_rotatable))
        return terms, n_contacts, n_hbonds

    def score(
        self,
        receptor: Molecule3D,
        ligand: Molecule3D,
        *,
        box: Optional[BindingBox] = None,
        pocket_atoms: Optional[Sequence[Atom3D]] = None,
    ) -> DockingScore:
        """
        Score a ligand pose against a receptor (optionally pocket-restricted).
        """
        if pocket_atoms is None:
            pocket_box, pocket = extract_binding_pocket(receptor, ligand)
            box = box or pocket_box
        else:
            pocket = list(pocket_atoms)
            box = box or ligand.ensure_box()

        # Restrict ligand atoms inside box when possible
        lig_atoms = [
            a
            for a in ligand.atoms
            if box is None or box.contains(a.x, a.y, a.z, margin=2.0)
        ]
        if not lig_atoms:
            lig_atoms = list(ligand.atoms)

        terms, n_contacts, n_hbonds = self.score_pair(
            pocket or receptor.heavy_atoms(),
            lig_atoms,
            n_rotatable=ligand.n_rotatable,
        )
        delta_g = terms.total
        # Unbound / no-contact poses are unfavourable (positive ΔG baseline)
        if n_contacts == 0:
            delta_g = max(delta_g, 5.0) + abs(terms.torsional) + 1.0
        elif n_contacts < 3:
            delta_g += 1.5
        ki = delta_g_to_ki(delta_g, temperature=self.temperature)
        return DockingScore(
            delta_g=delta_g,
            ki=ki,
            ki_uM=ki * 1e6,
            temperature=self.temperature,
            terms=terms,
            n_contacts=n_contacts,
            n_hbonds=n_hbonds,
            ligand_name=ligand.name,
            receptor_name=receptor.name,
            box=box,
            metadata={
                "n_rotatable": ligand.n_rotatable,
                "n_pocket_atoms": len(pocket),
            },
        )


def translate_molecule(mol: Molecule3D, dx: float, dy: float, dz: float) -> Molecule3D:
    """Return a translated copy (pose refinement helper)."""
    atoms = [
        Atom3D(
            serial=a.serial,
            name=a.name,
            element=a.element,
            x=a.x + dx,
            y=a.y + dy,
            z=a.z + dz,
            residue=a.residue,
            resseq=a.resseq,
            chain=a.chain,
            charge=a.charge,
            atom_type=a.atom_type,
            occupancy=a.occupancy,
            bfactor=a.bfactor,
            is_hetero=a.is_hetero,
        )
        for a in mol.atoms
    ]
    out = Molecule3D(
        name=mol.name,
        atoms=atoms,
        bonds=list(mol.bonds),
        smiles=mol.smiles,
        source_format=mol.source_format,
        metadata=dict(mol.metadata),
    )
    out.ensure_box()
    return out


def local_pose_search(
    receptor: Molecule3D,
    ligand: Molecule3D,
    *,
    scorer: Optional[BindingScorer] = None,
    step: float = 1.0,
    grid: int = 2,
) -> DockingScore:
    """
    Tiny translational grid search around the ligand centroid (pure-Python 'dock').
    """
    scorer = scorer or BindingScorer()
    box, pocket = extract_binding_pocket(receptor, ligand)
    best = scorer.score(receptor, ligand, box=box, pocket_atoms=pocket)
    for ix in range(-grid, grid + 1):
        for iy in range(-grid, grid + 1):
            for iz in range(-grid, grid + 1):
                if ix == iy == iz == 0:
                    continue
                posed = translate_molecule(ligand, ix * step, iy * step, iz * step)
                score = scorer.score(receptor, posed, box=box, pocket_atoms=pocket)
                if score.delta_g < best.delta_g:
                    best = score
                    best.metadata["best_translation"] = [ix * step, iy * step, iz * step]
    return best
