"""
Pure-Python 3D coordinate parsers for CISTRON Phase 11 docking.

Supports PDB, PDBQT, and a lightweight SMILES → 3D layout (deterministic,
no external chemistry libraries). Extracts heavy-atom coordinates, partial
charges, torsional degrees of freedom, and binding-box geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import math
import re

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Atom3D:
    """One heavy (or polar-H) atom in Cartesian space."""

    serial: int
    name: str
    element: str
    x: float
    y: float
    z: float
    residue: str = "LIG"
    resseq: int = 1
    chain: str = "A"
    charge: float = 0.0
    atom_type: str = ""
    """AutoDock atom type when known (e.g. ``A``, ``OA``, ``N``, ``HD``)."""
    occupancy: float = 1.0
    bfactor: float = 0.0
    is_hetero: bool = False

    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "serial": self.serial,
            "name": self.name,
            "element": self.element,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "residue": self.residue,
            "resseq": self.resseq,
            "chain": self.chain,
            "charge": self.charge,
            "atom_type": self.atom_type,
        }


@dataclass
class Bond:
    """Undirected bond between atom serials."""

    a: int
    b: int
    order: int = 1
    rotatable: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"a": self.a, "b": self.b, "order": self.order, "rotatable": self.rotatable}


@dataclass
class BindingBox:
    """Axis-aligned docking search box."""

    center_x: float
    center_y: float
    center_z: float
    size_x: float
    size_y: float
    size_z: float

    def contains(self, x: float, y: float, z: float, *, margin: float = 0.0) -> bool:
        hx, hy, hz = self.size_x / 2.0 + margin, self.size_y / 2.0 + margin, self.size_z / 2.0 + margin
        return (
            abs(x - self.center_x) <= hx
            and abs(y - self.center_y) <= hy
            and abs(z - self.center_z) <= hz
        )

    def volume(self) -> float:
        return max(0.0, self.size_x) * max(0.0, self.size_y) * max(0.0, self.size_z)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "center": [self.center_x, self.center_y, self.center_z],
            "size": [self.size_x, self.size_y, self.size_z],
            "volume": self.volume(),
        }

    @classmethod
    def from_atoms(
        cls,
        atoms: Sequence[Atom3D],
        *,
        padding: float = 5.0,
        min_size: float = 10.0,
    ) -> "BindingBox":
        if not atoms:
            return cls(0.0, 0.0, 0.0, min_size, min_size, min_size)
        xs = [a.x for a in atoms]
        ys = [a.y for a in atoms]
        zs = [a.z for a in atoms]
        cx, cy, cz = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, (min(zs) + max(zs)) / 2.0
        sx = max(min_size, max(xs) - min(xs) + 2.0 * padding)
        sy = max(min_size, max(ys) - min(ys) + 2.0 * padding)
        sz = max(min_size, max(zs) - min(zs) + 2.0 * padding)
        return cls(cx, cy, cz, sx, sy, sz)


@dataclass
class Molecule3D:
    """Parsed 3D molecular structure (receptor fragment or ligand)."""

    name: str
    atoms: List[Atom3D] = field(default_factory=list)
    bonds: List[Bond] = field(default_factory=list)
    box: Optional[BindingBox] = None
    smiles: Optional[str] = None
    source_format: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_atoms(self) -> int:
        return len(self.atoms)

    @property
    def n_rotatable(self) -> int:
        return sum(1 for b in self.bonds if b.rotatable)

    def heavy_atoms(self) -> List[Atom3D]:
        return [a for a in self.atoms if a.element.upper() != "H"]

    def centroid(self) -> Tuple[float, float, float]:
        heavy = self.heavy_atoms() or self.atoms
        if not heavy:
            return (0.0, 0.0, 0.0)
        n = float(len(heavy))
        return (
            sum(a.x for a in heavy) / n,
            sum(a.y for a in heavy) / n,
            sum(a.z for a in heavy) / n,
        )

    def ensure_box(self, *, padding: float = 5.0) -> BindingBox:
        if self.box is None:
            self.box = BindingBox.from_atoms(self.heavy_atoms() or self.atoms, padding=padding)
        return self.box

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "n_atoms": self.n_atoms,
            "n_heavy": len(self.heavy_atoms()),
            "n_rotatable": self.n_rotatable,
            "smiles": self.smiles,
            "source_format": self.source_format,
            "box": self.box.as_dict() if self.box else None,
            "centroid": list(self.centroid()),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Element / type helpers
# ---------------------------------------------------------------------------


_ELEMENT_FROM_NAME = re.compile(r"^([A-Za-z]{1,2})")

_VDW_RADIUS = {
    "H": 1.20,
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "S": 1.80,
    "P": 1.80,
    "F": 1.47,
    "CL": 1.75,
    "BR": 1.85,
    "I": 1.98,
    "ZN": 1.39,
    "MG": 1.73,
    "CA": 2.31,
    "FE": 2.00,
}

_DEFAULT_CHARGE = {
    "H": 0.06,
    "C": 0.0,
    "N": -0.4,
    "O": -0.5,
    "S": -0.2,
    "P": 0.5,
    "F": -0.2,
    "CL": -0.1,
    "BR": -0.1,
}


def element_from_atom_name(name: str, fallback: str = "") -> str:
    if fallback and fallback.strip():
        return normalize_element(fallback)
    raw = (name or "C").strip()
    upper = raw.upper()
    if upper.startswith("CL"):
        return "CL"
    if upper.startswith("BR"):
        return "BR"
    m = _ELEMENT_FROM_NAME.match(raw)
    if not m:
        return "C"
    return normalize_element(m.group(1))


def normalize_element(el: str) -> str:
    e = (el or "C").strip().upper()
    if e in {"CL", "BR", "ZN", "MG", "CA", "FE", "NA", "K", "SE", "SI"}:
        return e
    if len(e) >= 2 and e[:2] in {"CL", "BR", "ZN", "MG", "CA", "FE", "SE", "SI"}:
        return e[:2]
    return e[0] if e else "C"


def vdw_radius(element: str) -> float:
    return _VDW_RADIUS.get(normalize_element(element), 1.70)


def default_partial_charge(element: str) -> float:
    return _DEFAULT_CHARGE.get(normalize_element(element), 0.0)


# ---------------------------------------------------------------------------
# PDB / PDBQT
# ---------------------------------------------------------------------------


def _parse_pdb_atom_line(line: str, serial_fallback: int) -> Optional[Atom3D]:
    if not (line.startswith("ATOM") or line.startswith("HETATM")):
        return None
    # PDB fixed columns; tolerate short lines
    def col(start: int, end: int, default: str = "") -> str:
        if len(line) >= end:
            return line[start - 1 : end].strip()
        if len(line) >= start:
            return line[start - 1 :].strip()
        return default

    try:
        serial = int(col(7, 11) or serial_fallback)
    except ValueError:
        serial = serial_fallback
    name = col(13, 16) or "C"
    resname = col(18, 20) or "UNK"
    chain = col(22, 22) or "A"
    try:
        resseq = int(col(23, 26) or "1")
    except ValueError:
        resseq = 1
    try:
        x = float(col(31, 38) or "0")
        y = float(col(39, 46) or "0")
        z = float(col(47, 54) or "0")
    except ValueError:
        return None
    try:
        occ = float(col(55, 60) or "1")
    except ValueError:
        occ = 1.0
    try:
        bfac = float(col(61, 66) or "0")
    except ValueError:
        bfac = 0.0
    elem_col = col(77, 78)
    element = normalize_element(element_from_atom_name(name, elem_col))
    # PDBQT often omits the element column; trailing AutoDock types (A/OA/N/HD)
    # can leak into cols 77–78 — prefer atom-name element when that happens.
    _AD_TYPES = {
        "A", "C", "N", "O", "S", "P", "H", "HD", "HS", "OA", "NA", "SA",
        "F", "CL", "BR", "I", "MG", "MN", "ZN", "CA", "FE",
    }
    if element.upper() in _AD_TYPES and len(element) <= 2 and not elem_col:
        element = normalize_element(element_from_atom_name(name, ""))
    if element.upper() in {"A", "OA", "NA", "SA", "HD", "HS"}:
        element = normalize_element(element_from_atom_name(name, ""))
    charge = default_partial_charge(element)
    # PDBQT trailing charge / type: "  0.000 A" or " -0.274 OA"
    atom_type = ""
    tail = line[66:].strip() if len(line) > 66 else ""
    if tail:
        parts = tail.split()
        # patterns: charge type | type | charge
        if len(parts) >= 2:
            try:
                charge = float(parts[-2])
                atom_type = parts[-1]
            except ValueError:
                try:
                    charge = float(parts[-1])
                except ValueError:
                    atom_type = parts[-1]
        elif len(parts) == 1:
            try:
                charge = float(parts[0])
            except ValueError:
                atom_type = parts[0]
    return Atom3D(
        serial=serial,
        name=name,
        element=element,
        x=x,
        y=y,
        z=z,
        residue=resname,
        resseq=resseq,
        chain=chain,
        charge=charge,
        atom_type=atom_type,
        occupancy=occ,
        bfactor=bfac,
        is_hetero=line.startswith("HETATM"),
    )


def _infer_bonds_by_distance(atoms: Sequence[Atom3D]) -> List[Bond]:
    """Greedy covalent bonds from covalent radii sum × 1.2."""
    bonds: List[Bond] = []
    n = len(atoms)
    for i in range(n):
        ai = atoms[i]
        ri = vdw_radius(ai.element) * 0.6  # approximate covalent
        for j in range(i + 1, n):
            aj = atoms[j]
            rj = vdw_radius(aj.element) * 0.6
            dx, dy, dz = ai.x - aj.x, ai.y - aj.y, ai.z - aj.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            cutoff = (ri + rj) * 1.15
            if 0.4 < dist <= cutoff:
                # rotatable if single bond between heavy non-terminal-ish atoms
                rotatable = (
                    ai.element.upper() != "H"
                    and aj.element.upper() != "H"
                    and normalize_element(ai.element) in {"C", "N", "O", "S", "P"}
                    and normalize_element(aj.element) in {"C", "N", "O", "S", "P"}
                    and dist > 1.2
                )
                bonds.append(Bond(a=ai.serial, b=aj.serial, order=1, rotatable=rotatable))
    return bonds


def parse_pdb(
    source: Union[PathLike, str],
    *,
    name: str = "",
    hetero_only: bool = False,
) -> Molecule3D:
    """
    Parse a PDB file or multi-line string into :class:`Molecule3D`.
    """
    text = _load_text(source)
    atoms: List[Atom3D] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if hetero_only and line.startswith("ATOM"):
            continue
        atom = _parse_pdb_atom_line(line, serial_fallback=i)
        if atom is not None:
            atoms.append(atom)
    mol = Molecule3D(
        name=name or _guess_name(source, "receptor"),
        atoms=atoms,
        bonds=_infer_bonds_by_distance(atoms),
        source_format="pdb",
    )
    mol.ensure_box()
    return mol


def parse_pdbqt(
    source: Union[PathLike, str],
    *,
    name: str = "",
    model: int = 1,
) -> Molecule3D:
    """
    Parse AutoDock PDBQT (ligand or receptor). Uses first ``MODEL`` block when present.
    """
    text = _load_text(source)
    lines = text.splitlines()
    # Extract requested MODEL
    blocks: List[List[str]] = []
    current: List[str] = []
    in_model = False
    has_model = any(ln.startswith("MODEL") for ln in lines)
    if not has_model:
        blocks = [lines]
    else:
        for ln in lines:
            if ln.startswith("MODEL"):
                in_model = True
                current = [ln]
            elif ln.startswith("ENDMDL"):
                current.append(ln)
                blocks.append(current)
                in_model = False
                current = []
            elif in_model:
                current.append(ln)
        if not blocks and current:
            blocks.append(current)
    idx = max(0, min(model - 1, len(blocks) - 1)) if blocks else 0
    chosen = blocks[idx] if blocks else lines

    atoms: List[Atom3D] = []
    torsdof = 0
    for i, line in enumerate(chosen, start=1):
        if line.startswith("TORSDOF"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    torsdof = int(parts[1])
                except ValueError:
                    pass
            continue
        if line.startswith("REMARK") or line.startswith("ROOT") or line.startswith("BRANCH"):
            continue
        atom = _parse_pdb_atom_line(line, serial_fallback=i)
        if atom is not None:
            atoms.append(atom)

    bonds = _infer_bonds_by_distance(atoms)
    # Honour TORSDOF when provided
    if torsdof > 0:
        heavy_bonds = [
            b
            for b in bonds
            if _bond_elements(atoms, b)[0] != "H" and _bond_elements(atoms, b)[1] != "H"
        ]
        for b in bonds:
            b.rotatable = False
        for b in heavy_bonds[: max(torsdof, 1)]:
            b.rotatable = True
        if not heavy_bonds and atoms:
            # Fabricate rotatable DOF metadata when geometry is too sparse
            mol_meta_rot = torsdof
        else:
            mol_meta_rot = torsdof
    else:
        mol_meta_rot = 0
    mol = Molecule3D(
        name=name or _guess_name(source, "ligand"),
        atoms=atoms,
        bonds=bonds,
        source_format="pdbqt",
        metadata={"torsdof": torsdof, "model": model},
    )
    if torsdof > 0:
        mol.metadata["n_rotatable_declared"] = mol_meta_rot
        if mol.n_rotatable == 0 and torsdof > 0:
            # Ensure at least declared torsions are reflected for scoring
            if bonds:
                bonds[0].rotatable = True
            mol.metadata["n_rotatable_forced"] = True
    mol.ensure_box(padding=4.0)
    return mol


def _bond_elements(atoms: Sequence[Atom3D], bond: Bond) -> Tuple[str, str]:
    by_serial = {a.serial: a for a in atoms}
    ea = by_serial.get(bond.a)
    eb = by_serial.get(bond.b)
    return (
        normalize_element(ea.element) if ea else "C",
        normalize_element(eb.element) if eb else "C",
    )

# ---------------------------------------------------------------------------
# SMILES (lightweight)
# ---------------------------------------------------------------------------


_SMILES_ATOM = re.compile(
    r"(\[([^\]]+)\]|"
    r"Br|Cl|Si|Se|As|Zn|Mg|Ca|Fe|Na|"
    r"br|cl|"
    r"[BCNOPSFIbcnopsfi])"
)


def _smiles_element(token: str) -> str:
    t = token.strip()
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1]
        # strip charge / H count: C@@H → C, NH3+ → N
        m = re.match(r"([A-Za-z]{1,2})", inner)
        return normalize_element(m.group(1) if m else "C")
    return normalize_element(t)


def parse_smiles(
    smiles: str,
    *,
    name: str = "",
    bond_length: float = 1.45,
) -> Molecule3D:
    """
    Deterministic SMILES → 3D layout (chain / branch spiral).

    Not a full chemical valence engine — sufficient for docking demos, torsional
    DOF counts, and affinity scoring without RDKit / OpenBabel.
    """
    if not smiles or not smiles.strip():
        raise ValueError("SMILES string must be non-empty")
    s = smiles.strip()
    atoms: List[Atom3D] = []
    bonds: List[Bond] = []
    stack: List[int] = []  # branch points (atom index)
    ring_close: Dict[str, int] = {}
    prev: Optional[int] = None
    pending_order = 1
    serial = 1
    angle = 0.0
    x = y = z = 0.0

    i = 0
    while i < len(s):
        ch = s[i]
        if ch in " \t\n\r":
            i += 1
            continue
        if ch == "(":
            if prev is not None:
                stack.append(prev)
            i += 1
            continue
        if ch == ")":
            if stack:
                prev = stack.pop()
            i += 1
            continue
        if ch == "=":
            pending_order = 2
            i += 1
            continue
        if ch == "#":
            pending_order = 3
            i += 1
            continue
        if ch == "-":
            pending_order = 1
            i += 1
            continue
        if ch.isdigit() or ch == "%":
            # ring closure
            if ch == "%":
                digit = s[i + 1 : i + 3]
                i += 3
            else:
                digit = ch
                i += 1
            if digit in ring_close and prev is not None:
                other = ring_close.pop(digit)
                bonds.append(
                    Bond(a=atoms[other].serial, b=atoms[prev].serial, order=1, rotatable=False)
                )
            elif prev is not None:
                ring_close[digit] = prev
            continue
        if ch in ".+":
            i += 1
            continue

        m = _SMILES_ATOM.match(s, i)
        if not m:
            i += 1
            continue
        token = m.group(1)
        i = m.end()
        element = _smiles_element(token)
        # layout: advance along a gentle helix
        if atoms:
            angle += math.radians(109.5 if pending_order == 1 else 120.0)
            x += bond_length * math.cos(angle)
            y += bond_length * math.sin(angle)
            z += 0.35 * math.sin(angle * 0.5)
        atom = Atom3D(
            serial=serial,
            name=f"{element}{serial}",
            element=element,
            x=x,
            y=y,
            z=z,
            residue="LIG",
            charge=default_partial_charge(element),
            atom_type=_autodock_type(element),
            is_hetero=True,
        )
        atoms.append(atom)
        idx = len(atoms) - 1
        if prev is not None:
            rotatable = pending_order == 1 and element != "H" and atoms[prev].element != "H"
            bonds.append(
                Bond(
                    a=atoms[prev].serial,
                    b=atom.serial,
                    order=pending_order,
                    rotatable=rotatable,
                )
            )
        prev = idx
        serial += 1
        pending_order = 1

    mol = Molecule3D(
        name=name or "smiles_ligand",
        atoms=atoms,
        bonds=bonds,
        smiles=s,
        source_format="smiles",
        metadata={"n_tokens": len(atoms)},
    )
    mol.ensure_box(padding=3.5)
    return mol


def _autodock_type(element: str) -> str:
    e = normalize_element(element)
    return {
        "C": "A",
        "N": "N",
        "O": "OA",
        "S": "SA",
        "H": "HD",
        "P": "P",
        "F": "F",
        "CL": "Cl",
        "BR": "Br",
        "I": "I",
    }.get(e, "A")


# ---------------------------------------------------------------------------
# Pocket extraction
# ---------------------------------------------------------------------------


def extract_binding_pocket(
    receptor: Molecule3D,
    ligand: Optional[Molecule3D] = None,
    *,
    padding: float = 8.0,
    min_size: float = 16.0,
    near_ligand_cutoff: float = 6.0,
) -> Tuple[BindingBox, List[Atom3D]]:
    """
    Derive an active-site box.

    If ``ligand`` is given, box centres on the ligand centroid and pocket atoms
    are receptor heavy atoms within ``near_ligand_cutoff`` Å. Otherwise uses the
    receptor geometric centre with a default cubic box.
    """
    if ligand is not None and ligand.atoms:
        cx, cy, cz = ligand.centroid()
        size = max(min_size, 2.0 * padding + 4.0)
        # Expand size to cover ligand extent
        lig_box = BindingBox.from_atoms(ligand.heavy_atoms() or ligand.atoms, padding=padding, min_size=min_size)
        box = BindingBox(cx, cy, cz, lig_box.size_x, lig_box.size_y, lig_box.size_z)
        pocket_atoms: List[Atom3D] = []
        for a in receptor.heavy_atoms():
            for b in ligand.heavy_atoms() or ligand.atoms:
                dx, dy, dz = a.x - b.x, a.y - b.y, a.z - b.z
                if math.sqrt(dx * dx + dy * dy + dz * dz) <= near_ligand_cutoff:
                    pocket_atoms.append(a)
                    break
        if not pocket_atoms:
            pocket_atoms = [a for a in receptor.heavy_atoms() if box.contains(a.x, a.y, a.z)]
        return box, pocket_atoms

    cx, cy, cz = receptor.centroid()
    box = BindingBox(cx, cy, cz, min_size, min_size, min_size)
    pocket = [a for a in receptor.heavy_atoms() if box.contains(a.x, a.y, a.z, margin=2.0)]
    return box, pocket or list(receptor.heavy_atoms()[:40])


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def _load_text(source: Union[PathLike, str]) -> str:
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).is_file()):
        return Path(source).read_text(encoding="utf-8", errors="replace")
    return str(source)


def _guess_name(source: Union[PathLike, str], default: str) -> str:
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and len(source) < 260):
        try:
            p = Path(source)
            if p.suffix:
                return p.stem
        except Exception:
            pass
    return default


def load_structure(
    source: Union[PathLike, str],
    *,
    fmt: Optional[str] = None,
    name: str = "",
) -> Molecule3D:
    """
    Auto-dispatch PDB / PDBQT / SMILES based on ``fmt`` or file extension / content.
    """
    if fmt is None:
        if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source):
            suf = Path(str(source)).suffix.lower()
            if suf == ".pdbqt":
                fmt = "pdbqt"
            elif suf == ".pdb":
                fmt = "pdb"
            elif suf in {".smi", ".smiles"}:
                fmt = "smiles"
        if fmt is None:
            text_head = str(source)[:200].lstrip()
            if "ATOM" in text_head or "HETATM" in text_head or "ROOT" in text_head:
                fmt = "pdbqt" if "TORSDOF" in str(source) or "ROOT" in str(source) else "pdb"
            else:
                fmt = "smiles"
    fmt = fmt.lower()
    if fmt == "pdbqt":
        return parse_pdbqt(source, name=name)
    if fmt == "pdb":
        return parse_pdb(source, name=name)
    if fmt in {"smiles", "smi"}:
        smi = str(source).strip() if "\n" not in str(source) else Path(source).read_text(encoding="utf-8").strip().split()[0]
        if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file() and "\n" not in str(source)):
            smi = Path(source).read_text(encoding="utf-8").strip().split()[0]
        return parse_smiles(smi, name=name or "ligand")
    raise ValueError(f"Unsupported structure format {fmt!r}")
