"""
CISTRON integrations — 20-domain biological data ingestion for the
Virtual Cellular Laboratory.

Wraps live REST clients (KEGG / Reactome / STRING / UniProt) with a durable
disk cache under ``.cache/cistron/db/`` and **offline fallback corpora** so
experiments never hard-fail without network.
"""

from cistron.integrations.catalog import (
    HUMAN_PATHWAY_CATALOG,
    PathwayCatalogEntry,
    list_pathway_catalog,
    resolve_pathway_ids,
)
from cistron.integrations.cache_store import (
    IntegrationCache,
    default_integration_cache_dir,
)
from cistron.integrations.depmap_client import DepMapClient, EssentialityRecord
from cistron.integrations.encode_client import EncodeClient, ChromatinState
from cistron.integrations.enrichment import BiologicalEnrichmentEngine, EnrichmentReport
from cistron.integrations.kegg_client import LabKEGGClient
from cistron.integrations.merger import MultiPathwayMerger, MergeResult
from cistron.integrations.reactome_client import LabReactomeClient
from cistron.integrations.string_client import LabSTRINGClient
from cistron.integrations.structure_client import StructureClient, StructureRecord
from cistron.integrations.uniprot_client import LabUniProtClient

__all__ = [
    "BiologicalEnrichmentEngine",
    "ChromatinState",
    "DepMapClient",
    "EncodeClient",
    "EnrichmentReport",
    "EssentialityRecord",
    "HUMAN_PATHWAY_CATALOG",
    "IntegrationCache",
    "LabKEGGClient",
    "LabReactomeClient",
    "LabSTRINGClient",
    "LabUniProtClient",
    "MergeResult",
    "MultiPathwayMerger",
    "PathwayCatalogEntry",
    "StructureClient",
    "StructureRecord",
    "default_integration_cache_dir",
    "list_pathway_catalog",
    "resolve_pathway_ids",
]
