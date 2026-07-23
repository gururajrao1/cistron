"""
CSV ingest for Phase 2 omics profiles.

Normalizes heterogeneous differential-expression headers (DESeq2, edgeR,
Proteome Discoverer exports, etc.) into :class:`~cistron.models.omics.OmicsProfile`.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from typing import Dict, Iterable, Mapping, Optional, Union

from cistron.models.omics import OmicsFeature, OmicsProfile

logger = logging.getLogger(__name__)

# Canonical field → accepted header aliases (already normalized: lower, no spaces/_/-).
_SYMBOL_ALIASES = frozenset(
    {
        "symbol",
        "gene",
        "genesymbol",
        "gene_symbol",
        "genename",
        "gene_name",
        "protein",
        "proteinname",
        "protein_name",
        "hgnc",
        "hgncsymbol",
        "name",
    }
)
_LOG2FC_ALIASES = frozenset(
    {
        "log2fc",
        "log2_fc",
        "logfc",
        "log_fc",
        "foldchange",
        "fold_change",
        "log2foldchange",
        "log2_fold_change",
        "lfc",
        "fc",
    }
)
_PVALUE_ALIASES = frozenset(
    {
        "pvalue",
        "p_value",
        "pval",
        "p",
        "padj",
        "p_adj",
        "p.adj",
        "fdr",
        "qvalue",
        "q_value",
        "adjpvalue",
        "adj_p_value",
        "adjustedpvalue",
    }
)
_UNIPROT_ALIASES = frozenset(
    {
        "uniprot",
        "uniprot_id",
        "uniprotid",
        "accession",
        "protein_id",
        "proteinid",
    }
)
_ENSEMBL_ALIASES = frozenset(
    {
        "ensembl",
        "ensembl_id",
        "ensemblid",
        "ensemblgene",
        "ensembl_gene_id",
        "gene_id",
        "geneid",
    }
)
_EXPRESSION_ALIASES = frozenset(
    {
        "expression",
        "expression_level",
        "expressionlevel",
        "tpm",
        "fpkm",
        "rpkm",
        "counts",
        "basemean",
        "base_mean",
        "abundance",
    }
)


def _normalize_header(name: str) -> str:
    """Lowercase and strip separators so ``Log2_FC`` ≡ ``log2fc``."""
    s = str(name).strip().lower()
    s = s.replace(".", "_")
    s = re.sub(r"[\s\-]+", "_", s)
    # Keep underscores for alias sets that include them; also provide compact form.
    return s


def _header_keys(fieldnames: Iterable[str]) -> Dict[str, str]:
    """
    Map normalized header → original CSV column name.

    Also indexes the compact (underscore-stripped) form so ``log2_fc`` and
    ``log2fc`` both resolve.
    """
    mapping: Dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        norm = _normalize_header(raw)
        compact = norm.replace("_", "")
        mapping.setdefault(norm, raw)
        mapping.setdefault(compact, raw)
    return mapping


def _resolve_column(
    header_map: Mapping[str, str],
    aliases: frozenset[str],
) -> Optional[str]:
    """Return the original CSV column name for the first matching alias."""
    for alias in aliases:
        norm = _normalize_header(alias)
        compact = norm.replace("_", "")
        if norm in header_map:
            return header_map[norm]
        if compact in header_map:
            return header_map[compact]
    return None


def _cell(row: Mapping[str, str], column: Optional[str]) -> str:
    if not column:
        return ""
    val = row.get(column, "")
    if val is None:
        return ""
    return str(val).strip()


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
    return str(file_content)


def parse_omics_csv(
    file_content: Union[str, bytes],
    sample_name: str,
    condition: str,
) -> OmicsProfile:
    """
    Parse a differential-omics CSV/TSV blob into an :class:`OmicsProfile`.

    Header names are normalized for case and punctuation. Accepted aliases
    include ``gene`` / ``symbol`` / ``protein`` for identifiers and
    ``log2fc`` / ``logfc`` / ``fold_change`` for effect size, plus
    ``pvalue`` / ``padj`` / ``fdr`` for significance.

    Invalid or empty rows are skipped (logged at DEBUG); at least one
    valid feature with a finite ``log2_fc`` is required.

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

    header_map = _header_keys(reader.fieldnames)
    col_symbol = _resolve_column(header_map, _SYMBOL_ALIASES)
    col_lfc = _resolve_column(header_map, _LOG2FC_ALIASES)
    col_pval = _resolve_column(header_map, _PVALUE_ALIASES)
    col_uniprot = _resolve_column(header_map, _UNIPROT_ALIASES)
    col_ensembl = _resolve_column(header_map, _ENSEMBL_ALIASES)
    col_expr = _resolve_column(header_map, _EXPRESSION_ALIASES)

    if not col_symbol:
        raise ValueError(
            "omics CSV missing gene symbol column "
            "(expected one of: gene, symbol, protein, …)"
        )
    if not col_lfc:
        raise ValueError(
            "omics CSV missing log2 fold-change column "
            "(expected one of: log2fc, logfc, fold_change, …)"
        )

    features: Dict[str, OmicsFeature] = {}
    skipped = 0

    for row in reader:
        if not row:
            continue
        symbol_raw = _cell(row, col_symbol)
        if not symbol_raw:
            skipped += 1
            continue
        symbol = symbol_raw.strip().upper()
        # Drop multi-gene aggregates / placeholders.
        if not symbol or symbol in {"NA", "N/A", "NONE", ".", "-"}:
            skipped += 1
            continue
        if ";" in symbol or "," in symbol:
            symbol = symbol.split(";")[0].split(",")[0].strip().upper()
            if not symbol:
                skipped += 1
                continue

        lfc = _parse_float(_cell(row, col_lfc))
        if lfc is None:
            skipped += 1
            continue

        p_raw = _parse_float(_cell(row, col_pval)) if col_pval else None
        # Soft-clamp out-of-range p-values rather than rejecting the row.
        p_value: Optional[float] = None
        if p_raw is not None:
            p_value = min(1.0, max(0.0, p_raw))

        uniprot = _cell(row, col_uniprot) or None
        ensembl = _cell(row, col_ensembl) or None
        expr = _parse_float(_cell(row, col_expr)) if col_expr else None

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
