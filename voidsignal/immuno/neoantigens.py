"""
Neoantigen prediction — somatic variants → mutant peptides → MHC IC50 / immunogenicity.

Pure-Python MHC-I/II affinity estimator (no netMHCpan binary). Uses allele-specific
anchor preferences and physicochemical peptide features to estimate IC50 (nM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import hashlib
import math
import re

from voidsignal.parsers import VariantRecord
from voidsignal.structures import parse_residue_position

# ---------------------------------------------------------------------------
# Amino-acid chemistry
# ---------------------------------------------------------------------------

AA_HYDRO = {
    "A": 0.31, "R": -1.01, "N": -0.60, "D": -0.77, "C": 1.54,
    "Q": -0.22, "E": -0.64, "G": 0.00, "H": 0.13, "I": 1.80,
    "L": 1.70, "K": -0.99, "M": 1.23, "F": 1.79, "P": 0.72,
    "S": -0.04, "T": 0.26, "W": 2.25, "Y": 0.96, "V": 1.22,
}
AA_CHARGE = {
    "A": 0, "R": 1, "N": 0, "D": -1, "C": 0, "Q": 0, "E": -1, "G": 0,
    "H": 0.5, "I": 0, "L": 0, "K": 1, "M": 0, "F": 0, "P": 0, "S": 0,
    "T": 0, "W": 0, "Y": 0, "V": 0,
}
AA_MASS = {
    "A": 71.0, "R": 156.0, "N": 114.0, "D": 115.0, "C": 103.0,
    "Q": 128.0, "E": 129.0, "G": 57.0, "H": 137.0, "I": 113.0,
    "L": 113.0, "K": 128.0, "M": 131.0, "F": 147.0, "P": 97.0,
    "S": 87.0, "T": 101.0, "W": 186.0, "Y": 163.0, "V": 99.0,
}
THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "TER": "*", "STOP": "*",
}

_HGVS_MISSENSE = re.compile(
    r"(?:p\.)?(?P<ref>[A-Za-z]{1,3})(?P<pos>\d+)(?P<alt>[A-Za-z]{1,3})",
    re.IGNORECASE,
)
_HGVS_NONSENSE = re.compile(
    r"(?:p\.)?(?P<ref>[A-Za-z]{1,3})(?P<pos>\d+)\*",
    re.IGNORECASE,
)


def aa1(code: str) -> str:
    """Normalize 1- or 3-letter amino acid code to 1-letter (or '*')."""
    c = code.strip().upper()
    if len(c) == 1:
        return c
    return THREE_TO_ONE.get(c, "X")


# ---------------------------------------------------------------------------
# HLA alleles
# ---------------------------------------------------------------------------


class MHCClass(str, Enum):
    I = "I"
    II = "II"


@dataclass(frozen=True)
class HLAAllele:
    """Patient HLA allele, e.g. ``HLA-A*02:01``."""

    name: str
    mhc_class: MHCClass = MHCClass.I
    expression: float = 1.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("HLAAllele.name must be non-empty")
        if self.expression < 0.0 or not math.isfinite(self.expression):
            raise ValueError("expression must be non-negative finite")

    @property
    def normalized(self) -> str:
        return self.name.upper().replace("HLA-", "HLA-")


# Allele-specific preferred residues at anchor positions (simplified PSSM priors)
_MHC_I_ANCHORS: Dict[str, Dict[int, Dict[str, float]]] = {
    "HLA-A*02:01": {
        2: {"L": 2.5, "M": 2.2, "I": 1.8, "V": 1.5, "A": 0.8},
        9: {"V": 2.5, "L": 2.2, "I": 1.8, "A": 1.2, "M": 1.0},
    },
    "HLA-A*03:01": {
        2: {"L": 2.0, "V": 1.5, "M": 1.8, "I": 1.4},
        9: {"K": 2.8, "R": 2.5, "Y": 1.2},
    },
    "HLA-A*24:02": {
        2: {"Y": 2.8, "F": 2.2, "W": 1.5},
        9: {"F": 2.5, "L": 2.0, "I": 1.8, "W": 1.5},
    },
    "HLA-B*07:02": {
        2: {"P": 3.0, "A": 1.0},
        9: {"L": 2.5, "F": 2.0, "M": 1.8, "V": 1.5},
    },
    "HLA-B*27:05": {
        2: {"R": 3.0, "K": 1.5},
        9: {"L": 2.0, "F": 1.8, "Y": 1.5, "R": 1.2},
    },
}

_MHC_II_ANCHORS: Dict[str, Dict[int, Dict[str, float]]] = {
    "HLA-DRB1*01:01": {
        1: {"Y": 2.0, "F": 1.8, "W": 1.5, "L": 1.2},
        4: {"A": 1.5, "S": 1.2, "T": 1.0, "V": 0.8},
        6: {"A": 1.2, "S": 1.0, "T": 0.9},
        9: {"A": 1.5, "S": 1.2, "L": 1.0},
    },
    "HLA-DRB1*04:01": {
        1: {"F": 2.0, "Y": 1.8, "W": 1.5, "V": 1.2},
        4: {"D": 1.5, "E": 1.2, "Q": 1.0},
        6: {"N": 1.2, "S": 1.0, "T": 0.9},
        9: {"A": 1.2, "S": 1.0, "T": 0.8},
    },
}


@dataclass
class PatientHLAProfile:
    """Patient MHC genotype (class I + II)."""

    patient_id: str
    alleles: List[HLAAllele] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def class_i(self) -> List[HLAAllele]:
        return [a for a in self.alleles if a.mhc_class == MHCClass.I]

    def class_ii(self) -> List[HLAAllele]:
        return [a for a in self.alleles if a.mhc_class == MHCClass.II]


def make_demo_hla_profile(patient_id: str = "HLA_DEMO") -> PatientHLAProfile:
    return PatientHLAProfile(
        patient_id=patient_id,
        alleles=[
            HLAAllele("HLA-A*02:01", MHCClass.I, 1.0),
            HLAAllele("HLA-A*03:01", MHCClass.I, 0.9),
            HLAAllele("HLA-B*07:02", MHCClass.I, 0.85),
            HLAAllele("HLA-DRB1*01:01", MHCClass.II, 1.0),
        ],
    )


# ---------------------------------------------------------------------------
# Peptide generation from variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodingMutation:
    """Normalized coding change used for peptide windowing."""

    gene: str
    position: int
    ref_aa: str
    alt_aa: str
    consequence: str = "missense"
    transcript_id: Optional[str] = None
    source: str = "manual"

    def __post_init__(self) -> None:
        if self.position < 1:
            raise ValueError("position must be 1-based >= 1")
        if not self.gene:
            raise ValueError("gene must be non-empty")


def parse_hgvs_protein(hgvs: str, *, gene: str = "") -> Optional[CodingMutation]:
    """Parse ``p.L858R`` / ``p.Arg213Ter`` style HGVS into a CodingMutation."""
    raw = hgvs.strip()
    m = _HGVS_NONSENSE.search(raw.replace(" ", ""))
    if m:
        return CodingMutation(
            gene=gene or "UNKNOWN",
            position=int(m.group("pos")),
            ref_aa=aa1(m.group("ref")),
            alt_aa="*",
            consequence="nonsense",
            source="hgvs",
        )
    m = _HGVS_MISSENSE.search(raw.replace(" ", ""))
    if not m:
        return None
    alt = aa1(m.group("alt"))
    if alt == "*":
        consequence = "nonsense"
    else:
        consequence = "missense"
    return CodingMutation(
        gene=gene or "UNKNOWN",
        position=int(m.group("pos")),
        ref_aa=aa1(m.group("ref")),
        alt_aa=alt,
        consequence=consequence,
        source="hgvs",
    )


def coding_mutation_from_variant(variant: VariantRecord) -> Optional[CodingMutation]:
    """Extract CodingMutation from a VCF VariantRecord (HGVSp / AA_POS INFO)."""
    gene = variant.gene or str(variant.info.get("SYMBOL") or variant.info.get("GENE") or "")
    for key in ("HGVSp", "hgvsp", "AAChange", "Protein_change"):
        if key in variant.info:
            raw = variant.info[key]
            if isinstance(raw, list):
                raw = raw[0]
            mut = parse_hgvs_protein(str(raw), gene=gene)
            if mut is not None:
                return mut
    pos = parse_residue_position(variant)
    if pos is None:
        return None
    ref = aa1(str(variant.info.get("Ref_AA", variant.info.get("REF_AA", "X"))))
    alt = aa1(str(variant.info.get("Alt_AA", variant.info.get("ALT_AA", "X"))))
    if ref == "X" and alt == "X":
        return None
    return CodingMutation(
        gene=gene or "UNKNOWN",
        position=pos,
        ref_aa=ref,
        alt_aa=alt,
        consequence="missense",
        source="variant_info",
    )


def _synthetic_flank(gene: str, position: int, length: int, *, mutant: bool, alt_aa: str, ref_aa: str) -> str:
    """
    Build a deterministic pseudo-wildtype flank when no proteome sequence is supplied.

    Uses a gene+position seeded amino-acid stream so unit tests are reproducible
    without shipping a full UniProt cache.
    """
    seed = f"{gene.upper()}|{position}|{length}".encode()
    digest = hashlib.sha256(seed).digest()
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    chars: List[str] = []
    for i in range(length):
        chars.append(alphabet[digest[i % len(digest)] % len(alphabet)])
    # Place reference / mutant AA at the mutation index (0-based center-ish)
    mut_idx = min(length - 1, max(0, length // 2))
    chars[mut_idx] = alt_aa if mutant else ref_aa
    return "".join(chars)


def generate_peptide_windows(
    mutation: CodingMutation,
    *,
    lengths: Sequence[int] = (8, 9, 10, 11),
    wt_sequence: Optional[str] = None,
    flank: int = 10,
) -> List[Tuple[str, str, int]]:
    """
    Return list of ``(wt_peptide, mt_peptide, mut_offset)`` for each length.

    ``mut_offset`` is 0-based index of the substituted residue inside the peptide.
    Nonsense / stop → empty list (no MHC presentation of truncated stubs here).
    """
    if mutation.alt_aa == "*" or mutation.consequence == "nonsense":
        return []
    if mutation.alt_aa == mutation.ref_aa:
        return []

    out: List[Tuple[str, str, int]] = []
    for L in lengths:
        if L < 8 or L > 15:
            continue
        if wt_sequence is not None and len(wt_sequence) >= mutation.position:
            # 1-based protein position
            center = mutation.position - 1
            for start in range(max(0, center - L + 1), min(center + 1, len(wt_sequence) - L + 1)):
                end = start + L
                wt = wt_sequence[start:end]
                if len(wt) != L:
                    continue
                mt_chars = list(wt)
                offset = center - start
                if not (0 <= offset < L):
                    continue
                mt_chars[offset] = mutation.alt_aa
                mt = "".join(mt_chars)
                if wt != mt:
                    out.append((wt, mt, offset))
        else:
            # Single centered window from synthetic flank
            core = _synthetic_flank(
                mutation.gene,
                mutation.position,
                L,
                mutant=False,
                alt_aa=mutation.alt_aa,
                ref_aa=mutation.ref_aa,
            )
            mt_core = _synthetic_flank(
                mutation.gene,
                mutation.position,
                L,
                mutant=True,
                alt_aa=mutation.alt_aa,
                ref_aa=mutation.ref_aa,
            )
            offset = L // 2
            out.append((core, mt_core, offset))
    return out


# ---------------------------------------------------------------------------
# MHC binding predictor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PeptideBindingPrediction:
    """Affinity / immunogenicity call for one peptide–allele pair."""

    peptide: str
    allele: str
    mhc_class: MHCClass
    ic50_nM: float
    binding_score: float
    immunogenicity: float
    is_strong_binder: bool
    is_weak_binder: bool
    percentile_rank: float
    wildtype_peptide: Optional[str] = None
    gene: Optional[str] = None
    mutation_offset: Optional[int] = None

    @property
    def is_neoantigen_candidate(self) -> bool:
        return self.is_strong_binder or (self.is_weak_binder and self.immunogenicity >= 0.45)


def _anchor_bonus(peptide: str, allele: str, mhc_class: MHCClass) -> float:
    key = allele.upper()
    if not key.startswith("HLA-"):
        key = "HLA-" + key
    table = _MHC_I_ANCHORS if mhc_class == MHCClass.I else _MHC_II_ANCHORS
    # fuzzy key match
    anchors = None
    for k, v in table.items():
        if k in key or key in k:
            anchors = v
            break
    if anchors is None:
        # generic hydrophobics at ends for class I
        anchors = {2: {"L": 1.0, "V": 0.8, "I": 0.8}, 9: {"L": 1.0, "V": 1.0, "I": 0.8}} if mhc_class == MHCClass.I else {
            1: {"F": 1.0, "Y": 1.0},
            4: {"A": 0.8},
            9: {"A": 0.8},
        }
    bonus = 0.0
    for pos, prefs in anchors.items():
        idx = pos - 1
        if mhc_class == MHCClass.I and len(peptide) != 9 and pos == 9:
            idx = len(peptide) - 1
        if 0 <= idx < len(peptide):
            aa = peptide[idx]
            bonus += prefs.get(aa, -0.35)
    return bonus


def _physicochemical_score(peptide: str) -> float:
    if not peptide:
        return -5.0
    hydro = sum(AA_HYDRO.get(a, 0.0) for a in peptide) / len(peptide)
    charge = abs(sum(AA_CHARGE.get(a, 0.0) for a in peptide))
    # Mild preference for moderate hydrophobicity, avoid extreme charge
    return 1.2 * hydro - 0.35 * charge


def predict_binding(
    peptide: str,
    allele: HLAAllele | str,
    *,
    wildtype: Optional[str] = None,
    gene: Optional[str] = None,
    mutation_offset: Optional[int] = None,
    strong_nM: float = 50.0,
    weak_nM: float = 500.0,
) -> PeptideBindingPrediction:
    """Estimate MHC binding IC50 (nM) and immunogenicity for one peptide."""
    if isinstance(allele, str):
        mhc = MHCClass.II if "DR" in allele.upper() or "DQ" in allele.upper() or "DP" in allele.upper() else MHCClass.I
        allele_obj = HLAAllele(allele, mhc)
    else:
        allele_obj = allele

    pep = peptide.upper()
    if allele_obj.mhc_class == MHCClass.I and not (8 <= len(pep) <= 11):
        raise ValueError("MHC-I peptides must be length 8–11")
    if allele_obj.mhc_class == MHCClass.II and not (12 <= len(pep) <= 20):
        # allow shorter by padding score penalty
        pass

    anchor = _anchor_bonus(pep, allele_obj.name, allele_obj.mhc_class)
    phys = _physicochemical_score(pep)
    length_prior = 0.0
    if allele_obj.mhc_class == MHCClass.I:
        length_prior = {8: -0.3, 9: 0.6, 10: 0.2, 11: -0.2}.get(len(pep), -0.5)
    else:
        length_prior = 0.3 if 13 <= len(pep) <= 17 else -0.2

    expr = max(0.2, allele_obj.expression)
    score = (anchor + phys + length_prior) * expr

    # Map score → IC50: higher score → lower IC50
    # score≈3 → ~20 nM; score≈0 → ~500 nM; score≈-2 → ~5000 nM
    ic50 = math.exp((1.8 - score) * 1.15) * 40.0
    ic50 = max(1.0, min(50_000.0, ic50))

    # Immunogenicity: foreignness vs WT + bulky residues + binding
    foreign = 0.0
    if wildtype and len(wildtype) == len(pep):
        diffs = sum(1 for a, b in zip(wildtype.upper(), pep) if a != b)
        foreign = min(1.0, diffs / max(1, len(pep) // 3))
    bulky = sum(1 for a in pep if a in "FYW") / len(pep)
    bind_term = 1.0 / (1.0 + ic50 / 100.0)
    immuno = max(0.0, min(1.0, 0.45 * bind_term + 0.35 * foreign + 0.20 * bulky))

    # Approximate percentile rank from IC50
    pct = max(0.01, min(99.0, 100.0 * (1.0 - 1.0 / (1.0 + ic50 / 200.0))))

    return PeptideBindingPrediction(
        peptide=pep,
        allele=allele_obj.name,
        mhc_class=allele_obj.mhc_class,
        ic50_nM=ic50,
        binding_score=score,
        immunogenicity=immuno,
        is_strong_binder=ic50 <= strong_nM,
        is_weak_binder=strong_nM < ic50 <= weak_nM,
        percentile_rank=pct,
        wildtype_peptide=wildtype.upper() if wildtype else None,
        gene=gene,
        mutation_offset=mutation_offset,
    )


@dataclass
class NeoantigenRecord:
    """Filtered neoantigen candidate with best allele hit."""

    gene: str
    mutation: CodingMutation
    mutant_peptide: str
    wildtype_peptide: str
    best: PeptideBindingPrediction
    all_alleles: List[PeptideBindingPrediction] = field(default_factory=list)

    @property
    def ic50_nM(self) -> float:
        return self.best.ic50_nM

    @property
    def immunogenicity(self) -> float:
        return self.best.immunogenicity


@dataclass
class NeoantigenPanel:
    """Patient neoantigen call set."""

    patient_id: str
    hla: PatientHLAProfile
    candidates: List[NeoantigenRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def strong_binders(self) -> List[NeoantigenRecord]:
        return [c for c in self.candidates if c.best.is_strong_binder]

    def top(self, n: int = 10) -> List[NeoantigenRecord]:
        return sorted(self.candidates, key=lambda c: (c.ic50_nM, -c.immunogenicity))[:n]


class NeoantigenPredictor:
    """End-to-end variant → neoantigen pipeline."""

    def __init__(
        self,
        *,
        lengths_mhc_i: Sequence[int] = (8, 9, 10, 11),
        lengths_mhc_ii: Sequence[int] = (15,),
        strong_nM: float = 50.0,
        weak_nM: float = 500.0,
        min_immunogenicity: float = 0.25,
    ) -> None:
        self.lengths_mhc_i = tuple(lengths_mhc_i)
        self.lengths_mhc_ii = tuple(lengths_mhc_ii)
        self.strong_nM = strong_nM
        self.weak_nM = weak_nM
        self.min_immunogenicity = min_immunogenicity

    def predict_mutation(
        self,
        mutation: CodingMutation,
        hla: PatientHLAProfile,
        *,
        wt_sequence: Optional[str] = None,
    ) -> List[NeoantigenRecord]:
        records: List[NeoantigenRecord] = []
        # MHC-I
        windows = generate_peptide_windows(
            mutation, lengths=self.lengths_mhc_i, wt_sequence=wt_sequence
        )
        for wt, mt, offset in windows:
            preds: List[PeptideBindingPrediction] = []
            for allele in hla.class_i():
                preds.append(
                    predict_binding(
                        mt,
                        allele,
                        wildtype=wt,
                        gene=mutation.gene,
                        mutation_offset=offset,
                        strong_nM=self.strong_nM,
                        weak_nM=self.weak_nM,
                    )
                )
            if not preds:
                continue
            best = min(preds, key=lambda p: p.ic50_nM)
            if best.is_neoantigen_candidate and best.immunogenicity >= self.min_immunogenicity:
                records.append(
                    NeoantigenRecord(
                        gene=mutation.gene,
                        mutation=mutation,
                        mutant_peptide=mt,
                        wildtype_peptide=wt,
                        best=best,
                        all_alleles=preds,
                    )
                )

        # MHC-II (longer peptides from extended synthetic window)
        if hla.class_ii():
            long_windows = generate_peptide_windows(
                mutation, lengths=self.lengths_mhc_ii, wt_sequence=wt_sequence
            )
            for wt, mt, offset in long_windows:
                preds = [
                    predict_binding(
                        mt,
                        allele,
                        wildtype=wt,
                        gene=mutation.gene,
                        mutation_offset=offset,
                        strong_nM=self.strong_nM * 2,
                        weak_nM=self.weak_nM * 2,
                    )
                    for allele in hla.class_ii()
                ]
                if not preds:
                    continue
                best = min(preds, key=lambda p: p.ic50_nM)
                if best.ic50_nM <= self.weak_nM * 2 and best.immunogenicity >= self.min_immunogenicity * 0.8:
                    records.append(
                        NeoantigenRecord(
                            gene=mutation.gene,
                            mutation=mutation,
                            mutant_peptide=mt,
                            wildtype_peptide=wt,
                            best=best,
                            all_alleles=preds,
                        )
                    )
        return records

    def predict_panel(
        self,
        mutations: Sequence[CodingMutation],
        hla: PatientHLAProfile,
        *,
        sequences: Optional[Mapping[str, str]] = None,
    ) -> NeoantigenPanel:
        seqs = sequences or {}
        candidates: List[NeoantigenRecord] = []
        for mut in mutations:
            candidates.extend(
                self.predict_mutation(mut, hla, wt_sequence=seqs.get(mut.gene.upper()) or seqs.get(mut.gene))
            )
        # Deduplicate identical mutant peptides keeping best IC50
        best_by_pep: Dict[str, NeoantigenRecord] = {}
        for rec in candidates:
            key = f"{rec.gene}|{rec.mutant_peptide}|{rec.best.allele}"
            prev = best_by_pep.get(key)
            if prev is None or rec.ic50_nM < prev.ic50_nM:
                best_by_pep[key] = rec
        panel = NeoantigenPanel(
            patient_id=hla.patient_id,
            hla=hla,
            candidates=sorted(best_by_pep.values(), key=lambda c: c.ic50_nM),
            metadata={"n_mutations": len(mutations)},
        )
        return panel


def make_demo_mutations() -> List[CodingMutation]:
    egfr = parse_hgvs_protein("p.L858R", gene="EGFR")
    kras = parse_hgvs_protein("p.G12D", gene="KRAS")
    assert egfr is not None and kras is not None
    return [
        egfr,
        kras,
        CodingMutation(gene="TP53", position=175, ref_aa="R", alt_aa="H", consequence="missense"),
    ]
