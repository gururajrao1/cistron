"""
Bioinformatics file parsers for VOIDSIGNAL Phase 2.

Native streaming readers for VCF, FASTA, GFF/GTF, and BED that bridge raw
genomic artefacts into Phase 1 simulation objects — especially
:class:`~voidsignal.perturbation.Mutation` instances derived from variant
consequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    TextIO,
    Tuple,
    Union,
)
import gzip
import logging
import re

from voidsignal.perturbation import Mutation, MutationKind

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Shared I/O helpers
# ---------------------------------------------------------------------------


def open_text(path: PathLike) -> TextIO:
    """Open a text path, transparently handling ``.gz`` compression."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {p}")
    if p.suffix == ".gz" or p.name.endswith(".vcf.gz"):
        return gzip.open(p, mode="rt", encoding="utf-8", errors="replace")
    return p.open(mode="r", encoding="utf-8", errors="replace")


def _split_info(info_field: str) -> Dict[str, Any]:
    """Parse a VCF INFO column into a dict (flags → True, key=value → typed)."""
    result: Dict[str, Any] = {}
    if not info_field or info_field == ".":
        return result
    for token in info_field.split(";"):
        if not token:
            continue
        if "=" not in token:
            result[token] = True
            continue
        key, raw = token.split("=", 1)
        if "," in raw:
            parts = raw.split(",")
            typed: List[Any] = []
            for part in parts:
                typed.append(_coerce_scalar(part))
            result[key] = typed
        else:
            result[key] = _coerce_scalar(raw)
    return result


def _coerce_scalar(raw: str) -> Any:
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    try:
        if re.fullmatch(r"[+-]?\d+", raw):
            return int(raw)
        if re.fullmatch(r"[+-]?(\d+\.\d*|\d*\.\d+)([eE][+-]?\d+)?", raw) or re.fullmatch(
            r"[+-]?\d+[eE][+-]?\d+", raw
        ):
            return float(raw)
    except (TypeError, ValueError):
        pass
    return raw


# ---------------------------------------------------------------------------
# Variant consequence → Mutation mapping
# ---------------------------------------------------------------------------


class VariantConsequence(Enum):
    """Normalised consequence vocabulary used by the VCF→Mutation bridge."""

    STOP_GAINED = "stop_gained"
    STOP_LOST = "stop_lost"
    FRAMESHIFT = "frameshift_variant"
    SPLICE_ACCEPTOR = "splice_acceptor_variant"
    SPLICE_DONOR = "splice_donor_variant"
    START_LOST = "start_lost"
    MISSENSE = "missense_variant"
    SYNONYMOUS = "synonymous_variant"
    INFRAME_INSERTION = "inframe_insertion"
    INFRAME_DELETION = "inframe_deletion"
    UPSTREAM = "upstream_gene_variant"
    DOWNSTREAM = "downstream_gene_variant"
    INTRON = "intron_variant"
    UTR_5 = "5_prime_UTR_variant"
    UTR_3 = "3_prime_UTR_variant"
    REGULATORY = "regulatory_region_variant"
    UNKNOWN = "unknown"


# Map common ANN/CSQ / custom INFO tokens onto the normalised enum.
_CONSEQUENCE_ALIASES: Dict[str, VariantConsequence] = {
    "stop_gained": VariantConsequence.STOP_GAINED,
    "nonsense": VariantConsequence.STOP_GAINED,
    "nonsense_mutation": VariantConsequence.STOP_GAINED,
    "stop_codon": VariantConsequence.STOP_GAINED,
    "stop_lost": VariantConsequence.STOP_LOST,
    "frameshift_variant": VariantConsequence.FRAMESHIFT,
    "frameshift": VariantConsequence.FRAMESHIFT,
    "splice_acceptor_variant": VariantConsequence.SPLICE_ACCEPTOR,
    "splice_donor_variant": VariantConsequence.SPLICE_DONOR,
    "splice_site": VariantConsequence.SPLICE_ACCEPTOR,
    "start_lost": VariantConsequence.START_LOST,
    "missense_variant": VariantConsequence.MISSENSE,
    "missense": VariantConsequence.MISSENSE,
    "non_synonymous_codon": VariantConsequence.MISSENSE,
    "synonymous_variant": VariantConsequence.SYNONYMOUS,
    "synonymous": VariantConsequence.SYNONYMOUS,
    "silent": VariantConsequence.SYNONYMOUS,
    "inframe_insertion": VariantConsequence.INFRAME_INSERTION,
    "inframe_deletion": VariantConsequence.INFRAME_DELETION,
    "upstream_gene_variant": VariantConsequence.UPSTREAM,
    "downstream_gene_variant": VariantConsequence.DOWNSTREAM,
    "intron_variant": VariantConsequence.INTRON,
    "5_prime_utr_variant": VariantConsequence.UTR_5,
    "3_prime_utr_variant": VariantConsequence.UTR_3,
    "regulatory_region_variant": VariantConsequence.REGULATORY,
}


# Loss-of-function consequences → permanent knockout.
_LOF_CONSEQUENCES = {
    VariantConsequence.STOP_GAINED,
    VariantConsequence.FRAMESHIFT,
    VariantConsequence.SPLICE_ACCEPTOR,
    VariantConsequence.SPLICE_DONOR,
    VariantConsequence.START_LOST,
}


@dataclass(frozen=True)
class ConsequenceMapping:
    """Resolved Phase 1 mutation recipe for a variant consequence."""

    kind: MutationKind
    rate_scale: float = 1.0
    expression_level: float = 0.0
    permanent_lock: bool = True
    skip: bool = False
    """If True, the variant should not produce a Mutation (e.g. synonymous)."""


def normalize_consequence(raw: str) -> VariantConsequence:
    """Map a free-text / VEP-style consequence token to :class:`VariantConsequence`."""
    if not raw:
        return VariantConsequence.UNKNOWN
    token = raw.strip().lower().replace(" ", "_")
    # VEP may pipe multiple effects — take the most severe known token.
    parts = re.split(r"[&|,/]", token)
    severity_order = [
        VariantConsequence.STOP_GAINED,
        VariantConsequence.FRAMESHIFT,
        VariantConsequence.SPLICE_ACCEPTOR,
        VariantConsequence.SPLICE_DONOR,
        VariantConsequence.START_LOST,
        VariantConsequence.STOP_LOST,
        VariantConsequence.MISSENSE,
        VariantConsequence.INFRAME_DELETION,
        VariantConsequence.INFRAME_INSERTION,
        VariantConsequence.UTR_5,
        VariantConsequence.UTR_3,
        VariantConsequence.REGULATORY,
        VariantConsequence.UPSTREAM,
        VariantConsequence.DOWNSTREAM,
        VariantConsequence.INTRON,
        VariantConsequence.SYNONYMOUS,
    ]
    found: List[VariantConsequence] = []
    for part in parts:
        part = part.strip()
        if part in _CONSEQUENCE_ALIASES:
            found.append(_CONSEQUENCE_ALIASES[part])
    if not found:
        return VariantConsequence.UNKNOWN
    for sev in severity_order:
        if sev in found:
            return sev
    return found[0]


def consequence_to_mapping(consequence: VariantConsequence) -> ConsequenceMapping:
    """
    Translate a normalised consequence into Phase 1 :class:`Mutation` arguments.

    Biology
    -------
    * Premature stop / frameshift / canonical splice → hard knockout.
    * Missense → hypomorph (partial LoF; default scale 0.5).
    * Stop-lost → constitutive residual activity (read-through approximation).
    * Synonymous / deep intron → skipped (no simulation impact by default).
    """
    if consequence in _LOF_CONSEQUENCES:
        return ConsequenceMapping(kind=MutationKind.KNOCKOUT, permanent_lock=True)
    if consequence is VariantConsequence.MISSENSE:
        return ConsequenceMapping(
            kind=MutationKind.HYPOMORPH,
            rate_scale=0.5,
            permanent_lock=False,
        )
    if consequence is VariantConsequence.STOP_LOST:
        return ConsequenceMapping(
            kind=MutationKind.CONSTITUTIVE_ACTIVATION,
            expression_level=0.5,
            permanent_lock=True,
        )
    if consequence in {
        VariantConsequence.INFRAME_INSERTION,
        VariantConsequence.INFRAME_DELETION,
    }:
        return ConsequenceMapping(
            kind=MutationKind.HYPOMORPH,
            rate_scale=0.75,
            permanent_lock=False,
        )
    if consequence in {
        VariantConsequence.SYNONYMOUS,
        VariantConsequence.INTRON,
        VariantConsequence.UPSTREAM,
        VariantConsequence.DOWNSTREAM,
        VariantConsequence.UTR_5,
        VariantConsequence.UTR_3,
        VariantConsequence.REGULATORY,
        VariantConsequence.UNKNOWN,
    }:
        return ConsequenceMapping(kind=MutationKind.HYPOMORPH, skip=True)
    return ConsequenceMapping(kind=MutationKind.HYPOMORPH, skip=True)


# ---------------------------------------------------------------------------
# Genomic interval index — raw-VCF gene / impact fallback
# ---------------------------------------------------------------------------


_STOP_CODONS = {"TAA", "TAG", "TGA"}
_START_CODONS = {"ATG"}


@dataclass(frozen=True)
class GeneInterval:
    """
    1-based inclusive genomic span for a gene / CDS used during VCF fallback.

    Coordinate convention matches VCF POS (1-based). When loading from BED
    (0-based half-open), convert via :meth:`from_bed_coords`.
    """

    chrom: str
    start: int
    end: int
    gene: str
    strand: str = "+"
    cds_start: Optional[int] = None
    cds_end: Optional[int] = None
    coding_sequence: Optional[str] = None
    """Optional CDS DNA sequence (5'→3' on the sense strand) for stop inference."""

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"GeneInterval end < start for {self.gene}")
        if self.start < 1:
            raise ValueError("GeneInterval coordinates must be 1-based (start ≥ 1)")

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def effective_cds_start(self) -> int:
        return self.cds_start if self.cds_start is not None else self.start

    @property
    def effective_cds_end(self) -> int:
        return self.cds_end if self.cds_end is not None else self.end

    def contains(self, pos: int) -> bool:
        return self.start <= pos <= self.end

    def cds_fraction(self, pos: int) -> float:
        """Normalised position along the CDS / gene (0 = 5' end, 1 = 3' end)."""
        lo = self.effective_cds_start
        hi = self.effective_cds_end
        if hi <= lo:
            return 0.0
        if self.strand == "-":
            return max(0.0, min(1.0, (hi - pos) / float(hi - lo)))
        return max(0.0, min(1.0, (pos - lo) / float(hi - lo)))

    @classmethod
    def from_bed_coords(
        cls,
        chrom: str,
        start0: int,
        end0: int,
        gene: str,
        *,
        strand: str = "+",
        coding_sequence: Optional[str] = None,
    ) -> "GeneInterval":
        """Build from BED 0-based half-open coordinates."""
        return cls(
            chrom=chrom,
            start=start0 + 1,
            end=end0,
            gene=gene,
            strand=strand if strand in {"+", "-"} else "+",
            coding_sequence=coding_sequence,
        )


class GenomicIntervalIndex:
    """
    Chromosome-keyed interval store with binary-search query.

    Built from GFF gene features, BED intervals, or an explicit dictionary of
    ``gene → (chrom, start, end)`` tuples — the structural fallback for raw
    unannotated VCFs.
    """

    def __init__(self) -> None:
        self._by_chrom: Dict[str, List[GeneInterval]] = {}
        self._sorted = False

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_chrom.values())

    def add(self, interval: GeneInterval) -> None:
        chrom = _normalize_chrom(interval.chrom)
        # Rebuild frozen-like with normalised chrom via new instance
        if interval.chrom != chrom:
            interval = GeneInterval(
                chrom=chrom,
                start=interval.start,
                end=interval.end,
                gene=interval.gene,
                strand=interval.strand,
                cds_start=interval.cds_start,
                cds_end=interval.cds_end,
                coding_sequence=interval.coding_sequence,
            )
        self._by_chrom.setdefault(chrom, []).append(interval)
        self._sorted = False

    def _ensure_sorted(self) -> None:
        if self._sorted:
            return
        for chrom in self._by_chrom:
            self._by_chrom[chrom].sort(key=lambda iv: (iv.start, iv.end, iv.gene))
        self._sorted = True

    def query(self, chrom: str, pos: int) -> List[GeneInterval]:
        """Return all intervals overlapping 1-based ``pos`` on ``chrom``."""
        self._ensure_sorted()
        keys = {_normalize_chrom(chrom)}
        raw = chrom.strip()
        if raw.lower().startswith("chr"):
            keys.add(raw[3:])
            keys.add("chr" + raw[3:])
        else:
            keys.add("chr" + raw)
        hits: List[GeneInterval] = []
        seen: Set[Tuple[str, int, int, str]] = set()
        for key in keys:
            intervals = self._by_chrom.get(key, [])
            for iv in intervals:
                if iv.start > pos:
                    break
                if iv.contains(pos):
                    sig = (iv.chrom, iv.start, iv.end, iv.gene)
                    if sig not in seen:
                        seen.add(sig)
                        hits.append(iv)
        return hits

    def best_hit(self, chrom: str, pos: int) -> Optional[GeneInterval]:
        """Prefer the shortest overlapping interval (usually CDS ⊂ gene)."""
        hits = self.query(chrom, pos)
        if not hits:
            return None
        hits.sort(key=lambda iv: (iv.length, iv.gene))
        return hits[0]

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, Tuple[str, int, int]],
        *,
        one_based: bool = True,
    ) -> "GenomicIntervalIndex":
        """
        Build from ``{gene: (chrom, start, end)}``.

        Coordinates are treated as 1-based inclusive unless ``one_based=False``
        (then interpreted as BED 0-based half-open).
        """
        index = cls()
        for gene, (chrom, start, end) in mapping.items():
            if one_based:
                index.add(GeneInterval(chrom=chrom, start=int(start), end=int(end), gene=gene))
            else:
                index.add(GeneInterval.from_bed_coords(chrom, int(start), int(end), gene))
        return index

    @classmethod
    def from_gff(cls, path: PathLike, *, feature_types: Sequence[str] = ("gene", "CDS")) -> "GenomicIntervalIndex":
        index = cls()
        features = GFFParser(path).parse()
        # Collect CDS spans per gene for tighter impact inference
        cds_spans: Dict[str, List[Tuple[int, int]]] = {}
        gene_rows: List[GenomicFeature] = []
        for feat in features:
            if feat.feature_type == "CDS":
                gname = feat.gene_name or feat.attributes.get("Parent") or feat.attributes.get("ID")
                if gname:
                    cds_spans.setdefault(gname, []).append((feat.start, feat.end))
            if feat.feature_type in feature_types and feat.feature_type != "CDS":
                gene_rows.append(feat)
            elif feat.feature_type == "gene":
                gene_rows.append(feat)
        seen: set[str] = set()
        for feat in gene_rows:
            name = feat.gene_name
            if not name or name in seen:
                continue
            seen.add(name)
            spans = cds_spans.get(name, [])
            cds_start = min(s[0] for s in spans) if spans else None
            cds_end = max(s[1] for s in spans) if spans else None
            index.add(
                GeneInterval(
                    chrom=feat.seqid,
                    start=feat.start,
                    end=feat.end,
                    gene=name,
                    strand=feat.strand,
                    cds_start=cds_start,
                    cds_end=cds_end,
                )
            )
        return index

    @classmethod
    def from_bed(cls, path: PathLike) -> "GenomicIntervalIndex":
        index = cls()
        for iv in BEDParser(path).iter_intervals():
            if not iv.name:
                continue
            index.add(
                GeneInterval.from_bed_coords(
                    iv.chrom,
                    iv.start,
                    iv.end,
                    iv.name,
                    strand=iv.strand or "+",
                )
            )
        return index


def _normalize_chrom(chrom: str) -> str:
    text = chrom.strip()
    if text.lower().startswith("chr"):
        return "chr" + text[3:]
    # Keep bare numbers/X/Y/MT under chr-less and chr-prefixed aliases via dual insert in query
    return text


def infer_structural_consequence(
    ref: str,
    alt: str,
    pos: int,
    interval: GeneInterval,
) -> Tuple[VariantConsequence, str, float]:
    """
    Infer consequence without VEP/snpeff INFO annotations.

    Rules (ordered)
    ---------------
    1. Large SVs (``len(ref|alt) ≥ 50``) → frameshift (hard LoF prior).
    2. Indels whose length delta is not divisible by 3 → frameshift.
    3. In-frame indels → inframe insertion / deletion.
    4. If coding sequence is available, translate the affected codon — stop
       gained / start lost when detectable.
    5. Early CDS position (fraction < 0.05) for SNVs → start_lost prior.
    6. Late CDS truncation heuristics: indel in final 5% → milder inframe prior.
    7. Default coding SNV → missense_variant.
    """
    frac = interval.cds_fraction(pos)
    ref_u = (ref or "").upper()
    alt_u = (alt or "").upper()
    if not alt_u or alt_u == ".":
        return VariantConsequence.UNKNOWN, "missing_alt", frac

    # Structural / length-based
    if max(len(ref_u), len(alt_u)) >= 50:
        return VariantConsequence.FRAMESHIFT, "large_sv", frac

    delta = abs(len(ref_u) - len(alt_u))
    if delta > 0:
        if delta % 3 != 0:
            return VariantConsequence.FRAMESHIFT, "frameshift_indel", frac
        if len(alt_u) > len(ref_u):
            return VariantConsequence.INFRAME_INSERTION, "inframe_insertion", frac
        return VariantConsequence.INFRAME_DELETION, "inframe_deletion", frac

    # SNV codon-level inference when CDS DNA is present
    if interval.coding_sequence and len(ref_u) == 1 and len(alt_u) == 1:
        codon_hit = _snv_codon_consequence(ref_u, alt_u, pos, interval)
        if codon_hit is not None:
            return codon_hit[0], codon_hit[1], frac

    if frac <= 0.05 and len(ref_u) == 1 and len(alt_u) == 1:
        return VariantConsequence.START_LOST, "early_cds_snv", frac

    return VariantConsequence.MISSENSE, "coding_snv_default", frac


def _snv_codon_consequence(
    ref: str,
    alt: str,
    pos: int,
    interval: GeneInterval,
) -> Optional[Tuple[VariantConsequence, str]]:
    seq = (interval.coding_sequence or "").upper().replace("U", "T")
    if not seq or len(seq) < 3:
        return None
    cds0 = interval.effective_cds_start
    if pos < cds0 or pos > interval.effective_cds_end:
        return None
    # Offset into sense-strand CDS
    if interval.strand == "-":
        offset = interval.effective_cds_end - pos
    else:
        offset = pos - cds0
    if offset < 0 or offset >= len(seq):
        return None
    codon_index = offset // 3
    codon_pos = offset % 3
    start = codon_index * 3
    if start + 3 > len(seq):
        return None
    codon = list(seq[start : start + 3])
    # Verify reference base matches when possible
    if codon[codon_pos] not in {ref, "N"}:
        # Mismatch — still attempt with declared REF (assembly drift)
        pass
    mut = codon.copy()
    mut[codon_pos] = alt
    mut_codon = "".join(mut)
    ref_codon = "".join(codon)
    if codon_index == 0 and ref_codon in _START_CODONS and mut_codon not in _START_CODONS:
        return VariantConsequence.START_LOST, "start_codon_disrupted"
    if mut_codon in _STOP_CODONS and ref_codon not in _STOP_CODONS:
        return VariantConsequence.STOP_GAINED, "nonsense_codon"
    if ref_codon in _STOP_CODONS and mut_codon not in _STOP_CODONS:
        return VariantConsequence.STOP_LOST, "stop_codon_lost"
    return VariantConsequence.MISSENSE, "nonsynonymous_codon"


# ---------------------------------------------------------------------------
# VCF
# ---------------------------------------------------------------------------


@dataclass
class VariantRecord:
    """One non-header VCF data line, fully parsed."""

    chrom: str
    pos: int
    variant_id: str
    ref: str
    alt: List[str]
    qual: Optional[float]
    filter_status: List[str]
    info: Dict[str, Any]
    format_keys: List[str] = field(default_factory=list)
    samples: Dict[str, Dict[str, str]] = field(default_factory=dict)
    gene: Optional[str] = None
    consequence: VariantConsequence = VariantConsequence.UNKNOWN
    raw_consequence: Optional[str] = None
    annotation_source: str = "none"
    """``info`` | ``interval_fallback`` | ``none`` — provenance of gene/consequence."""
    inferred_cds_fraction: Optional[float] = None
    """Fraction along matched gene/CDS interval used for impact heuristics (0–1)."""

    @property
    def primary_alt(self) -> str:
        return self.alt[0] if self.alt else "."

    def key(self) -> str:
        return f"{self.chrom}:{self.pos}:{self.ref}>{self.primary_alt}"


@dataclass
class VCFHeader:
    """VCF meta-information and column header."""

    fileformat: Optional[str] = None
    infos: Dict[str, Dict[str, str]] = field(default_factory=dict)
    filters: Dict[str, str] = field(default_factory=dict)
    contigs: List[str] = field(default_factory=list)
    sample_names: List[str] = field(default_factory=list)
    raw_meta: List[str] = field(default_factory=list)


class VCFParseError(ValueError):
    """Raised when a VCF record cannot be parsed."""


class VCFParser:
    """
    Streaming VCF reader (VCFv4.1+ compatible subset).

    Extracts CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO, and optional
    genotype columns. Consequence / gene symbols are resolved from common INFO
    keys (`GENE`, `SYMBOL`, `ANN`, `CSQ`, `Consequence`) when present.

    Raw / unannotated VCFs
    ----------------------
    When INFO lacks VEP/snpeff annotations, the parser falls back to
    :class:`GenomicIntervalIndex` (GFF/BED/dict) to recover the overlapping
    gene and a structural impact prior via :func:`infer_structural_consequence`.
    """

    def __init__(
        self,
        path: PathLike,
        *,
        feature_index: Optional[GenomicIntervalIndex] = None,
        gene_locus_map: Optional[Mapping[str, Tuple[str, int, int]]] = None,
        auto_annotate: bool = True,
    ) -> None:
        self.path = Path(path)
        self.header = VCFHeader()
        self._column_names: List[str] = []
        self.auto_annotate = auto_annotate
        self.feature_index = feature_index
        if self.feature_index is None and gene_locus_map is not None:
            self.feature_index = GenomicIntervalIndex.from_mapping(gene_locus_map)
        self.fallback_annotated = 0
        self.fallback_unresolved = 0

    def parse(self) -> Tuple[VCFHeader, List[VariantRecord]]:
        records: List[VariantRecord] = []
        with open_text(self.path) as handle:
            for record in self.iter_records(handle):
                records.append(record)
        return self.header, records

    def iter_records(self, handle: Optional[TextIO] = None) -> Iterator[VariantRecord]:
        owns_handle = handle is None
        fh = handle if handle is not None else open_text(self.path)
        try:
            for line_no, line in enumerate(fh, start=1):
                line = line.rstrip("\n\r")
                if not line:
                    continue
                if line.startswith("##"):
                    self._ingest_meta(line)
                    continue
                if line.startswith("#CHROM") or line.startswith("#chrom"):
                    self._ingest_column_header(line)
                    continue
                if line.startswith("#"):
                    self.header.raw_meta.append(line)
                    continue
                try:
                    record = self._parse_data_line(line)
                    if self.auto_annotate:
                        record = self.apply_structural_fallback(record)
                    yield record
                except VCFParseError as exc:
                    logger.warning("Skipping malformed VCF line %s: %s", line_no, exc)
        finally:
            if owns_handle:
                fh.close()

    def apply_structural_fallback(self, record: VariantRecord) -> VariantRecord:
        """
        Fill gene + consequence when INFO annotations are absent.

        Leaves annotated records unchanged. Requires a populated
        ``feature_index``; otherwise marks unresolved and returns as-is.
        """
        has_info_ann = bool(record.gene) or (
            record.consequence is not VariantConsequence.UNKNOWN
            and record.raw_consequence is not None
        )
        if has_info_ann:
            if record.annotation_source == "none":
                record.annotation_source = "info"
            return record
        if self.feature_index is None:
            self.fallback_unresolved += 1
            return record
        hit = self.feature_index.best_hit(record.chrom, record.pos)
        if hit is None:
            # Try alternate chr prefixing
            chrom = record.chrom
            alt_chrom = chrom[3:] if chrom.lower().startswith("chr") else f"chr{chrom}"
            hit = self.feature_index.best_hit(alt_chrom, record.pos)
        if hit is None:
            self.fallback_unresolved += 1
            logger.debug(
                "No interval hit for %s:%s — leaving unannotated",
                record.chrom,
                record.pos,
            )
            return record
        alt = record.primary_alt
        consequence, reason, frac = infer_structural_consequence(
            record.ref, alt, record.pos, hit
        )
        record.gene = hit.gene
        record.consequence = consequence
        record.raw_consequence = f"structural_fallback:{reason}"
        record.annotation_source = "interval_fallback"
        record.inferred_cds_fraction = frac
        record.info = dict(record.info)
        record.info["VS_GENE"] = hit.gene
        record.info["VS_CONSEQUENCE"] = consequence.value
        record.info["VS_FALLBACK"] = reason
        self.fallback_annotated += 1
        return record

    def annotate_records(
        self,
        records: Sequence[VariantRecord],
        feature_index: Optional[GenomicIntervalIndex] = None,
    ) -> List[VariantRecord]:
        """Post-hoc annotation pass (e.g. after attaching a GFF-built index)."""
        if feature_index is not None:
            self.feature_index = feature_index
        return [self.apply_structural_fallback(r) for r in records]

    def _ingest_meta(self, line: str) -> None:
        self.header.raw_meta.append(line)
        body = line[2:]
        if body.startswith("fileformat="):
            self.header.fileformat = body.split("=", 1)[1]
            return
        if body.startswith("INFO="):
            parsed = self._parse_angled(body[len("INFO=") :])
            key = parsed.get("ID")
            if key:
                self.header.infos[key] = parsed
            return
        if body.startswith("FILTER="):
            parsed = self._parse_angled(body[len("FILTER=") :])
            key = parsed.get("ID")
            if key:
                self.header.filters[key] = parsed.get("Description", "")
            return
        if body.startswith("contig="):
            parsed = self._parse_angled(body[len("contig=") :])
            cid = parsed.get("ID")
            if cid:
                self.header.contigs.append(cid)

    @staticmethod
    def _parse_angled(blob: str) -> Dict[str, str]:
        """Parse ``<ID=X,Number=1,Type=String,Description=\"...\">`` blocks."""
        text = blob.strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1]
        result: Dict[str, str] = {}
        # Split on commas not inside quotes
        tokens: List[str] = []
        buf: List[str] = []
        in_quotes = False
        for ch in text:
            if ch == '"':
                in_quotes = not in_quotes
                buf.append(ch)
            elif ch == "," and not in_quotes:
                tokens.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        if buf:
            tokens.append("".join(buf))
        for token in tokens:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            result[key] = value.strip().strip('"')
        return result

    def _ingest_column_header(self, line: str) -> None:
        cols = line.lstrip("#").split("\t")
        self._column_names = cols
        if len(cols) > 9:
            self.header.sample_names = cols[9:]
        else:
            self.header.sample_names = []

    def _parse_data_line(self, line: str) -> VariantRecord:
        fields = line.split("\t")
        if len(fields) < 8:
            raise VCFParseError(f"expected ≥8 columns, got {len(fields)}")
        chrom, pos_s, vid, ref, alt_s, qual_s, filt_s, info_s = fields[:8]
        try:
            pos = int(pos_s)
        except ValueError as exc:
            raise VCFParseError(f"invalid POS {pos_s!r}") from exc
        if not ref or ref == ".":
            raise VCFParseError("REF allele missing")
        alts = [a for a in alt_s.split(",") if a and a != "."]
        qual: Optional[float]
        if qual_s in {".", ""}:
            qual = None
        else:
            try:
                qual = float(qual_s)
            except ValueError as exc:
                raise VCFParseError(f"invalid QUAL {qual_s!r}") from exc
        filters = [] if filt_s in {".", "PASS", ""} else filt_s.split(";")
        if filt_s == "PASS":
            filters = ["PASS"]
        info = _split_info(info_s)
        format_keys: List[str] = []
        samples: Dict[str, Dict[str, str]] = {}
        if len(fields) >= 10 and len(self.header.sample_names) >= 1:
            format_keys = fields[8].split(":")
            for sample_name, sample_blob in zip(self.header.sample_names, fields[9:]):
                parts = sample_blob.split(":")
                samples[sample_name] = {
                    key: parts[i] if i < len(parts) else "."
                    for i, key in enumerate(format_keys)
                }
        gene, raw_csq, consequence = self._extract_annotation(info)
        annotation_source = "info" if (gene or raw_csq) else "none"
        return VariantRecord(
            chrom=chrom,
            pos=pos,
            variant_id=vid if vid != "." else f"{chrom}_{pos}_{ref}_{alts[0] if alts else 'NA'}",
            ref=ref,
            alt=alts,
            qual=qual,
            filter_status=filters,
            info=info,
            format_keys=format_keys,
            samples=samples,
            gene=gene,
            consequence=consequence,
            raw_consequence=raw_csq,
            annotation_source=annotation_source,
        )

    def _extract_annotation(
        self, info: Mapping[str, Any]
    ) -> Tuple[Optional[str], Optional[str], VariantConsequence]:
        gene: Optional[str] = None
        for key in ("GENE", "Gene", "SYMBOL", "gene", "Gene.refGene", "Gene.ensGene"):
            if key in info:
                raw = info[key]
                gene = raw[0] if isinstance(raw, list) else str(raw)
                break

        raw_csq: Optional[str] = None
        for key in ("Consequence", "consequence", "EFFECT", "Effect", "Func.refGene"):
            if key in info:
                raw = info[key]
                raw_csq = raw[0] if isinstance(raw, list) else str(raw)
                break

        # VEP ANN: Allele|Consequence|IMPACT|SYMBOL|...
        if "ANN" in info and raw_csq is None:
            ann = info["ANN"]
            first = ann[0] if isinstance(ann, list) else str(ann)
            parts = str(first).split("|")
            if len(parts) > 1:
                raw_csq = parts[1]
            if gene is None and len(parts) > 3 and parts[3]:
                gene = parts[3]

        # VEP CSQ requires header order; best-effort: look for known tokens.
        if "CSQ" in info and raw_csq is None:
            csq = info["CSQ"]
            first = csq[0] if isinstance(csq, list) else str(csq)
            parts = str(first).split("|")
            for part in parts:
                norm = normalize_consequence(part)
                if norm is not VariantConsequence.UNKNOWN:
                    raw_csq = part
                    break
            if gene is None:
                for part in parts:
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9Flash.-]{1,20}", part or ""):
                        # Heuristic gene symbol candidate
                        if part.upper() != part or len(part) <= 15:
                            gene = part
                            break

        consequence = normalize_consequence(raw_csq or "")
        return gene, raw_csq, consequence


def variants_to_mutations(
    variants: Sequence[VariantRecord],
    gene_to_entity_id: Mapping[str, str],
    *,
    t_start: float = 0.0,
    missense_rate_scale: float = 0.5,
    include_filtered: bool = False,
) -> List[Mutation]:
    """
    Map parsed VCF records onto Phase 1 :class:`~voidsignal.perturbation.Mutation`
    objects using gene-symbol → ``entity_id`` resolution.

    Parameters
    ----------
    gene_to_entity_id :
        Case-sensitive map of gene / protein symbols present in the simulation
        network. Lookup also tries upper-case keys.
    missense_rate_scale :
        Overrides the default hypomorph scale for missense variants.
    include_filtered :
        If False (default), skip records whose FILTER is set and not PASS.
    """
    mutations: List[Mutation] = []
    for variant in variants:
        if not include_filtered:
            if variant.filter_status and variant.filter_status != ["PASS"]:
                if "PASS" not in variant.filter_status:
                    logger.debug("Skipping filtered variant %s (%s)", variant.key(), variant.filter_status)
                    continue
        if not variant.gene:
            logger.debug("Skipping variant %s — no gene annotation", variant.key())
            continue
        entity_id = gene_to_entity_id.get(variant.gene) or gene_to_entity_id.get(variant.gene.upper())
        if entity_id is None:
            logger.info(
                "Variant %s gene %s not in simulation network — skipped",
                variant.key(),
                variant.gene,
            )
            continue
        mapping = consequence_to_mapping(variant.consequence)
        if mapping.skip:
            logger.debug(
                "Variant %s consequence %s is non-coding/silent for simulation — skipped",
                variant.key(),
                variant.consequence.value,
            )
            continue
        rate_scale = (
            missense_rate_scale
            if variant.consequence is VariantConsequence.MISSENSE
            else mapping.rate_scale
        )
        mut = Mutation(
            target_id=entity_id,
            kind=mapping.kind,
            name=f"vcf:{variant.key()}:{variant.consequence.value}",
            expression_level=mapping.expression_level,
            rate_scale=rate_scale,
            permanent_lock=mapping.permanent_lock,
            t_start=t_start,
        )
        mutations.append(mut)
    return mutations


# ---------------------------------------------------------------------------
# FASTA
# ---------------------------------------------------------------------------


@dataclass
class FastaRecord:
    """One FASTA sequence entry."""

    header: str
    sequence: str

    @property
    def identifier(self) -> str:
        return self.header.split()[0] if self.header else ""

    @property
    def length(self) -> int:
        return len(self.sequence)

    def gc_content(self) -> float:
        if not self.sequence:
            return 0.0
        seq = self.sequence.upper()
        gc = seq.count("G") + seq.count("C")
        atgc = gc + seq.count("A") + seq.count("T")
        return gc / atgc if atgc else 0.0


class FASTAParser:
    """Streaming FASTA reader supporting multi-line sequence blocks."""

    def __init__(self, path: PathLike) -> None:
        self.path = Path(path)

    def parse(self) -> List[FastaRecord]:
        return list(self.iter_records())

    def iter_records(self) -> Iterator[FastaRecord]:
        header: Optional[str] = None
        chunks: List[str] = []
        with open_text(self.path) as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    if header is not None:
                        yield FastaRecord(header=header, sequence="".join(chunks).upper())
                    header = line[1:].strip()
                    chunks = []
                else:
                    if header is None:
                        raise ValueError(f"FASTA sequence data before header at line {line_no}")
                    chunks.append(re.sub(r"\s+", "", line))
            if header is not None:
                yield FastaRecord(header=header, sequence="".join(chunks).upper())

    def as_dict(self) -> Dict[str, FastaRecord]:
        return {rec.identifier: rec for rec in self.iter_records()}


# ---------------------------------------------------------------------------
# GFF / GTF
# ---------------------------------------------------------------------------


@dataclass
class GenomicFeature:
    """One GFF3 / GTF feature row."""

    seqid: str
    source: str
    feature_type: str
    start: int
    end: int
    score: Optional[float]
    strand: str
    phase: Optional[int]
    attributes: Dict[str, str]
    frame_format: str = "gff3"

    @property
    def length(self) -> int:
        return max(0, self.end - self.start + 1)

    def attribute(self, *keys: str, default: Optional[str] = None) -> Optional[str]:
        for key in keys:
            if key in self.attributes:
                return self.attributes[key]
        return default

    @property
    def gene_name(self) -> Optional[str]:
        return self.attribute("gene_name", "Name", "gene", "gene_id")


class GFFParser:
    """
    GFF3 / GTF feature parser.

    Attributes are split on ``;`` with GFF3 ``key=value`` or GTF
    ``key "value"`` syntax auto-detected per file.
    """

    def __init__(self, path: PathLike) -> None:
        self.path = Path(path)

    def parse(self) -> List[GenomicFeature]:
        return list(self.iter_features())

    def iter_features(self) -> Iterator[GenomicFeature]:
        with open_text(self.path) as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 9:
                    logger.warning("Skipping malformed GFF line %s (%d columns)", line_no, len(parts))
                    continue
                seqid, source, ftype, start_s, end_s, score_s, strand, phase_s, attr_s = parts[:9]
                try:
                    start = int(start_s)
                    end = int(end_s)
                except ValueError:
                    logger.warning("Skipping GFF line %s — bad coordinates", line_no)
                    continue
                if end < start:
                    start, end = end, start
                score: Optional[float]
                if score_s in {".", ""}:
                    score = None
                else:
                    try:
                        score = float(score_s)
                    except ValueError:
                        score = None
                phase: Optional[int]
                if phase_s in {".", ""}:
                    phase = None
                else:
                    try:
                        phase = int(phase_s)
                    except ValueError:
                        phase = None
                attributes, fmt = self._parse_attributes(attr_s)
                yield GenomicFeature(
                    seqid=seqid,
                    source=source,
                    feature_type=ftype,
                    start=start,
                    end=end,
                    score=score,
                    strand=strand if strand in {"+", "-", "."} else ".",
                    phase=phase,
                    attributes=attributes,
                    frame_format=fmt,
                )

    @staticmethod
    def _parse_attributes(blob: str) -> Tuple[Dict[str, str], str]:
        attrs: Dict[str, str] = {}
        text = blob.strip().rstrip(";")
        if not text or text == ".":
            return attrs, "gff3"
        # GTF-style: gene_id "X"; transcript_id "Y";
        if re.search(r'\w+\s+"[^"]*"', text):
            for match in re.finditer(r'(\w+)\s+"([^"]*)"', text):
                attrs[match.group(1)] = match.group(2)
            return attrs, "gtf"
        # GFF3-style: ID=x;Name=y
        for token in text.split(";"):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                key, value = token.split("=", 1)
                attrs[key.strip()] = value.strip()
            else:
                attrs[token] = "true"
        return attrs, "gff3"

    def features_by_type(self, feature_type: str) -> List[GenomicFeature]:
        return [f for f in self.iter_features() if f.feature_type == feature_type]

    def gene_spans(self) -> Dict[str, GenomicFeature]:
        """Return gene_name → feature for rows typed ``gene`` / ``mRNA`` preference."""
        result: Dict[str, GenomicFeature] = {}
        for feat in self.iter_features():
            if feat.feature_type not in {"gene", "mRNA", "transcript"}:
                continue
            name = feat.gene_name
            if not name:
                continue
            if name not in result or feat.feature_type == "gene":
                result[name] = feat
        return result


# ---------------------------------------------------------------------------
# BED
# ---------------------------------------------------------------------------


@dataclass
class BedInterval:
    """UCSC BED interval (BED3 minimum; optional thick/block fields retained)."""

    chrom: str
    start: int
    end: int
    name: Optional[str] = None
    score: Optional[float] = None
    strand: Optional[str] = None
    extra: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"BED end ({self.end}) < start ({self.start})")
        if self.start < 0:
            raise ValueError("BED start must be ≥ 0 (0-based half-open)")

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "BedInterval") -> bool:
        if self.chrom != other.chrom:
            return False
        return self.start < other.end and other.start < self.end


class BEDParser:
    """
    BED parser (BED3–BED12 subset).

    Coordinates are kept in native 0-based half-open form. Use
    :meth:`to_gff_coords` when intersecting with 1-based GFF features.
    """

    def __init__(self, path: PathLike) -> None:
        self.path = Path(path)

    def parse(self) -> List[BedInterval]:
        return list(self.iter_intervals())

    def iter_intervals(self) -> Iterator[BedInterval]:
        with open_text(self.path) as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line or line.startswith(("#", "track", "browser")):
                    continue
                parts = re.split(r"\s+", line)
                if len(parts) < 3:
                    logger.warning("Skipping malformed BED line %s", line_no)
                    continue
                chrom = parts[0]
                try:
                    start = int(parts[1])
                    end = int(parts[2])
                except ValueError:
                    logger.warning("Skipping BED line %s — bad coordinates", line_no)
                    continue
                name = parts[3] if len(parts) > 3 else None
                score: Optional[float] = None
                if len(parts) > 4 and parts[4] not in {".", ""}:
                    try:
                        score = float(parts[4])
                    except ValueError:
                        score = None
                strand = parts[5] if len(parts) > 5 else None
                extra = parts[6:] if len(parts) > 6 else []
                try:
                    yield BedInterval(
                        chrom=chrom,
                        start=start,
                        end=end,
                        name=name,
                        score=score,
                        strand=strand,
                        extra=extra,
                    )
                except ValueError as exc:
                    logger.warning("Skipping BED line %s: %s", line_no, exc)

    def named_intervals(self) -> Dict[str, BedInterval]:
        result: Dict[str, BedInterval] = {}
        for interval in self.iter_intervals():
            if interval.name:
                result[interval.name] = interval
        return result


def link_sequence_lengths(
    fasta: Mapping[str, FastaRecord],
    features: Sequence[GenomicFeature],
    *,
    id_keys: Sequence[str] = ("protein_id", "Name", "gene_name", "ID"),
) -> Dict[str, int]:
    """
    Build ``feature_id → amino-acid/nucleotide length`` by matching FASTA
    identifiers to GFF attributes — consumed by the ETL layer when seeding
    :class:`~voidsignal.components.Protein.sequence_length`.
    """
    lengths: Dict[str, int] = {}
    fasta_index = {k: v.length for k, v in fasta.items()}
    # Also index by stripped versions (UniProt style sp|P04637|P53_HUMAN)
    for key, rec in fasta.items():
        for piece in re.split(r"[|:\s]", key):
            if piece:
                fasta_index.setdefault(piece, rec.length)
    for feat in features:
        for key in id_keys:
            value = feat.attributes.get(key)
            if value and value in fasta_index:
                lengths[value] = fasta_index[value]
                break
        else:
            # Fall back to genomic span length
            name = feat.gene_name or feat.attributes.get("ID")
            if name:
                lengths.setdefault(name, feat.length)
    return lengths


GeneResolver = Callable[[str], Optional[str]]
