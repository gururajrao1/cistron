"""
CSV ingest for Phase 2 omics profiles.

Normalizes heterogeneous differential-expression headers (DESeq2, edgeR,
Proteome Discoverer exports, etc.) into :class:`~cistron.models.omics.OmicsProfile`.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from typing import Dict, List, Mapping, Optional, Union

from cistron.models.omics import OmicsFeature, OmicsProfile

logger = logging.getLogger(__name__)

# Accepted identity columns after ``k.strip().lower()``.
_SYMBOL_KEYS = (
    "symbol",
    "gene",
    "protein",
    "gene_symbol",
    "gene_name",
    "target",
    "id",
)

# Accepted effect-size columns after ``k.strip().lower()`` (also matched
# with underscores / spaces removed, e.g. log2FoldChange → log2foldchange).
_LOG2FC_KEYS = (
    "log2foldchange",
    "log2fc",
    "logfc",
    "fold_change",
    "log2_fc",
)

_PVALUE_KEYS = (
    "pvalue",
    "p_value",
    "pval",
    "padj",
    "p_adj",
    "fdr",
    "qvalue",
    "q_value",
)

_UNIPROT_KEYS = ("uniprot", "uniprot_id", "accession", "protein_id")
_ENSEMBL_KEYS = ("ensembl", "ensembl_id", "ensembl_gene_id", "gene_id")
_EXPRESSION_KEYS = (
    "expression",
    "expression_level",
    "tpm",
    "fpkm",
    "rpkm",
    "counts",
    "basemean",
    "base_mean",
)


def _strip_bom(value: str) -> str:
    """Remove a leading UTF-8 BOM (``\\ufeff``) and surrounding whitespace."""
    return str(value).lstrip("\ufeff").strip()


def _norm_key(name: object) -> str:
    """Lowercase + strip BOM/whitespace for header / row key matching."""
    return _strip_bom(str(name) if name is not None else "").lower()


def _compact_key(name: str) -> str:
    """Drop separators so ``log2_fc`` / ``log2FoldChange`` / ``Log2 FC`` collide."""
    return (
        _norm_key(name)
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
    )


def _normalize_row(row: Mapping[str, object]) -> Dict[str, str]:
    """
    Rebuild a DictReader row with lowercase stripped keys.

    Values are coerced to stripped strings. Duplicate normalized keys keep
    the first non-empty value.
    """
    out: Dict[str, str] = {}
    for raw_key, raw_val in row.items():
        if raw_key is None:
            continue
        key = _norm_key(raw_key)
        if not key:
            continue
        val = "" if raw_val is None else str(raw_val).strip()
        if key not in out or (not out[key] and val):
            out[key] = val
        # Also index the compact form for alias lookup.
        compact = _compact_key(raw_key)
        if compact and (compact not in out or (not out[compact] and val)):
            out[compact] = val
    return out


def _pick(row: Mapping[str, str], candidates: tuple[str, ...]) -> str:
    """Return the first non-empty cell matching any candidate key."""
    for cand in candidates:
        # Exact normalized match.
        if cand in row and row[cand]:
            return row[cand]
        # Compact match (log2foldchange ↔ log2_fold_change).
        compact = _compact_key(cand)
        if compact in row and row[compact]:
            return row[compact]
    return ""


def _parse_float(raw: str) -> Optional[float]:
    if not raw or raw.lower() in {"na", "nan", "none", ".", "-"}:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    if v != v:  # NaN
        return None
    return float(v)


def _decode_content(file_content: Union[str, bytes]) -> str:
    if isinstance(file_content, bytes):
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return file_content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return file_content.decode("utf-8", errors="replace")
    # String payloads may still carry a BOM from some editors.
    return _strip_bom(str(file_content))


def parse_omics_csv(
    file_content: Union[str, bytes],
    sample_name: str,
    condition: str,
) -> OmicsProfile:
    """
    Parse a differential-omics CSV/TSV blob into an :class:`OmicsProfile`.

    Headers are BOM-stripped and lowercased (``Symbol`` → ``symbol``,
    ``log2FoldChange`` → ``log2foldchange``). Rows are rebuilt the same way
    before alias lookup. Gene symbols are uppercased before insertion into
    ``features``.

    Parameters
    ----------
    file_content:
        Raw CSV or TSV text / bytes.
    sample_name:
        Sample or cohort label stored on the profile.
    condition:
        Biological condition label (e.g. ``\"hypoxia\"``).

    Returns
    -------
    OmicsProfile
        Features keyed by uppercase gene symbol (last row wins on duplicates).
    """
    text = _decode_content(file_content).strip()
    if not text:
        raise ValueError("omics CSV content is empty")

    # Sniff delimiter from the header line (comma vs tab).
    sample_line = text.splitlines()[0]
    try:
        dialect = csv.Sniffer().sniff(sample_line, delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if sample_line.count("\t") > sample_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("omics CSV has no header row")

    # Normalize headers up-front (BOM + case + whitespace).
    normalized_fields: List[str] = [_norm_key(h) for h in reader.fieldnames if h is not None]
    if not any(f for f in normalized_fields):
        raise ValueError("omics CSV has no usable header columns")

    # Probe first data rows via normalized keys to confirm required columns exist.
    peek_ok_symbol = any(
        f in _SYMBOL_KEYS or _compact_key(f) in {_compact_key(k) for k in _SYMBOL_KEYS}
        for f in normalized_fields
    )
    peek_ok_lfc = any(
        f in _LOG2FC_KEYS or _compact_key(f) in {_compact_key(k) for k in _LOG2FC_KEYS}
        for f in normalized_fields
    )
    if not peek_ok_symbol:
        raise ValueError(
            "omics CSV missing gene symbol column "
            f"(expected one of: {', '.join(_SYMBOL_KEYS)})"
        )
    if not peek_ok_lfc:
        raise ValueError(
            "omics CSV missing log2 fold-change column "
            f"(expected one of: {', '.join(_LOG2FC_KEYS)})"
        )

    features: Dict[str, OmicsFeature] = {}
    skipped = 0

    for raw_row in reader:
        if not raw_row:
            continue
        row = _normalize_row(raw_row)

        symbol_raw = _pick(row, _SYMBOL_KEYS)
        lfc_raw = _pick(row, _LOG2FC_KEYS)
        if not symbol_raw or not lfc_raw:
            skipped += 1
            continue

        symbol = symbol_raw.strip().upper()
        if not symbol or symbol in {"NA", "N/A", "NONE", ".", "-"}:
            skipped += 1
            continue
        # Collapse multi-gene aggregates to the first token.
        if ";" in symbol or "," in symbol:
            symbol = symbol.split(";")[0].split(",")[0].strip().upper()
            if not symbol:
                skipped += 1
                continue

        lfc = _parse_float(lfc_raw)
        if lfc is None:
            skipped += 1
            continue

        p_raw = _parse_float(_pick(row, _PVALUE_KEYS))
        p_value: Optional[float] = None
        if p_raw is not None:
            p_value = min(1.0, max(0.0, p_raw))

        uniprot = _pick(row, _UNIPROT_KEYS) or None
        ensembl = _pick(row, _ENSEMBL_KEYS) or None
        expr = _parse_float(_pick(row, _EXPRESSION_KEYS))

        try:
            features[symbol] = OmicsFeature(
                symbol=symbol,
                uniprot_id=uniprot,
                ensembl_id=ensembl,
                log2_fc=lfc,
                p_value=p_value,
                expression_level=expr,
            )
        except Exception as exc:  # noqa: BLE001 — skip malformed rows
            skipped += 1
            logger.debug("Skipping omics row %s: %s", symbol, exc)

    if not features:
        raise ValueError("omics CSV produced zero valid features")

    if skipped:
        logger.debug("Omics parse skipped %d invalid/empty rows", skipped)

    return OmicsProfile(
        profile_id=f"omics_{uuid.uuid4().hex[:12]}",
        sample_name=sample_name,
        condition=condition,
        features=features,
    )


__all__ = ["parse_omics_csv"]
