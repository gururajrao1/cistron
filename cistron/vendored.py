"""
Air-gapped / vendored pathway assets for CISTRON.

Provides offline high-fidelity pathway topologies so cold-start API failures
do not collapse the ETL pipeline onto raw centrality heuristics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import logging

from cistron.knowledge_graph import KEGGClient, PathwayMap, pathway_map_to_network
from cistron.topology import SignalingNetwork

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "pathways"

# Canonical pathway id aliases → vendored filename stem
_VENDOR_ALIASES: Dict[str, str] = {
    "hsa04010": "hsa04010_mapk",
    "path:hsa04010": "hsa04010_mapk",
    "mapk": "hsa04010_mapk",
    "MAPK": "hsa04010_mapk",
}


class VendoredPathwayRepository:
    """
    Load packaged KGML / pathway maps without network access.

    Resolution order for :meth:`load_kgml`:
    1. Explicit override path (constructor)
    2. Packaged file under ``cistron/assets/pathways/``
    3. Embedded minimal MAPK KGML string (last-resort in-memory asset)
    """

    def __init__(self, assets_dir: Optional[Path] = None) -> None:
        self.assets_dir = Path(assets_dir) if assets_dir is not None else _ASSETS_DIR
        self._kegg = KEGGClient()  # parser only; no HTTP required for parse_kgml

    def available(self) -> List[str]:
        """Return pathway ids that this repository can serve."""
        ids = sorted(set(_VENDOR_ALIASES.keys()))
        if self.assets_dir.is_dir():
            for path in sorted(self.assets_dir.glob("*.kgml")):
                ids.append(path.stem)
        return ids

    def resolve_stem(self, pathway_id: str) -> str:
        key = pathway_id.strip()
        if key in _VENDOR_ALIASES:
            return _VENDOR_ALIASES[key]
        # Strip path: prefix
        if key.startswith("path:"):
            key = key.split(":", 1)[1]
        return _VENDOR_ALIASES.get(key, key.replace(":", "_"))

    def kgml_path(self, pathway_id: str) -> Optional[Path]:
        stem = self.resolve_stem(pathway_id)
        candidate = self.assets_dir / f"{stem}.kgml"
        if candidate.is_file():
            return candidate
        # Direct filename match
        direct = self.assets_dir / f"{pathway_id}.kgml"
        if direct.is_file():
            return direct
        return None

    def load_kgml(self, pathway_id: str = "hsa04010") -> str:
        """
        Return KGML text for ``pathway_id``.

        Raises ``FileNotFoundError`` only if the embedded fallback also cannot
        serve this id (non-MAPK requests without a file).
        """
        path = self.kgml_path(pathway_id)
        if path is not None:
            text = path.read_text(encoding="utf-8")
            logger.info("Loaded vendored KGML from %s", path)
            return text
        stem = self.resolve_stem(pathway_id)
        if stem == "hsa04010_mapk" or pathway_id.strip() in _VENDOR_ALIASES:
            logger.warning(
                "Vendored KGML file missing at %s — using embedded MAPK asset",
                self.assets_dir,
            )
            return _EMBEDDED_HSA04010_KGML
        raise FileNotFoundError(
            f"No vendored pathway asset for {pathway_id!r} under {self.assets_dir}"
        )

    def load_map(self, pathway_id: str = "hsa04010") -> PathwayMap:
        """Parse a vendored KGML into a :class:`PathwayMap`."""
        kgml = self.load_kgml(pathway_id)
        pathway = self._kegg.parse_kgml(kgml, pathway_id=pathway_id if "04010" in pathway_id else "hsa04010")
        pathway.metadata = dict(pathway.metadata or {})
        pathway.metadata["vendored"] = True
        pathway.metadata["source"] = "VendoredPathwayRepository"
        return pathway

    def load_network(
        self,
        pathway_id: str = "hsa04010",
        *,
        network: Optional[SignalingNetwork] = None,
        default_concentration: float = 0.1,
    ) -> SignalingNetwork:
        """Materialise a Phase 1 :class:`SignalingNetwork` from a vendored pathway."""
        pathway = self.load_map(pathway_id)
        return pathway_map_to_network(
            pathway,
            network=network,
            default_concentration=default_concentration,
        )

    def has(self, pathway_id: str) -> bool:
        try:
            self.load_kgml(pathway_id)
            return True
        except FileNotFoundError:
            return False


# Minimal embedded copy — kept in sync with assets/pathways/hsa04010_mapk.kgml
# so editable installs without package-data still work offline.
_EMBEDDED_HSA04010_KGML = """<?xml version="1.0"?>
<!DOCTYPE pathway SYSTEM "https://www.kegg.jp/kegg/xml/KGML_v0.7.2_.dtd">
<pathway name="path:hsa04010" org="hsa" number="04010"
         title="MAPK signaling pathway (CISTRON embedded)">
  <entry id="1" name="hsa:1950" type="gene">
    <graphics name="EGF" type="rectangle" x="80" y="120" width="46" height="17"/>
  </entry>
  <entry id="2" name="hsa:1956" type="gene">
    <graphics name="EGFR" type="rectangle" x="180" y="120" width="46" height="17"/>
  </entry>
  <entry id="4" name="hsa:3845" type="gene">
    <graphics name="KRAS" type="rectangle" x="280" y="160" width="46" height="17"/>
  </entry>
  <entry id="6" name="hsa:673" type="gene">
    <graphics name="BRAF" type="rectangle" x="400" y="200" width="46" height="17"/>
  </entry>
  <entry id="7" name="hsa:5604" type="gene">
    <graphics name="MAP2K1" type="rectangle" x="520" y="120" width="46" height="17"/>
  </entry>
  <entry id="9" name="hsa:5594" type="gene">
    <graphics name="MAPK1" type="rectangle" x="640" y="120" width="46" height="17"/>
  </entry>
  <entry id="11" name="vs:MAP2K1_P" type="gene">
    <graphics name="MAP2K1_P" type="rectangle" x="520" y="40" width="54" height="17"/>
  </entry>
  <entry id="12" name="vs:MAPK1_P" type="gene">
    <graphics name="MAPK1_P" type="rectangle" x="640" y="40" width="54" height="17"/>
  </entry>
  <relation entry1="1" entry2="2" type="PPrel"><subtype name="activation"/></relation>
  <relation entry1="2" entry2="4" type="PPrel"><subtype name="activation"/></relation>
  <relation entry1="4" entry2="6" type="PPrel"><subtype name="activation"/></relation>
  <relation entry1="6" entry2="7" type="PPrel"><subtype name="activation"/></relation>
  <relation entry1="12" entry2="6" type="PPrel"><subtype name="inhibition"/></relation>
  <entry id="20" name="hsa:673" type="gene" reaction="rn:VS_MAP2K1_PHOS">
    <graphics name="BRAF" type="rectangle" x="400" y="40" width="46" height="17"/>
  </entry>
  <reaction id="100" name="rn:VS_MAP2K1_PHOS" type="irreversible">
    <substrate id="7" name="hsa:5604" stoichiometry="1"/>
    <product id="11" name="vs:MAP2K1_P" stoichiometry="1"/>
  </reaction>
  <entry id="21" name="vs:MAP2K1_P" type="gene" reaction="rn:VS_ERK_BURST">
    <graphics name="MAP2K1_P" type="rectangle" x="560" y="40" width="54" height="17"/>
  </entry>
  <reaction id="102" name="rn:VS_ERK_BURST" type="irreversible">
    <substrate id="9" name="hsa:5594" stoichiometry="1"/>
    <substrate id="11" name="vs:MAP2K1_P" stoichiometry="1"/>
    <product id="12" name="vs:MAPK1_P" stoichiometry="2"/>
  </reaction>
</pathway>
"""
