"""Clinical benchmarking — multi-hit VCF ingestion & Option A pipeline helpers."""

from __future__ import annotations

from pathlib import Path

from cistron import __version__
from cistron.benchmarks.clinical_data import (
    ClinicalIngestionEngine,
    clinical_specs_to_vcf_text,
    default_expression_panel,
    default_multihit_specs,
    parse_clinical_vcf_string,
    write_expression_tsv,
    write_multihit_vcf,
)


def test_version_at_least_010() -> None:
    major, minor, *_ = __version__.split(".")
    assert int(major) >= 0
    assert int(minor) >= 10


def test_multihit_vcf_roundtrip(tmp_path: Path) -> None:
    specs = default_multihit_specs()
    assert len(specs) == 3
    text = clinical_specs_to_vcf_text(specs)
    assert "EGFR" in text and "KRAS" in text and "TP53" in text
    assert "p.L858R" in text and "p.G12D" in text and "p.R213*" in text
    records, warnings = parse_clinical_vcf_string(text)
    assert len(records) == 3
    genes = {r.gene for r in records}
    assert "EGFR" in genes and "KRAS" in genes and "TP53" in genes
    egfr = next(r for r in records if r.gene == "EGFR")
    assert egfr.info.get("HGVSp") == "p.L858R"
    assert egfr.info.get("AA_POS") in (858, "858", 858.0) or int(egfr.info.get("AA_POS", 0)) == 858


def test_clinical_ingestion_demo_baseline(tmp_path: Path) -> None:
    vcf = write_multihit_vcf(tmp_path / "case.vcf")
    expr = write_expression_tsv(tmp_path / "expr.tsv", records=default_expression_panel())
    engine = ClinicalIngestionEngine(prefer_vendored=False)
    bundle = engine.ingest(
        patient_id="TEST_CASE",
        vcf_path=vcf,
        expression=expr,
        apply_structure=True,
    )
    assert bundle.patient.n_mutations if hasattr(bundle.patient, "n_mutations") else True
    assert len(bundle.patient.applied_mutations) == 3
    assert len(bundle.patient.expression_scales) >= 3
    assert not bundle.ingestion.unresolved_genes
    assert len(bundle.ingestion.structural_hits) == 3
    assert all(h.applied for h in bundle.ingestion.structural_hits)
    # GoF EGFR / KRAS and LoF TP53
    by_gene = {h.gene: h for h in bundle.ingestion.structural_hits}
    assert any("gof" in n for n in by_gene["EGFR"].notes)
    assert by_gene["TP53"].applied and by_gene["TP53"].disruption >= 0.5


def test_vendored_baseline_loads() -> None:
    from cistron.benchmarks.clinical_data import build_clinical_baseline

    net, ids, warnings = build_clinical_baseline(prefer_vendored=True, fallback_demo=False)
    assert len(net.nodes()) >= 6
    assert "EGFR" in ids or "egfr" in {k.lower() for k in ids}
    assert "TP53" in ids
