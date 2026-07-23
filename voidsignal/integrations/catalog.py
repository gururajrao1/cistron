"""Human pathway catalog for the Virtual Cellular Laboratory dropdown."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PathwayCatalogEntry:
    """One selectable human signalling pathway."""

    pathway_id: str
    """Primary ID (KEGG ``hsa#####`` or Reactome ``R-HSA-…``)."""
    name: str
    domain: str
    """High-level lab domain tag."""
    source: str
    """``kegg`` | ``reactome`` | ``synthetic``."""
    aliases: Tuple[str, ...] = ()
    hub_genes: Tuple[str, ...] = ()
    description: str = ""
    kegg_id: Optional[str] = None
    reactome_id: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "pathway_id": self.pathway_id,
            "name": self.name,
            "domain": self.domain,
            "source": self.source,
            "aliases": list(self.aliases),
            "hub_genes": list(self.hub_genes),
            "description": self.description,
            "kegg_id": self.kegg_id,
            "reactome_id": self.reactome_id,
        }


HUMAN_PATHWAY_CATALOG: Tuple[PathwayCatalogEntry, ...] = (
    PathwayCatalogEntry(
        "hsa04010",
        "MAPK signaling pathway",
        "Pathways",
        "kegg",
        ("mapk", "MAPK", "Erk"),
        ("EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1"),
        "Classical RTK → RAS → RAF → MEK → ERK cascade.",
        kegg_id="hsa04010",
        reactome_id="R-HSA-5683057",
    ),
    PathwayCatalogEntry(
        "hsa04151",
        "PI3K-Akt signaling pathway",
        "Pathways",
        "kegg",
        ("pi3k", "PI3K-Akt", "akt"),
        ("EGFR", "PIK3CA", "AKT1", "PTEN", "MTOR"),
        "Survival / growth signalling via PIP3 and AKT.",
        kegg_id="hsa04151",
        reactome_id="R-HSA-2219528",
    ),
    PathwayCatalogEntry(
        "hsa04115",
        "p53 signaling pathway",
        "Pathways",
        "kegg",
        ("p53", "TP53"),
        ("TP53", "MDM2", "CDKN1A", "BAX"),
        "Genome integrity and apoptosis gatekeeping.",
        kegg_id="hsa04115",
    ),
    PathwayCatalogEntry(
        "hsa04210",
        "Apoptosis",
        "Pathways",
        "kegg",
        ("apoptosis",),
        ("CASP3", "CASP8", "BCL2", "BAX", "TP53"),
        "Intrinsic / extrinsic programmed cell death.",
        kegg_id="hsa04210",
    ),
    PathwayCatalogEntry(
        "hsa04064",
        "NF-kappa B signaling pathway",
        "Pathways",
        "kegg",
        ("nfkb", "NF-kB", "NFkB"),
        ("RELA", "NFKB1", "IKBKB", "TNF"),
        "Inflammatory transcription via RelA/p50.",
        kegg_id="hsa04064",
    ),
    PathwayCatalogEntry(
        "hsa04630",
        "JAK-STAT signaling pathway",
        "Pathways",
        "kegg",
        ("jak-stat", "JAK", "STAT"),
        ("JAK1", "JAK2", "STAT3", "STAT1", "IL6R"),
        "Cytokine receptor → JAK → STAT transcription.",
        kegg_id="hsa04630",
    ),
    PathwayCatalogEntry(
        "hsa04310",
        "Wnt signaling pathway",
        "Pathways",
        "kegg",
        ("wnt",),
        ("CTNNB1", "APC", "GSK3B", "WNT3A"),
        "β-catenin dependent developmental signalling.",
        kegg_id="hsa04310",
    ),
    PathwayCatalogEntry(
        "hsa04350",
        "TGF-beta signaling pathway",
        "Pathways",
        "kegg",
        ("tgf", "TGF-beta", "TGFb"),
        ("TGFB1", "SMAD2", "SMAD3", "SMAD4"),
        "SMAD-mediated growth inhibition / EMT.",
        kegg_id="hsa04350",
    ),
    PathwayCatalogEntry(
        "hsa04150",
        "mTOR signaling pathway",
        "Pathways",
        "kegg",
        ("mtor",),
        ("MTOR", "RPTOR", "RPS6KB1", "EIF4EBP1"),
        "Nutrient sensing and translational control.",
        kegg_id="hsa04150",
    ),
    PathwayCatalogEntry(
        "hsa04330",
        "Notch signaling pathway",
        "Pathways",
        "kegg",
        ("notch",),
        ("NOTCH1", "DLL1", "JAG1", "RBPJ"),
        "Contact-dependent lateral inhibition.",
        kegg_id="hsa04330",
    ),
    PathwayCatalogEntry(
        "hsa04014",
        "Ras signaling pathway",
        "Pathways",
        "kegg",
        ("ras",),
        ("KRAS", "HRAS", "NRAS", "RAF1"),
        "GTPase hub linking RTKs to MAPK / PI3K.",
        kegg_id="hsa04014",
    ),
    PathwayCatalogEntry(
        "hsa01521",
        "EGFR tyrosine kinase inhibitor resistance",
        "Pathways",
        "kegg",
        ("egfr-resistance", "TKI"),
        ("EGFR", "MET", "ERBB2", "KRAS"),
        "Adaptive bypass under EGFR TKI pressure.",
        kegg_id="hsa01521",
    ),
    PathwayCatalogEntry(
        "crosstalk_multi",
        "Multi-Pathway Crosstalk (MAPK + PI3K-AKT + JAK-STAT)",
        "Pathways",
        "synthetic",
        ("crosstalk", "multi"),
        ("EGFR", "KRAS", "TP53"),
        "Merged laboratory scaffold with glowing shared hubs.",
    ),
    # Domain stubs for 20-domain lab navigation (offline metadata)
    PathwayCatalogEntry(
        "domain:structural",
        "Structural biology (PDB / AlphaFold)",
        "Structural",
        "synthetic",
        ("structure", "pdb", "alphafold"),
        ("EGFR", "MAP2K1"),
        "Pocket docking and pLDDT enrichment domain.",
    ),
    PathwayCatalogEntry(
        "domain:crispr",
        "CRISPR essentiality (DepMap)",
        "CRISPR/Essentiality",
        "synthetic",
        ("depmap", "crispr"),
        ("KRAS", "MYC", "TP53"),
        "Gene-effect / Chronos essentiality overlays.",
    ),
    PathwayCatalogEntry(
        "domain:epigenomics",
        "Epigenomics (ENCODE chromatin)",
        "Epigenomics",
        "synthetic",
        ("encode", "chromatin"),
        ("TP53", "MYC"),
        "Promoter / enhancer chromatin state priors.",
    ),
    PathwayCatalogEntry(
        "domain:multiomics",
        "Multi-omics FBA / PTM / splicing",
        "Multi-Omics",
        "synthetic",
        ("omics", "fba", "ptm"),
        ("AKT1", "MTOR"),
        "Coupled metabolic / PTM laboratory layer.",
    ),
    PathwayCatalogEntry(
        "domain:immuno",
        "Immuno-oncology / TME",
        "Immuno-Oncology",
        "synthetic",
        ("immuno", "tme", "neoantigen"),
        ("PDCD1", "CD274", "HLA-A"),
        "Checkpoint and neoantigen experiment domain.",
    ),
    PathwayCatalogEntry(
        "domain:tox",
        "Toxicology safety panel",
        "Toxicology",
        "synthetic",
        ("tox", "safety"),
        ("CYP3A4", "HERG"),
        "Adverse-event monitoring domain.",
    ),
    PathwayCatalogEntry(
        "domain:evo",
        "Evolutionary conservation",
        "Evolutionary Bio",
        "synthetic",
        ("evolution", "conservation"),
        ("TP53", "KRAS"),
        "Cross-species conservation priors.",
    ),
)


def list_pathway_catalog(*, domain: Optional[str] = None) -> List[PathwayCatalogEntry]:
    """Return catalog entries, optionally filtered by domain label."""
    if domain is None:
        return list(HUMAN_PATHWAY_CATALOG)
    d = domain.strip().lower()
    return [e for e in HUMAN_PATHWAY_CATALOG if e.domain.lower() == d or d in e.domain.lower()]


def resolve_pathway_ids(selectors: Sequence[str]) -> List[PathwayCatalogEntry]:
    """
    Resolve UI / CLI selectors (IDs, aliases, names) to catalog entries.

    Unknown selectors are skipped (never raise) so the lab stays resilient.
    """
    index: Dict[str, PathwayCatalogEntry] = {}
    for e in HUMAN_PATHWAY_CATALOG:
        index[e.pathway_id.lower()] = e
        index[e.name.lower()] = e
        for a in e.aliases:
            index[a.lower()] = e
        if e.kegg_id:
            index[e.kegg_id.lower()] = e
        if e.reactome_id:
            index[e.reactome_id.lower()] = e

    out: List[PathwayCatalogEntry] = []
    seen = set()
    for raw in selectors:
        key = str(raw).strip().lower()
        hit = index.get(key)
        if hit is None:
            continue
        if hit.pathway_id in seen:
            continue
        seen.add(hit.pathway_id)
        out.append(hit)
    return out
