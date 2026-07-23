"""RCSB PDB + AlphaFold structure metadata (zero-key REST)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import logging

from voidsignal.integrations.cache_store import IntegrationCache
from voidsignal.integrations.http_sync import http_get_json, http_get_text

logger = logging.getLogger(__name__)

# Curated offline pocket priors when RCSB / AF are unreachable
_OFFLINE_STRUCTURE: Dict[str, Dict[str, Any]] = {
    "1M17": {
        "pdb_id": "1M17",
        "title": "EGFR kinase domain with erlotinib",
        "ligand": "Erlotinib",
        "resolution": 2.6,
        "active_site_center": [20.1, 32.4, 18.7],
        "active_site_size": [22.0, 22.0, 22.0],
        "uniprot": "P00533",
        "mean_plddt": 86.5,
    },
    "4OBE": {
        "pdb_id": "4OBE",
        "title": "KRAS G12D",
        "ligand": "GDP",
        "resolution": 1.9,
        "active_site_center": [15.0, 12.0, 10.0],
        "active_site_size": [18.0, 18.0, 18.0],
        "uniprot": "P01116",
        "mean_plddt": 91.2,
    },
    "3EQC": {
        "pdb_id": "3EQC",
        "title": "MEK1 with inhibitor",
        "ligand": "ATP-site inhibitor",
        "resolution": 2.1,
        "active_site_center": [25.0, 20.0, 15.0],
        "active_site_size": [20.0, 20.0, 20.0],
        "uniprot": "Q02750",
        "mean_plddt": 88.0,
    },
}


@dataclass
class StructureRecord:
    pdb_id: Optional[str] = None
    uniprot_accession: Optional[str] = None
    title: str = ""
    ligand_name: Optional[str] = None
    resolution_A: Optional[float] = None
    mean_plddt: Optional[float] = None
    active_site_center: Optional[Tuple[float, float, float]] = None
    active_site_size: Optional[Tuple[float, float, float]] = None
    alphafold_url: Optional[str] = None
    pdb_url: Optional[str] = None
    source: str = "offline"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pdb_id": self.pdb_id,
            "uniprot_accession": self.uniprot_accession,
            "title": self.title,
            "ligand_name": self.ligand_name,
            "resolution_A": self.resolution_A,
            "mean_plddt": self.mean_plddt,
            "active_site_center": list(self.active_site_center) if self.active_site_center else None,
            "active_site_size": list(self.active_site_size) if self.active_site_size else None,
            "alphafold_url": self.alphafold_url,
            "pdb_url": self.pdb_url,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


class StructureClient:
    """
    Zero-key structure enrichment via RCSB Data API + AlphaFold prediction API.

    Falls back to curated offline pocket priors when offline / rate-limited.
    """

    RCSB_ENTRY = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
    AF_PREDICTION = "https://alphafold.ebi.ac.uk/api/prediction/{accession}"

    def __init__(self, cache: Optional[IntegrationCache] = None) -> None:
        self.cache = cache or IntegrationCache()

    def lookup_pdb(self, pdb_id: str) -> StructureRecord:
        pid = pdb_id.strip().upper()
        cached = self.cache.get_json("rcsb", pid)
        if isinstance(cached, dict) and cached.get("pdb_id"):
            return self._from_payload(cached)

        url = self.RCSB_ENTRY.format(pdb_id=pid)
        payload = http_get_json(url)
        if isinstance(payload, dict):
            title = str(
                (payload.get("struct") or {}).get("title")
                or payload.get("entry")
                or pid
            )
            resol = None
            refine = payload.get("rcsb_entry_info") or {}
            try:
                rc = refine.get("resolution_combined")
                if isinstance(rc, list) and rc:
                    resol = float(rc[0])
                elif rc is not None:
                    resol = float(rc)
            except (TypeError, ValueError):
                resol = None
            record = StructureRecord(
                pdb_id=pid,
                title=title[:200],
                resolution_A=resol,
                pdb_url=f"https://www.rcsb.org/structure/{pid}",
                source="rcsb-live",
                metadata={"rcsb_keys": list(payload.keys())[:12]},
            )
            # Default pocket box when coordinates unavailable
            record.active_site_center = (0.0, 0.0, 0.0)
            record.active_site_size = (22.0, 22.0, 22.0)
            self.cache.set_json("rcsb", pid, record.as_dict())
            return record

        offline = _OFFLINE_STRUCTURE.get(pid)
        if offline:
            rec = self._from_payload(offline)
            rec.source = "offline"
            self.cache.set_json("rcsb", pid, rec.as_dict())
            return rec
        return StructureRecord(pdb_id=pid, title=pid, source="stub", pdb_url=f"https://www.rcsb.org/structure/{pid}")

    def lookup_alphafold(self, uniprot_accession: str) -> StructureRecord:
        acc = uniprot_accession.strip().upper()
        cached = self.cache.get_json("alphafold", acc)
        if isinstance(cached, dict) and cached.get("uniprot_accession"):
            return self._from_payload(cached)

        url = self.AF_PREDICTION.format(accession=acc)
        payload = http_get_json(url)
        # API returns a list of prediction entries
        entry: Optional[Dict[str, Any]] = None
        if isinstance(payload, list) and payload:
            entry = payload[0] if isinstance(payload[0], dict) else None
        elif isinstance(payload, dict):
            entry = payload

        if entry:
            plddt = entry.get("globalMetricValue") or entry.get("confidenceScore")
            try:
                mean_plddt = float(plddt) if plddt is not None else None
            except (TypeError, ValueError):
                mean_plddt = None
            record = StructureRecord(
                uniprot_accession=acc,
                title=str(entry.get("uniprotDescription") or acc),
                mean_plddt=mean_plddt,
                alphafold_url=f"https://alphafold.ebi.ac.uk/entry/{acc}",
                pdb_id=None,
                source="alphafold-live",
                metadata={"model": entry.get("modelCreatedDate")},
            )
            self.cache.set_json("alphafold", acc, record.as_dict())
            return record

        # Offline: map known UniProt → curated PDB priors
        for off in _OFFLINE_STRUCTURE.values():
            if str(off.get("uniprot", "")).upper() == acc:
                rec = self._from_payload(off)
                rec.uniprot_accession = acc
                rec.alphafold_url = f"https://alphafold.ebi.ac.uk/entry/{acc}"
                rec.source = "offline"
                self.cache.set_json("alphafold", acc, rec.as_dict())
                return rec
        return StructureRecord(
            uniprot_accession=acc,
            alphafold_url=f"https://alphafold.ebi.ac.uk/entry/{acc}",
            source="stub",
        )

    def enrich_from_uniprot_or_pdb(
        self,
        *,
        pdb_id: Optional[str] = None,
        uniprot_id: Optional[str] = None,
    ) -> StructureRecord:
        if pdb_id:
            rec = self.lookup_pdb(pdb_id)
            if uniprot_id and rec.mean_plddt is None:
                af = self.lookup_alphafold(uniprot_id)
                rec.mean_plddt = af.mean_plddt or rec.mean_plddt
                rec.alphafold_url = af.alphafold_url
                rec.uniprot_accession = uniprot_id
            return rec
        if uniprot_id:
            return self.lookup_alphafold(uniprot_id)
        return StructureRecord(source="empty")

    @staticmethod
    def _from_payload(data: Dict[str, Any]) -> StructureRecord:
        center = data.get("active_site_center")
        size = data.get("active_site_size")
        return StructureRecord(
            pdb_id=data.get("pdb_id"),
            uniprot_accession=data.get("uniprot") or data.get("uniprot_accession"),
            title=str(data.get("title") or ""),
            ligand_name=data.get("ligand") or data.get("ligand_name"),
            resolution_A=data.get("resolution") or data.get("resolution_A"),
            mean_plddt=data.get("mean_plddt"),
            active_site_center=tuple(center) if isinstance(center, list) and len(center) == 3 else None,
            active_site_size=tuple(size) if isinstance(size, list) and len(size) == 3 else None,
            alphafold_url=data.get("alphafold_url"),
            pdb_url=data.get("pdb_url")
            or (f"https://www.rcsb.org/structure/{data['pdb_id']}" if data.get("pdb_id") else None),
            source=str(data.get("source") or "cached"),
            metadata=dict(data.get("metadata") or {}),
        )

    def fetch_pdb_atom_lines(self, pdb_id: str, *, max_lines: int = 400) -> List[str]:
        """Download a short PDB atom excerpt for docking demos (cached)."""
        pid = pdb_id.strip().upper()
        cached = self.cache.get_json("pdb_atoms", pid)
        if isinstance(cached, dict) and "lines" in cached:
            return list(cached["lines"])[:max_lines]
        url = f"https://files.rcsb.org/download/{pid}.pdb"
        text = http_get_text(url, accept="chemical/x-pdb, text/plain")
        if not text:
            return []
        lines = [
            ln
            for ln in text.splitlines()
            if ln.startswith("ATOM") or ln.startswith("HETATM")
        ][:max_lines]
        self.cache.set_json("pdb_atoms", pid, {"lines": lines})
        return lines
