"""Offline fallback corpora for DepMap / ENCODE / UniProt enrichment."""

from __future__ import annotations

from typing import Any, Dict, List


OFFLINE_UNIPROT: Dict[str, Dict[str, Any]] = {
    "EGFR": {
        "accession": "P00533",
        "gene_symbol": "EGFR",
        "full_name": "Epidermal growth factor receptor",
        "organism": "Homo sapiens",
        "function": "Receptor tyrosine kinase binding EGF family ligands.",
        "domains": [{"name": "Protein kinase", "start": 712, "end": 979}],
        "ptm_sites": [{"residue": "Tyr1068", "modification": "phosphorylation"}],
        "localization": "Plasma Membrane",
        "pdb_ids": ["1M17", "5WB7"],
        "alphafold_url": "https://alphafold.ebi.ac.uk/entry/P00533",
        "diseases": ["NSCLC", "glioblastoma"],
        "mutations": ["EGFR p.L858R"],
    },
    "KRAS": {
        "accession": "P01116",
        "gene_symbol": "KRAS",
        "full_name": "GTPase KRas",
        "organism": "Homo sapiens",
        "function": "GTPase transmitting RTK signals to RAF / PI3K.",
        "domains": [{"name": "G domain", "start": 1, "end": 166}],
        "ptm_sites": [],
        "localization": "Plasma Membrane",
        "pdb_ids": ["4OBE"],
        "alphafold_url": "https://alphafold.ebi.ac.uk/entry/P01116",
        "diseases": ["CRC", "PDAC", "NSCLC"],
        "mutations": ["KRAS p.G12D", "KRAS p.G12C"],
    },
    "TP53": {
        "accession": "P04637",
        "gene_symbol": "TP53",
        "full_name": "Cellular tumor antigen p53",
        "organism": "Homo sapiens",
        "function": "Tumor suppressor and transcription factor.",
        "domains": [{"name": "DNA-binding", "start": 95, "end": 289}],
        "ptm_sites": [{"residue": "Ser15", "modification": "phosphorylation"}],
        "localization": "Nucleus",
        "pdb_ids": ["1TUP"],
        "alphafold_url": "https://alphafold.ebi.ac.uk/entry/P04637",
        "diseases": ["Li-Fraumeni"],
        "mutations": ["TP53 p.R175H", "TP53 p.R213*"],
    },
    "MAP2K1": {
        "accession": "Q02750",
        "gene_symbol": "MAP2K1",
        "full_name": "Dual specificity mitogen-activated protein kinase kinase 1",
        "organism": "Homo sapiens",
        "function": "MEK1 dual-specificity kinase activating ERK.",
        "domains": [{"name": "Protein kinase", "start": 68, "end": 369}],
        "ptm_sites": [{"residue": "Ser218", "modification": "phosphorylation"}],
        "localization": "Cytosol",
        "pdb_ids": ["3EQC"],
        "alphafold_url": "https://alphafold.ebi.ac.uk/entry/Q02750",
        "diseases": [],
        "mutations": [],
    },
    "AKT1": {
        "accession": "P31749",
        "gene_symbol": "AKT1",
        "full_name": "RAC-alpha serine/threonine-protein kinase",
        "organism": "Homo sapiens",
        "function": "PI3K effector controlling survival and metabolism.",
        "domains": [{"name": "Protein kinase", "start": 150, "end": 408}],
        "ptm_sites": [{"residue": "Ser473", "modification": "phosphorylation"}],
        "localization": "Cytosol",
        "pdb_ids": ["3O96"],
        "alphafold_url": "https://alphafold.ebi.ac.uk/entry/P31749",
        "diseases": [],
        "mutations": [],
    },
}


# Chronos-like gene effect scores (more negative ⇒ more essential)
OFFLINE_DEPMAP: Dict[str, Dict[str, Any]] = {
    "KRAS": {"gene_effect": -1.42, "dependency_prob": 0.96, "lineage": "pan-cancer"},
    "MYC": {"gene_effect": -1.55, "dependency_prob": 0.98, "lineage": "pan-cancer"},
    "EGFR": {"gene_effect": -0.65, "dependency_prob": 0.55, "lineage": "lung"},
    "TP53": {"gene_effect": -0.12, "dependency_prob": 0.08, "lineage": "pan-cancer"},
    "BRAF": {"gene_effect": -0.88, "dependency_prob": 0.72, "lineage": "melanoma"},
    "PIK3CA": {"gene_effect": -0.71, "dependency_prob": 0.61, "lineage": "breast"},
    "MAP2K1": {"gene_effect": -0.54, "dependency_prob": 0.48, "lineage": "pan-cancer"},
    "AKT1": {"gene_effect": -0.49, "dependency_prob": 0.42, "lineage": "pan-cancer"},
}


OFFLINE_ENCODE: Dict[str, Dict[str, Any]] = {
    "TP53": {"chromatin_state": "Active TSS", "cell_type": "HepG2", "assay": "ChromHMM"},
    "MYC": {"chromatin_state": "Strong enhancer", "cell_type": "K562", "assay": "ChromHMM"},
    "EGFR": {"chromatin_state": "Flanking TSS", "cell_type": "A549", "assay": "ChromHMM"},
    "KRAS": {"chromatin_state": "Quiescent/low", "cell_type": "GM12878", "assay": "ChromHMM"},
}


# Minimal directed edges for offline pathway scaffolds (symbol → symbol, type)
OFFLINE_PATHWAY_EDGES: Dict[str, List[Dict[str, str]]] = {
    "hsa04010": [
        {"source": "EGF", "target": "EGFR", "type": "activation"},
        {"source": "EGFR", "target": "KRAS", "type": "activation"},
        {"source": "KRAS", "target": "BRAF", "type": "activation"},
        {"source": "BRAF", "target": "MAP2K1", "type": "phosphorylation"},
        {"source": "MAP2K1", "target": "MAPK1", "type": "phosphorylation"},
    ],
    "hsa04151": [
        {"source": "EGFR", "target": "PIK3CA", "type": "activation"},
        {"source": "KRAS", "target": "PIK3CA", "type": "activation"},
        {"source": "PIK3CA", "target": "AKT1", "type": "activation"},
        {"source": "AKT1", "target": "MTOR", "type": "activation"},
        {"source": "PTEN", "target": "PIK3CA", "type": "inhibition"},
    ],
    "hsa04630": [
        {"source": "IL6R", "target": "JAK2", "type": "activation"},
        {"source": "JAK2", "target": "STAT3", "type": "phosphorylation"},
        {"source": "STAT3", "target": "TP53", "type": "activation"},
    ],
    "hsa04115": [
        {"source": "ATM", "target": "TP53", "type": "phosphorylation"},
        {"source": "TP53", "target": "CDKN1A", "type": "transcription"},
        {"source": "MDM2", "target": "TP53", "type": "inhibition"},
    ],
}
