"""
VOIDSIGNAL integrations — 20-domain biological data ingestion for the
Virtual Cellular Laboratory.

Wraps live REST clients (KEGG / Reactome / STRING / UniProt) with a durable
disk cache under ``.cache/voidsignal/db/`` and **offline fallback corpora** so
experiments never hard-fail without network.
"""

from voidsignal.integrations.catalog import (
    HUMAN_PATHWAY_CATALOG,
    PathwayCatalogEntry,
    list_pathway_catalog,
    resolve_pathway_ids,
)
from voidsignal.integrations.cache_store import (
    IntegrationCache,
    default_integration_cache_dir,
)
from voidsignal.integrations.depmap_client import DepMapClient, EssentialityRecord
from voidsignal.integrations.encode_client import EncodeClient, ChromatinState
from voidsignal.integrations.enrichment import BiologicalEnrichmentEngine, EnrichmentReport
from voidsignal.integrations.kegg_client import LabKEGGClient
from voidsignal.integrations.merger import MultiPathwayMerger, MergeResult
from voidsignal.integrations.reactome_client import LabReactomeClient
from voidsignal.integrations.string_client import LabSTRINGClient
from voidsignal.integrations.structure_client import StructureClient, StructureRecord
from voidsignal.integrations.uniprot_client import LabUniProtClient

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
