"""UniProt enrichment client — live REST with offline gene-symbol fallbacks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import logging

from voidsignal.components import (
    ClinicalAnnotation,
    ModificationSite,
    ModificationType,
    Protein,
    ProteinDomain,
    StructuralMetadata,
)
from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.http_sync import http_get_json
from voidsignal.integrations.offline_data import OFFLINE_UNIPROT

logger = logging.getLogger(__name__)


class LabUniProtClient:
    """
    Synchronous lab-facing UniProt enrichment (zero-key REST).

    Order: disk cache → live UniProt REST → curated offline corpus.
    """

    BASE = "https://rest.uniprot.org"

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()

    def search(self, query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
        """Dynamic gene / protein search for Protein Explorer."""
        q = query.strip()
        if not q:
            return []
        cache_key = f"search:{q.lower()}:{limit}"
        cached = self.cache.get_json("uniprot_search", cache_key)
        if isinstance(cached, list):
            return list(cached)

        # Prefer exact gene matches from offline first for snappy UX
        offline_hits = []
        needle = q.upper()
        for sym, row in OFFLINE_UNIPROT.items():
            if needle in sym or needle in str(row.get("full_name", "")).upper():
                offline_hits.append(dict(row))
        if offline_hits:
            self.cache.set_json("uniprot_search", cache_key, offline_hits[:limit])
            return offline_hits[:limit]

        params = urlencode(
            {
                "query": f"(gene:{q}) AND (organism_id:9606)",
                "format": "json",
                "size": str(max(1, min(limit, 25))),
                "fields": "accession,gene_names,protein_name,organism_name,cc_subcellular_location,ft_domain,ft_mod_res",
            }
        )
        url = f"{self.BASE}/uniprotkb/search?{params}"
        payload = http_get_json(url)
        results: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            for entry in payload.get("results") or []:
                parsed = self._parse_entry(entry)
                if parsed:
                    results.append(parsed)
        if results:
            self.cache.set_json("uniprot_search", cache_key, results)
        return results

    def lookup(self, gene_symbol: str) -> Optional[Dict[str, Any]]:
        sym = gene_symbol.strip().upper()
        cached = self.cache.get_json("uniprot_lab", sym)
        if isinstance(cached, dict):
            return cached

        offline = OFFLINE_UNIPROT.get(sym) or OFFLINE_UNIPROT.get(gene_symbol.strip())
        if offline is not None:
            self.cache.set_json("uniprot_lab", sym, offline)
            return dict(offline)

        live = self._live_gene(sym)
        if live:
            self.cache.set_json("uniprot_lab", sym, live)
            return live
        return None

    def _live_gene(self, gene_symbol: str) -> Optional[Dict[str, Any]]:
        params = urlencode(
            {
                "query": f"(gene_exact:{gene_symbol}) AND (organism_id:9606)",
                "format": "json",
                "size": "1",
                "fields": "accession,gene_names,protein_name,organism_name,cc_subcellular_location,ft_domain,ft_mod_res,xref_pdb",
            }
        )
        url = f"{self.BASE}/uniprotkb/search?{params}"
        payload = http_get_json(url)
        if not isinstance(payload, dict):
            return None
        results = payload.get("results") or []
        if not results:
            return None
        return self._parse_entry(results[0])

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            accession = str(entry.get("primaryAccession") or "")
            if not accession:
                return None
            genes = entry.get("genes") or []
            gene_symbol = None
            if genes:
                gene_symbol = (genes[0].get("geneName") or {}).get("value")
            desc = entry.get("proteinDescription") or {}
            recommended = (desc.get("recommendedName") or {}).get("fullName") or {}
            full_name = recommended.get("value") or accession
            organism = (entry.get("organism") or {}).get("scientificName") or "Homo sapiens"
            domains = []
            ptm_sites = []
            for feature in entry.get("features") or []:
                ftype = str(feature.get("type") or "")
                location = feature.get("location") or {}
                start = (location.get("start") or {}).get("value")
                end = (location.get("end") or {}).get("value")
                description = str(feature.get("description") or ftype)
                if ftype.lower() in {"domain", "region", "motif", "topological domain", "transmembrane"}:
                    domains.append(
                        {
                            "name": description or ftype,
                            "start": int(start) if start else None,
                            "end": int(end) if end else None,
                        }
                    )
                if ftype.lower() in {"modified residue", "cross-link"}:
                    res = description.split(";")[0].strip() or f"site_{start}"
                    ptm_sites.append({"residue": res, "modification": "phosphorylation"})
            # Subcellular location comments
            localization = None
            for comment in entry.get("comments") or []:
                if comment.get("commentType") == "SUBCELLULAR LOCATION":
                    locs = comment.get("subcellularLocations") or []
                    if locs:
                        localization = (
                            (locs[0].get("location") or {}).get("value")
                            or None
                        )
            pdb_ids = []
            for xref in entry.get("uniProtKBCrossReferences") or []:
                if xref.get("database") == "PDB":
                    pid = xref.get("id")
                    if pid:
                        pdb_ids.append(str(pid))
            return {
                "accession": accession,
                "gene_symbol": gene_symbol or accession,
                "full_name": full_name,
                "organism": organism,
                "function": "",
                "domains": domains[:12],
                "ptm_sites": ptm_sites[:12],
                "localization": localization,
                "pdb_ids": pdb_ids[:5],
                "alphafold_url": f"https://alphafold.ebi.ac.uk/entry/{accession}",
                "diseases": [],
                "mutations": [],
            }
        except (TypeError, ValueError, KeyError) as exc:
            logger.debug("UniProt parse failed: %s", exc)
            return None

    def enrich_protein(self, protein: Protein) -> Protein:
        """Annotate a Protein in-place from UniProt offline/live metadata."""
        sym = protein.gene_symbol or protein.name
        data = self.lookup(sym)
        if not data:
            return protein
        protein.uniprot_id = data.get("accession") or protein.uniprot_id
        protein.full_name = data.get("full_name") or protein.full_name
        protein.gene_symbol = data.get("gene_symbol") or protein.gene_symbol
        if data.get("localization"):
            protein.cellular_localization = data["localization"]
        if data.get("domains") and not protein.domains:
            protein.domains = [
                ProteinDomain(
                    name=str(d.get("name", "domain")),
                    start=d.get("start") if d.get("start") else None,
                    end=d.get("end") if d.get("end") else None,
                    domain_type="annotated",
                )
                for d in data["domains"]
            ]
        if data.get("ptm_sites") and not protein.modification_sites:
            for p in data["ptm_sites"]:
                residue = str(p.get("residue", "site"))
                protein.modification_sites.append(
                    ModificationSite(
                        name=residue,
                        modification=ModificationType.PHOSPHORYLATION,
                        residue=residue,
                        occupancy=0.5,
                        active=True,
                    )
                )
        pdb_ids = data.get("pdb_ids") or []
        if pdb_ids and protein.structure.pdb_id is None:
            protein.structure = StructuralMetadata(
                pdb_id=str(pdb_ids[0]),
                alphafold_plddt_score=protein.structure.alphafold_plddt_score,
                disruption_delta=protein.structure.disruption_delta,
            )
        diseases = list(data.get("diseases") or [])
        muts = list(data.get("mutations") or [])
        if diseases or muts:
            protein.clinical = ClinicalAnnotation(
                diseases=diseases or list(protein.clinical.diseases),
                somatic_mutations=muts or list(protein.clinical.somatic_mutations),
                oncogene=protein.clinical.oncogene,
                tumor_suppressor=protein.clinical.tumor_suppressor,
                clinical_significance=protein.clinical.clinical_significance,
            )
        protein.metadata["uniprot_enrichment"] = data
        protein.metadata["alphafold_url"] = data.get("alphafold_url")
        return protein
