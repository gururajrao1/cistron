"""
Clinical profile generator & ingestion for CISTRON real-world benchmarking.

Parses multi-hit oncology VCFs (CSQ / HGVS annotated), RNA-seq fold-change
matrices, and AlphaFold disruption coefficients (δ) into personalized
:class:`~cistron.patient_profile.PatientSignalingNetwork` instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import io
import logging
import math
import re
import tempfile

from cistron.components import KineticParameters, Protein
from cistron.parsers import (
    VCFParser,
    VariantConsequence,
    VariantRecord,
    consequence_to_mapping,
    normalize_consequence,
)
from cistron.patient_profile import (
    ExpressionRecord,
    PatientGenomicProfile,
    PatientProfileEngine,
    PatientSignalingNetwork,
    build_patient_network,
    load_expression_tsv,
    parse_expression_table,
)
from cistron.structures import (
    DisruptionAssessment,
    KineticScaleFactors,
    StructuralMap,
    StructureAwareModulator,
    BindingPocket,
    StructuralDomain,
    parse_residue_position,
)
from cistron.topology import InteractionType, SignalingNetwork
from cistron.vendored import VendoredPathwayRepository
from cistron.visualization.session import build_demo_mapk
from cistron.simulation import DualEngineSimulator, SimulationConfig

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

# Clinical gene ↔ simulation node aliases (MAPK-centric)
GENE_ALIASES: Dict[str, Tuple[str, ...]] = {
    "EGFR": ("EGFR",),
    "KRAS": ("KRAS", "RAS"),
    "HRAS": ("HRAS", "RAS"),
    "NRAS": ("NRAS", "RAS"),
    "BRAF": ("BRAF", "RAF"),
    "RAF1": ("RAF1", "RAF"),
    "MAP2K1": ("MAP2K1", "MEK"),
    "MAP2K2": ("MAP2K2", "MEK"),
    "MAPK1": ("MAPK1", "ERK"),
    "MAPK3": ("MAPK3", "ERK"),
    "TP53": ("TP53", "P53"),
    "EGF": ("EGF",),
}


@dataclass(frozen=True)
class ClinicalVariantSpec:
    """One curated multi-hit oncology variant for fixture / string ingestion."""

    gene: str
    hgvs_p: str
    """Protein HGVS, e.g. ``p.L858R``, ``p.G12D``, ``p.R213*``."""
    consequence: str
    chrom: str = "7"
    pos: int = 1
    ref: str = "A"
    alt: str = "G"
    clinvar_significance: str = "Pathogenic"
    residue: Optional[int] = None

    def resolved_residue(self) -> Optional[int]:
        if self.residue is not None:
            return self.residue
        return parse_residue_position(self.hgvs_p)


@dataclass
class StructuralHitReport:
    """Per-variant AlphaFold / kinetic disruption telemetry."""

    gene: str
    entity_id: Optional[str]
    hgvs_p: str
    consequence: str
    residue: Optional[int]
    disruption: float
    scales: Optional[KineticScaleFactors]
    applied: bool
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gene": self.gene,
            "entity_id": self.entity_id,
            "hgvs_p": self.hgvs_p,
            "consequence": self.consequence,
            "residue": self.residue,
            "disruption": self.disruption,
            "scales": None
            if self.scales is None
            else {
                "kcat_scale": self.scales.kcat_scale,
                "km_scale": self.scales.km_scale,
                "binding_scale": self.scales.binding_scale,
                "production_scale": self.scales.production_scale,
            },
            "applied": self.applied,
            "notes": list(self.notes),
        }


@dataclass
class ClinicalIngestionReport:
    """Telemetry from a clinical profile → PatientSignalingNetwork build."""

    patient_id: str
    n_variants_input: int
    n_variants_parsed: int
    n_mutations_applied: int
    n_expression_applied: int
    unresolved_genes: List[str]
    structural_hits: List[StructuralHitReport]
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "n_variants_input": self.n_variants_input,
            "n_variants_parsed": self.n_variants_parsed,
            "n_mutations_applied": self.n_mutations_applied,
            "n_expression_applied": self.n_expression_applied,
            "unresolved_genes": list(self.unresolved_genes),
            "structural_hits": [h.as_dict() for h in self.structural_hits],
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


@dataclass
class ClinicalCaseBundle:
    """Fully resolved clinical case ready for agent benchmarking."""

    patient: PatientSignalingNetwork
    profile: PatientGenomicProfile
    ingestion: ClinicalIngestionReport
    baseline: SignalingNetwork
    symbol_to_id: Dict[str, str]
    vcf_path: Optional[Path] = None
    expression_path: Optional[Path] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "patient": self.patient.summary(),
            "ingestion": self.ingestion.as_dict(),
            "n_baseline_nodes": len(self.baseline.nodes()),
            "symbols": sorted(self.symbol_to_id.keys()),
            "vcf_path": str(self.vcf_path) if self.vcf_path else None,
            "expression_path": str(self.expression_path) if self.expression_path else None,
        }


# ---------------------------------------------------------------------------
# Canonical multi-hit oncology fixture
# ---------------------------------------------------------------------------


def default_multihit_specs() -> List[ClinicalVariantSpec]:
    """EGFRᴸ⁸⁵⁸ᴿ + KRASᴳ¹²ᴰ + TP53ᴿ²¹³* co-occurring drivers."""
    return [
        ClinicalVariantSpec(
            gene="EGFR",
            hgvs_p="p.L858R",
            consequence="missense_variant",
            chrom="7",
            pos=55259515,
            ref="T",
            alt="G",
            residue=858,
            clinvar_significance="Pathogenic",
        ),
        ClinicalVariantSpec(
            gene="KRAS",
            hgvs_p="p.G12D",
            consequence="missense_variant",
            chrom="12",
            pos=25398284,
            ref="C",
            alt="T",
            residue=12,
            clinvar_significance="Pathogenic",
        ),
        ClinicalVariantSpec(
            gene="TP53",
            hgvs_p="p.R213*",
            consequence="stop_gained",
            chrom="17",
            pos=7578212,
            ref="G",
            alt="A",
            residue=213,
            clinvar_significance="Pathogenic",
        ),
    ]


def default_expression_panel() -> List[ExpressionRecord]:
    """RNA-seq style fold-changes for the multi-hit MAPK case."""
    return [
        ExpressionRecord(symbol="EGFR", fold_change=2.4, tpm=85.0, z_score=1.8),
        ExpressionRecord(symbol="KRAS", fold_change=1.6, tpm=42.0, z_score=1.1),
        ExpressionRecord(symbol="MAP2K1", fold_change=1.3, tpm=30.0, z_score=0.7),
        ExpressionRecord(symbol="MAPK1", fold_change=1.9, tpm=55.0, z_score=1.4),
        ExpressionRecord(symbol="TP53", fold_change=0.35, tpm=8.0, z_score=-1.6),
        ExpressionRecord(symbol="EGF", fold_change=1.1, tpm=20.0, z_score=0.2),
    ]


# ---------------------------------------------------------------------------
# VCF / expression I/O
# ---------------------------------------------------------------------------


def clinical_specs_to_vcf_text(
    specs: Sequence[ClinicalVariantSpec],
    *,
    sample: str = "PATIENT01",
) -> str:
    """
    Render a VEP-flavoured VCFv4.2 string with CSQ + gene INFO for air-gapped demos.
    """
    lines = [
        "##fileformat=VCFv4.2",
        "##source=CISTRON_clinical_benchmark",
        '##INFO=<ID=GENE,Number=1,Type=String,Description="Gene symbol">',
        '##INFO=<ID=Consequence,Number=.,Type=String,Description="Variant consequence">',
        '##INFO=<ID=HGVSp,Number=1,Type=String,Description="Protein HGVS">',
        '##INFO=<ID=AA_POS,Number=1,Type=Integer,Description="Amino-acid position">',
        '##INFO=<ID=CLNSIG,Number=.,Type=String,Description="ClinVar significance">',
        '##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations from Ensembl VEP. Format: Allele|Consequence|SYMBOL|HGVSp|Protein_position">',
        f"##SAMPLE=<ID={sample}>",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + sample,
    ]
    for i, spec in enumerate(specs, start=1):
        res = spec.resolved_residue() or 0
        csq = (
            f"{spec.alt}|{spec.consequence}|{spec.gene}|{spec.hgvs_p}|{res}"
        )
        info = (
            f"GENE={spec.gene};"
            f"Consequence={spec.consequence};"
            f"HGVSp={spec.hgvs_p};"
            f"AA_POS={res};"
            f"CLNSIG={spec.clinvar_significance};"
            f"CSQ={csq}"
        )
        vid = f"rsCLIN{i}_{spec.gene}"
        lines.append(
            f"{spec.chrom}\t{spec.pos}\t{vid}\t{spec.ref}\t{spec.alt}\t99\tPASS\t"
            f"{info}\tGT\t0/1"
        )
    return "\n".join(lines) + "\n"


def write_multihit_vcf(
    path: Optional[PathLike] = None,
    *,
    specs: Optional[Sequence[ClinicalVariantSpec]] = None,
    sample: str = "PATIENT01",
) -> Path:
    """Write the canonical multi-hit VCF to disk; returns the path."""
    target = Path(path) if path is not None else Path(tempfile.gettempdir()) / "cistron_multihit.vcf"
    target.write_text(
        clinical_specs_to_vcf_text(specs or default_multihit_specs(), sample=sample),
        encoding="utf-8",
    )
    return target


def write_expression_tsv(
    path: Optional[PathLike] = None,
    *,
    records: Optional[Sequence[ExpressionRecord]] = None,
) -> Path:
    """Write RNA-seq fold-change panel as TSV."""
    target = Path(path) if path is not None else Path(tempfile.gettempdir()) / "cistron_expression.tsv"
    rows = records or default_expression_panel()
    lines = ["gene\tfold_change\ttpm\tz_score"]
    for r in rows:
        tpm = "" if r.tpm is None else f"{r.tpm:g}"
        z = "" if r.z_score is None else f"{r.z_score:g}"
        lines.append(f"{r.symbol}\t{r.fold_change:g}\t{tpm}\t{z}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def parse_clinical_vcf(path: PathLike) -> Tuple[List[VariantRecord], List[str]]:
    """
    Parse a clinical VCF with graceful telemetry for missing headers / genes.

    Returns ``(records, warnings)``.
    """
    warnings: List[str] = []
    path = Path(path)
    if not path.is_file():
        warnings.append(f"VCF not found: {path}")
        return [], warnings
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Cannot read VCF: {exc}")
        return [], warnings

    if "##fileformat" not in text[:500]:
        warnings.append("VCF header missing ##fileformat — attempting best-effort parse")
    if "CSQ" not in text and "Consequence" not in text and "GENE" not in text:
        warnings.append(
            "No GENE/Consequence/CSQ INFO annotations detected — "
            "gene mapping may rely on structural fallbacks"
        )

    try:
        parser = VCFParser(path, auto_annotate=True)
        header, records = parser.parse()
        if not header.fileformat:
            warnings.append("Parsed VCF without fileformat metadata")
        if not records:
            warnings.append("VCF contained zero variant records")
        # Enrich residue from HGVSp if AA_POS missing
        for rec in records:
            if "AA_POS" not in rec.info and "HGVSp" in rec.info:
                pos = parse_residue_position(str(rec.info["HGVSp"]))
                if pos is not None:
                    rec.info["AA_POS"] = pos
            if rec.gene is None:
                warnings.append(f"Variant {rec.key()} has no gene annotation")
        return records, warnings
    except Exception as exc:  # noqa: BLE001
        logger.exception("Clinical VCF parse failed: %s", exc)
        warnings.append(f"VCF parse failure: {exc}")
        return [], warnings


def parse_clinical_vcf_string(vcf_text: str, *, tmp_name: str = "inline.vcf") -> Tuple[List[VariantRecord], List[str]]:
    """Parse an in-memory VCF string via a temporary file."""
    path = Path(tempfile.gettempdir()) / f"cistron_{tmp_name}"
    path.write_text(vcf_text, encoding="utf-8")
    return parse_clinical_vcf(path)


def load_clinical_expression(
    source: Union[PathLike, Sequence[Mapping[str, Any]], Sequence[ExpressionRecord], None],
) -> Tuple[List[ExpressionRecord], List[str]]:
    """Load expression from TSV path, row dicts, or ready records."""
    warnings: List[str] = []
    if source is None:
        return list(default_expression_panel()), warnings
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            warnings.append(f"Expression file missing: {path} — using defaults")
            return list(default_expression_panel()), warnings
        try:
            return load_expression_tsv(path), warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Expression load failed ({exc}) — using defaults")
            return list(default_expression_panel()), warnings
    if not source:
        return [], warnings
    if isinstance(source[0], ExpressionRecord):
        return list(source), warnings  # type: ignore[arg-type]
    return parse_expression_table(source), warnings  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Baseline network preparation
# ---------------------------------------------------------------------------


def _name_index(network: SignalingNetwork) -> Dict[str, str]:
    idx: Dict[str, str] = {}
    for ent in network.registry.entities():
        idx[ent.name.upper()] = ent.entity_id
        gs = ent.metadata.get("gene_symbol")
        if gs:
            idx[str(gs).upper()] = ent.entity_id
    return idx


def resolve_gene_to_entity(network: SignalingNetwork, gene: str) -> Optional[str]:
    """Map a clinical gene symbol onto a live entity id via aliases."""
    idx = _name_index(network)
    key = gene.upper()
    if key in idx:
        return idx[key]
    for alias in GENE_ALIASES.get(key, (key,)):
        if alias.upper() in idx:
            return idx[alias.upper()]
    return None


def ensure_clinical_scaffold(
    network: SignalingNetwork,
    *,
    ensure_tp53: bool = True,
    alias_metadata: bool = True,
) -> Dict[str, str]:
    """
    Guarantee clinical oncology nodes / aliases exist on ``network``.

    Adds TP53 as a tumour-suppressor node (inhibits ERK/MAPK1) when missing so
    stop-gained TP53 variants have a kinetic target. Stamps ``gene_symbol``
    metadata for alias resolution.
    """
    idx = _name_index(network)
    # Stamp gene symbols
    if alias_metadata:
        for ent in network.registry.entities():
            ent.metadata.setdefault("gene_symbol", ent.name)
            # Reverse aliases: if node is RAS, also accept KRAS lookups via GENE_ALIASES
            upper = ent.name.upper()
            if upper == "RAS":
                ent.metadata.setdefault("aliases", ["KRAS", "HRAS", "NRAS"])
            elif upper == "RAF":
                ent.metadata.setdefault("aliases", ["BRAF", "RAF1"])
            elif upper == "MEK":
                ent.metadata.setdefault("aliases", ["MAP2K1", "MAP2K2"])
            elif upper == "ERK":
                ent.metadata.setdefault("aliases", ["MAPK1", "MAPK3"])

    created: Dict[str, str] = {}
    if ensure_tp53 and resolve_gene_to_entity(network, "TP53") is None:
        tp53 = Protein(
            name="TP53",
            concentration=0.8,
            kinetics=KineticParameters(
                production_rate=0.05,
                degradation_rate=0.04,
                basal_activity=0.3,
            ),
            metadata={"gene_symbol": "TP53", "role": "tumor_suppressor", "clinical": True},
        )
        network.add_node(tp53)
        created["TP53"] = tp53.entity_id
        # Soft negative regulation onto ERK / MAPK1 if present
        for target_name in ("ERK", "MAPK1", "MAPK1_P"):
            tid = resolve_gene_to_entity(network, target_name)
            if tid is not None:
                network.connect(
                    tp53.entity_id,
                    tid,
                    InteractionType.INHIBITION,
                    rate_constant=0.35,
                    metadata={"clinical_edge": True, "role": "tp53_checkpoint"},
                )
                break
        logger.info("Inserted clinical TP53 scaffold node %s", tp53.entity_id)

    # Ensure KRAS label exists as alias metadata on RAS/KRAS node
    for clinical, aliases in GENE_ALIASES.items():
        eid = resolve_gene_to_entity(network, clinical)
        if eid is None:
            continue
        ent = network.registry.get(eid)
        existing = list(ent.metadata.get("aliases") or [])
        for a in aliases:
            if a.upper() not in {x.upper() for x in existing} and a.upper() != ent.name.upper():
                existing.append(a)
        ent.metadata["aliases"] = existing
        ent.metadata.setdefault("gene_symbol", clinical if clinical in aliases else ent.name)

    return created


def build_clinical_baseline(
    *,
    pathway_id: str = "hsa04010",
    prefer_vendored: bool = True,
    fallback_demo: bool = True,
) -> Tuple[SignalingNetwork, Dict[str, str], List[str]]:
    """
    Load air-gapped MAPK pathway (vendored) or demo cascade; apply clinical scaffold.

    Returns ``(network, symbol→id, warnings)``.
    """
    warnings: List[str] = []
    net: Optional[SignalingNetwork] = None
    if prefer_vendored:
        try:
            repo = VendoredPathwayRepository()
            net = repo.load_network(pathway_id, default_concentration=0.25)
            net.name = f"clinical_baseline:{pathway_id}"
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Vendored pathway load failed ({exc})")
            net = None
    if net is None and fallback_demo:
        net, _ = build_demo_mapk()
        net.name = "clinical_baseline:demo_mapk"
        warnings.append("Using demo MAPK cascade baseline")
    if net is None:
        raise RuntimeError("Unable to construct clinical baseline network")

    ensure_clinical_scaffold(net)
    # Build symbol map including aliases
    symbol_to_id: Dict[str, str] = {}
    for ent in net.registry.entities():
        symbol_to_id[ent.name] = ent.entity_id
        symbol_to_id[ent.name.upper()] = ent.entity_id
        gs = ent.metadata.get("gene_symbol")
        if gs:
            symbol_to_id[str(gs)] = ent.entity_id
            symbol_to_id[str(gs).upper()] = ent.entity_id
        for a in ent.metadata.get("aliases") or []:
            symbol_to_id[str(a)] = ent.entity_id
            symbol_to_id[str(a).upper()] = ent.entity_id
    for gene, aliases in GENE_ALIASES.items():
        eid = resolve_gene_to_entity(net, gene)
        if eid is not None:
            symbol_to_id[gene] = eid
            symbol_to_id[gene.upper()] = eid
            for a in aliases:
                symbol_to_id[a] = eid
                symbol_to_id[a.upper()] = eid
    return net, symbol_to_id, warnings


def _synthetic_structural_map(gene: str, residue: int, *, hotspot: bool) -> StructuralMap:
    """Minimal AlphaFold-like map centred on the clinical residue."""
    length = max(residue + 50, 300)
    domains = [
        StructuralDomain(
            name=f"{gene}_catalytic",
            start=max(1, residue - 25),
            end=min(length, residue + 25),
            kind="kinase" if gene.upper() in {"EGFR", "BRAF", "MAP2K1"} else "domain",
        )
    ]
    pockets = [
        BindingPocket(
            name=f"{gene}_active_site",
            residues=(max(1, residue - 2), residue, min(length, residue + 2)),
            radius_angstrom=6.0,
        )
    ]
    # High confidence around hotspot
    plddt = {r: 90.0 if abs(r - residue) <= 5 else 70.0 for r in range(1, length + 1, 5)}
    return StructuralMap(
        protein_id=gene,
        sequence_length=length,
        domains=domains,
        pockets=pockets,
        plddt=plddt,
        metadata={"synthetic": True, "clinical_gene": gene},
    )


def apply_structural_disruptions(
    network: SignalingNetwork,
    variants: Sequence[VariantRecord],
    *,
    modulator: Optional[StructureAwareModulator] = None,
) -> List[StructuralHitReport]:
    """
    Map missense / nonsense hits onto kinetic δ scales via StructureAwareModulator.
    """
    mod = modulator or StructureAwareModulator()
    reports: List[StructuralHitReport] = []
    for var in variants:
        clinical_gene = str(var.info.get("CLINICAL_GENE") or var.gene or "?")
        gene = clinical_gene
        eid = resolve_gene_to_entity(network, clinical_gene) if clinical_gene != "?" else None
        if eid is None and var.gene:
            eid = resolve_gene_to_entity(network, var.gene)
        residue = parse_residue_position(var)
        hgvs = str(var.info.get("HGVSp") or var.raw_consequence or "")
        notes: List[str] = []
        if eid is None:
            reports.append(
                StructuralHitReport(
                    gene=gene,
                    entity_id=None,
                    hgvs_p=hgvs,
                    consequence=var.consequence.value,
                    residue=residue,
                    disruption=0.0,
                    scales=None,
                    applied=False,
                    notes=["gene_unresolved_in_network"],
                )
            )
            continue
        # Register synthetic map if needed
        if mod.get(eid) is None and mod.get(gene) is None:
            if residue is None:
                residue = 100
                notes.append("residue_defaulted")
            hotspot = var.consequence is VariantConsequence.MISSENSE or "missense" in (
                var.raw_consequence or ""
            ).lower()
            smap = _synthetic_structural_map(gene, residue, hotspot=hotspot)
            smap.protein_id = eid
            mod.register(smap)
            notes.append("synthetic_alphafold_map")

        try:
            assessment, scales = mod.evaluate_variant(eid, var, consequence=var.consequence)
        except KeyError:
            try:
                assessment, scales = mod.evaluate_variant(gene, var, consequence=var.consequence)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"evaluate_failed:{exc}")
                reports.append(
                    StructuralHitReport(
                        gene=gene,
                        entity_id=eid,
                        hgvs_p=hgvs,
                        consequence=var.consequence.value,
                        residue=residue,
                        disruption=0.0,
                        scales=None,
                        applied=False,
                        notes=notes,
                    )
                )
                continue

        entity = network.registry.get(eid)
        # Gain-of-function oncogene missense (EGFR L858R, KRAS G12D): boost activity
        gof_genes = {"EGFR", "KRAS", "HRAS", "NRAS", "BRAF", "RAS", "RAF"}
        if (
            clinical_gene.upper() in gof_genes
            and var.consequence is VariantConsequence.MISSENSE
        ):
            k = entity.kinetics
            entity.kinetics = k.with_updates(
                vmax=max(k.vmax, 1.0) * (1.0 + 0.8 * max(assessment.disruption, 0.4)),
                production_rate=k.production_rate * (1.0 + 0.6 * max(assessment.disruption, 0.4)),
                km=max(0.05, k.km * (1.0 - 0.3 * max(assessment.disruption, 0.4))),
                basal_activity=min(1.0, k.basal_activity + 0.25),
            )
            entity.set_concentration(max(entity.concentration, 0.5) * 1.5)
            entity.metadata["structure_disruption"] = assessment.disruption
            entity.metadata["clinical_gof"] = True
            entity.metadata["hgvs_p"] = hgvs
            entity.metadata["clinical_gene"] = clinical_gene
            notes.append("oncogene_gof_kinetic_boost")
            applied = True
        else:
            # LoF / TP53 stop-gained — apply hypomorph / knockout scales
            try:
                if isinstance(entity, Protein):
                    mod.apply_scales(entity, scales)
                else:
                    raise TypeError("not a Protein")
                entity.metadata["structure_disruption"] = assessment.disruption
                entity.metadata["hgvs_p"] = hgvs
                applied = True
                notes.append("lof_or_hypomorph_scales_applied")
            except Exception as exc:  # noqa: BLE001
                k = entity.kinetics
                entity.kinetics = k.with_updates(
                    vmax=k.vmax * scales.kcat_scale,
                    km=k.km * scales.km_scale,
                    production_rate=k.production_rate * scales.production_scale,
                    binding_affinity=k.binding_affinity * scales.binding_scale,
                )
                entity.metadata["structure_disruption"] = assessment.disruption
                applied = True
                notes.append(f"manual_scale_fallback:{exc}")

        reports.append(
            StructuralHitReport(
                gene=gene,
                entity_id=eid,
                hgvs_p=hgvs,
                consequence=var.consequence.value,
                residue=assessment.residue,
                disruption=assessment.disruption,
                scales=scales,
                applied=applied,
                notes=notes,
            )
        )
    return reports


# ---------------------------------------------------------------------------
# High-level ingestion engine
# ---------------------------------------------------------------------------


def materialize_patient_perturbations(
    patient: PatientSignalingNetwork,
    *,
    t_end: float = 1.0,
) -> None:
    """
    Run a short DualEngine pass so VCF-derived Mutation hooks stamp concentrations /
    locks onto ``patient.network`` (survives subsequent deep-copies for the agent).
    """
    if not patient.applied_mutations:
        return
    eng = DualEngineSimulator(patient.network)
    patient.load_into(eng)
    eng.run_ode(SimulationConfig(t_end=t_end, dt=min(0.5, t_end), record_every=1))
    logger.info(
        "Materialized %d patient mutations onto network %s",
        len(patient.applied_mutations),
        patient.patient_id,
    )


class ClinicalIngestionEngine:
    """
    End-to-end clinical profile → personalized signalling network.
    """

    def __init__(
        self,
        *,
        pathway_id: str = "hsa04010",
        prefer_vendored: bool = True,
        missense_rate_scale: float = 0.55,
    ) -> None:
        self.pathway_id = pathway_id
        self.prefer_vendored = prefer_vendored
        self.missense_rate_scale = missense_rate_scale

    def ingest(
        self,
        *,
        patient_id: str = "CLIN_MULTIHIT_01",
        vcf_path: Optional[PathLike] = None,
        vcf_text: Optional[str] = None,
        expression: Union[PathLike, Sequence[Mapping[str, Any]], Sequence[ExpressionRecord], None] = None,
        apply_structure: bool = True,
    ) -> ClinicalCaseBundle:
        warnings: List[str] = []
        baseline, symbol_to_id, base_warn = build_clinical_baseline(
            pathway_id=self.pathway_id,
            prefer_vendored=self.prefer_vendored,
        )
        warnings.extend(base_warn)

        resolved_vcf: Optional[Path] = None
        if vcf_text is not None:
            records, vcf_warn = parse_clinical_vcf_string(vcf_text, tmp_name=f"{patient_id}.vcf")
            warnings.extend(vcf_warn)
        elif vcf_path is not None:
            resolved_vcf = Path(vcf_path)
            records, vcf_warn = parse_clinical_vcf(resolved_vcf)
            warnings.extend(vcf_warn)
        else:
            resolved_vcf = write_multihit_vcf()
            records, vcf_warn = parse_clinical_vcf(resolved_vcf)
            warnings.extend(vcf_warn)

        expr_records, expr_warn = load_clinical_expression(expression)
        warnings.extend(expr_warn)
        # Remap expression symbols onto network aliases (MAP2K1→MEK etc.)
        remapped_expr: List[ExpressionRecord] = []
        for er in expr_records:
            eid = resolve_gene_to_entity(baseline, er.symbol)
            if eid is None:
                remapped_expr.append(er)
                continue
            node_name = baseline.registry.get(eid).name
            remapped_expr.append(
                ExpressionRecord(
                    symbol=node_name,
                    fold_change=er.fold_change,
                    tpm=er.tpm,
                    z_score=er.z_score,
                )
            )

        # Remap clinical gene symbols onto network node names for mutation bridging
        for rec in records:
            if not rec.gene:
                continue
            eid = resolve_gene_to_entity(baseline, rec.gene)
            if eid is None:
                warnings.append(f"No network node for gene {rec.gene} — mutation may be skipped")
                continue
            rec.info["CLINICAL_GENE"] = rec.gene
            rec.gene = baseline.registry.get(eid).name

        profile = PatientGenomicProfile(
            patient_id=patient_id,
            variants=list(records),
            expression=remapped_expr,
            metadata={
                "pathway_id": self.pathway_id,
                "n_input_variants": len(records),
                "clinical_benchmark": True,
            },
        )

        # Gene map for patient engine: include aliases
        gene_map = {k: v for k, v in symbol_to_id.items() if isinstance(k, str)}

        patient = build_patient_network(
            baseline,
            patient_id,
            records,
            expression=remapped_expr,
            missense_rate_scale=self.missense_rate_scale,
        )

        structural_hits: List[StructuralHitReport] = []
        if apply_structure and records:
            structural_hits = apply_structural_disruptions(patient.network, records)

        # Stamp VCF mutations into live concentrations / locks for agent deep-copies
        try:
            materialize_patient_perturbations(patient)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Mutation materialization failed: {exc}")

        expr_path: Optional[Path] = None
        if isinstance(expression, (str, Path)):
            expr_path = Path(expression)

        report = ClinicalIngestionReport(
            patient_id=patient_id,
            n_variants_input=len(default_multihit_specs()) if not records and vcf_path is None else len(records),
            n_variants_parsed=len(records),
            n_mutations_applied=len(patient.applied_mutations),
            n_expression_applied=len(patient.expression_scales),
            unresolved_genes=list(patient.unresolved_genes),
            structural_hits=structural_hits,
            warnings=warnings,
            metadata={
                "gene_map_size": len(gene_map),
                "patient_summary": patient.summary(),
            },
        )
        return ClinicalCaseBundle(
            patient=patient,
            profile=profile,
            ingestion=report,
            baseline=baseline,
            symbol_to_id=symbol_to_id,
            vcf_path=resolved_vcf,
            expression_path=expr_path,
        )
