"""
Data normalization & ETL orchestration for VOIDSIGNAL Phase 2.

Combines local genomic artefacts (VCF / FASTA / GFF / BED) with public
knowledge clients to produce a simulation-ready
:class:`~voidsignal.topology.SignalingNetwork` plus Phase 1
:class:`~voidsignal.perturbation.Mutation` objects.

Missingness-as-a-feature
------------------------
When UniProt kinetic / sequence annotation is unavailable for a node, kinetic
parameters are approximated from:

1. Normalised degree centrality inside the assembled network, and/or
2. Mean STRING neighbourhood confidence for that gene symbol,

instead of aborting the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
import asyncio
import logging
import math
from voidsignal.components import Gene, KineticParameters, Protein
from voidsignal.knowledge_graph import (
    KnowledgeGraphService,
    PathwayMap,
    PPIEdge,
    UniProtRecord,
    apply_ppi_edges,
    enrich_protein_from_uniprot,
    pathway_map_to_network,
)
from voidsignal.parsers import (
    BEDParser,
    BedInterval,
    FASTAParser,
    FastaRecord,
    GenomicIntervalIndex,
    GFFParser,
    GenomicFeature,
    PathLike,
    VCFParser,
    VariantRecord,
    link_sequence_lengths,
    variants_to_mutations,
)
from voidsignal.perturbation import Mutation, PerturbationManager
from voidsignal.topology import InteractionType, SignalingNetwork
from voidsignal.vendored import VendoredPathwayRepository

logger = logging.getLogger(__name__)


@dataclass
class LocalDataset:
    """User-supplied local files (clinical / trial-like profiles)."""

    vcf_path: Optional[PathLike] = None
    fasta_path: Optional[PathLike] = None
    gff_path: Optional[PathLike] = None
    bed_path: Optional[PathLike] = None
    gene_panel: Optional[Sequence[str]] = None
    """Optional allow-list of gene symbols to retain."""


@dataclass
class PublicReferences:
    """Public pathway / PPI configuration."""

    kegg_pathway_id: Optional[str] = "hsa04010"
    reactome_pathway_id: Optional[str] = None
    use_string: bool = True
    use_biogrid: bool = False
    string_min_score: float = 0.4
    enrich_uniprot: bool = True
    uniprot_organism_id: int = 9606
    prefer_vendored: bool = False
    """If True, skip live KEGG and load the packaged pathway asset first."""
    allow_vendored_fallback: bool = True
    """If True, use VendoredPathwayRepository when the KEGG API fails / 404s."""


@dataclass
class MissingnessReport:
    """Audit trail for nodes that received fallback kinetic estimates."""

    node_name: str
    entity_id: str
    reason: str
    degree_centrality: float
    string_neighbourhood: float
    assigned_production_rate: float
    assigned_degradation_rate: float


@dataclass
class PipelineResult:
    """Fully assembled simulation artefacts."""

    network: SignalingNetwork
    mutations: List[Mutation]
    variants: List[VariantRecord] = field(default_factory=list)
    fasta: Dict[str, FastaRecord] = field(default_factory=dict)
    features: List[GenomicFeature] = field(default_factory=list)
    intervals: List[BedInterval] = field(default_factory=list)
    ppi_edges: List[PPIEdge] = field(default_factory=list)
    uniprot_records: Dict[str, UniProtRecord] = field(default_factory=dict)
    missingness: List[MissingnessReport] = field(default_factory=list)
    gene_to_entity_id: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def perturbation_manager(self) -> PerturbationManager:
        mgr = PerturbationManager()
        mgr.extend(self.mutations)
        return mgr


def degree_centrality(network: SignalingNetwork) -> Dict[str, float]:
    """
    Normalised total-degree centrality for every node.

    ``C(v) = min(1, deg(v) / (N - 1))`` for ``N > 1``, else ``0``.

    Clamped because VOIDSIGNAL graphs are typed multigraphs (pathway + PPI
    overlays can push raw degree above ``N - 1``).
    """
    nodes = network.nodes()
    n = len(nodes)
    if n <= 1:
        return {nid: 0.0 for nid in nodes}
    denom = float(n - 1)
    return {nid: min(1.0, network.total_degree(nid) / denom) for nid in nodes}


def approximate_kinetics(
    *,
    degree_cent: float,
    string_weight: float,
    sequence_length: Optional[int] = None,
) -> KineticParameters:
    """
    Missingness fallback kinetic estimator.

    Heuristic
    ---------
    * Production correlates with connectivity:
      ``k_prod = 0.05 + 0.5 · (0.6 · C_degree + 0.4 · w_STRING)``
    * Degradation anti-correlates lightly with sequence length (larger → slower)
      and with STRING support (well-supported hubs turnover moderately).

    All outputs are clamped to biologically plausible open intervals.
    """
    support = max(0.0, min(1.0, 0.6 * degree_cent + 0.4 * string_weight))
    production = 0.05 + 0.5 * support
    if sequence_length and sequence_length > 0:
        length_factor = 50.0 / math.sqrt(float(sequence_length))
    else:
        length_factor = 0.15
    degradation = max(0.01, min(0.5, 0.7 * length_factor + 0.1 * (1.0 - support)))
    basal = 0.05 * support
    return KineticParameters(
        production_rate=round(production, 6),
        degradation_rate=round(degradation, 6),
        basal_activity=round(min(basal, 1.0), 6),
        km=1.0,
        vmax=round(0.5 + support, 6),
    )


class BioDataPipeline:
    """
    End-to-end ETL: local files + public references → simulation network.

    Usage::

        pipeline = BioDataPipeline()
        result = asyncio.run(pipeline.run(
            LocalDataset(vcf_path="cohort.vcf", gene_panel=["EGFR", "KRAS", "BRAF"]),
            PublicReferences(kegg_pathway_id="hsa04010"),
        ))
        engine = DualEngineSimulator(result.network)
        engine.run_ode(config, perturbation_hooks=result.perturbation_manager().hooks())
    """

    def __init__(
        self,
        knowledge: Optional[KnowledgeGraphService] = None,
        *,
        missense_rate_scale: float = 0.5,
        default_concentration: float = 0.1,
    ) -> None:
        self.knowledge = knowledge or KnowledgeGraphService()
        self.missense_rate_scale = missense_rate_scale
        self.default_concentration = default_concentration

    # -- synchronous local parsers ------------------------------------------

    def load_local(self, dataset: LocalDataset) -> Dict[str, Any]:
        """Parse all provided local files; tolerant of missing paths."""
        payload: Dict[str, Any] = {
            "variants": [],
            "fasta": {},
            "features": [],
            "intervals": [],
        }
        if dataset.vcf_path:
            try:
                feature_index = None
                if dataset.gff_path:
                    try:
                        feature_index = GenomicIntervalIndex.from_gff(dataset.gff_path)
                    except Exception as exc:
                        logger.warning("Could not build GFF interval index: %s", exc)
                if feature_index is None and dataset.bed_path:
                    try:
                        feature_index = GenomicIntervalIndex.from_bed(dataset.bed_path)
                    except Exception as exc:
                        logger.warning("Could not build BED interval index: %s", exc)
                parser = VCFParser(dataset.vcf_path, feature_index=feature_index)
                _, variants = parser.parse()
                payload["variants"] = variants
                payload["vcf_fallback_annotated"] = parser.fallback_annotated
                payload["vcf_fallback_unresolved"] = parser.fallback_unresolved
                logger.info(
                    "Loaded %d VCF variants from %s (fallback annotated=%d unresolved=%d)",
                    len(variants),
                    dataset.vcf_path,
                    parser.fallback_annotated,
                    parser.fallback_unresolved,
                )
            except FileNotFoundError:
                logger.error("VCF not found: %s", dataset.vcf_path)
            except Exception as excel:
                logger.exception("VCF parse failed for %s: %s", dataset.vcf_path, excel)

        if dataset.fasta_path:
            try:
                payload["fasta"] = FASTAParser(dataset.fasta_path).as_dict()
                logger.info("Loaded %d FASTA records from %s", len(payload["fasta"]), dataset.fasta_path)
            except FileNotFoundError:
                logger.error("FASTA not found: %s", dataset.fasta_path)
            except Exception as exc:
                logger.exception("FASTA parse failed for %s: %s", dataset.fasta_path, exc)

        if dataset.gff_path:
            try:
                payload["features"] = GFFParser(dataset.gff_path).parse()
                logger.info("Loaded %d GFF features from %s", len(payload["features"]), dataset.gff_path)
            except FileNotFoundError:
                logger.error("GFF not found: %s", dataset.gff_path)
            except Exception as exc:
                logger.exception("GFF parse failed for %s: %s", dataset.gff_path, exc)

        if dataset.bed_path:
            try:
                payload["intervals"] = BEDParser(dataset.bed_path).parse()
                logger.info("Loaded %d BED intervals from %s", len(payload["intervals"]), dataset.bed_path)
            except FileNotFoundError:
                logger.error("BED not found: %s", dataset.bed_path)
            except Exception as exc:
                logger.exception("BED parse failed for %s: %s", dataset.bed_path, exc)

        return payload

    # -- network assembly ---------------------------------------------------

    async def assemble_network(
        self,
        refs: PublicReferences,
        *,
        seed_genes: Optional[Sequence[str]] = None,
        base_network: Optional[SignalingNetwork] = None,
    ) -> Tuple[SignalingNetwork, List[PPIEdge], Optional[PathwayMap]]:
        """
        Build / extend a signalling network from KEGG / Reactome / STRING / BioGRID.
        """
        network = base_network or SignalingNetwork(name="etl_network")
        ppi_edges: List[PPIEdge] = []
        pathway: Optional[PathwayMap] = None

        if refs.kegg_pathway_id:
            pathway = None
            used_vendored = False
            try:
                if refs.prefer_vendored:
                    repo = VendoredPathwayRepository()
                    pathway = repo.load_map(refs.kegg_pathway_id)
                    used_vendored = True
                    logger.info(
                        "Prefer-vendored: loaded %s from VendoredPathwayRepository",
                        refs.kegg_pathway_id,
                    )
                else:
                    pathway = await self.knowledge.kegg.fetch_pathway_map(refs.kegg_pathway_id)
                    if pathway is not None and pathway.metadata.get("vendored"):
                        used_vendored = True
            except Exception as exc:
                logger.exception("KEGG assembly failed: %s", exc)
                pathway = None

            if pathway is None and refs.allow_vendored_fallback:
                try:
                    repo = VendoredPathwayRepository()
                    if repo.has(refs.kegg_pathway_id):
                        pathway = repo.load_map(refs.kegg_pathway_id)
                        used_vendored = True
                        logger.warning(
                            "KEGG cold-start/offline — vendored fallback for %s",
                            refs.kegg_pathway_id,
                        )
                except Exception as exc:
                    logger.exception("Vendored KEGG fallback failed: %s", exc)

            if pathway is not None:
                network = pathway_map_to_network(
                    pathway,
                    network=network,
                    default_concentration=self.default_concentration,
                )
                network.name = pathway.name or network.name
                logger.info(
                    "KEGG %s → %d nodes, %d relations, %d reactions (vendored=%s)",
                    refs.kegg_pathway_id,
                    len(pathway.nodes),
                    len(pathway.relations),
                    len(pathway.reactions),
                    used_vendored,
                )
            else:
                logger.warning(
                    "KEGG pathway %s unavailable and no vendored asset — "
                    "continuing; missingness kinetics may apply later",
                    refs.kegg_pathway_id,
                )

        if refs.reactome_pathway_id:
            try:
                r_map = await self.knowledge.reactome.fetch_pathway_map(refs.reactome_pathway_id)
                if r_map is not None:
                    network = pathway_map_to_network(
                        r_map,
                        network=network,
                        default_concentration=self.default_concentration,
                    )
                    logger.info(
                        "Reactome %s → %d nodes, %d relations",
                        refs.reactome_pathway_id,
                        len(r_map.nodes),
                        len(r_map.relations),
                    )
            except Exception as excel:
                logger.exception("Reactome assembly failed: %s", excel)

        # Ensure seed genes / panel members exist even if pathway fetch failed
        if seed_genes:
            existing = {e.name.upper() for e in network.registry.entities()}
            for gene in seed_genes:
                if gene.upper() in existing:
                    continue
                network.add_node(
                    Protein(
                        name=gene,
                        concentration=self.default_concentration,
                        metadata={"source": "gene_panel"},
                    )
                )
                existing.add(gene.upper())

        gene_names = [e.name for e in network.registry.entities()]
        if refs.use_string and gene_names:
            try:
                string_edges = await self.knowledge.string.fetch_network(gene_names)
                apply_ppi_edges(
                    network,
                    string_edges,
                    min_score=refs.string_min_score,
                    interaction_type=InteractionType.BINDING,
                    create_missing=False,
                )
                ppi_edges.extend(string_edges)
                logger.info("STRING overlay added from %d raw edges", len(string_edges))
            except Exception as exc:
                logger.exception("STRING overlay failed: %s", exc)

        if refs.use_biogrid and gene_names:
            try:
                bg_edges = await self.knowledge.biogrid.fetch_interactions(gene_names)
                apply_ppi_edges(
                    network,
                    bg_edges,
                    min_score=0.4,
                    create_missing=False,
                )
                ppi_edges.extend(bg_edges)
                logger.info("BioGRID overlay added from %d raw edges", len(bg_edges))
            except Exception as exc:
                logger.exception("BioGRID overlay failed: %s", exc)

        return network, ppi_edges, pathway

    async def enrich_with_uniprot(
        self,
        network: SignalingNetwork,
        *,
        organism_id: int = 9606,
        max_genes: Optional[int] = None,
    ) -> Dict[str, UniProtRecord]:
        """Fetch UniProt records for network gene symbols (best-effort)."""
        records: Dict[str, UniProtRecord] = {}
        entities = list(network.registry.entities())
        if max_genes is not None:
            entities = entities[: max(0, max_genes)]
        for entity in entities:
            if not isinstance(entity, Protein):
                continue
            try:
                hits = await self.knowledge.uniprot.search_gene(
                    entity.name,
                    organism_id=organism_id,
                    limit=1,
                )
            except Exception as excel:
                logger.warning("UniProt search error for %s: %s", entity.name, excel)
                continue
            if not hits:
                logger.debug("No UniProt hit for %s", entity.name)
                continue
            rec = hits[0]
            records[entity.name] = rec
            enrich_protein_from_uniprot(entity, rec)
        return records

    def apply_sequence_lengths(
        self,
        network: SignalingNetwork,
        fasta: Mapping[str, FastaRecord],
        features: Sequence[GenomicFeature],
    ) -> None:
        """Stamp ``sequence_length`` from FASTA/GFF linkage onto matching proteins."""
        lengths = link_sequence_lengths(fasta, features)
        for entity in network.registry.entities():
            if not isinstance(entity, (Protein, Gene)):
                continue
            for key in (entity.name, entity.name.upper()):
                if key in lengths:
                    if isinstance(entity, Protein):
                        entity.sequence_length = lengths[key]
                    entity.metadata["linked_sequence_length"] = lengths[key]
                    break
            # Direct FASTA id match
            if entity.name in fasta:
                if isinstance(entity, Protein):
                    entity.sequence_length = fasta[entity.name].length
                entity.metadata["linked_sequence_length"] = fasta[entity.name].length

    def apply_bed_locus_metadata(
        self,
        network: SignalingNetwork,
        intervals: Sequence[BedInterval],
    ) -> None:
        """Attach BED interval coordinates to proteins / genes by matching names."""
        by_name = {iv.name: iv for iv in intervals if iv.name}
        for entity in network.registry.entities():
            iv = by_name.get(entity.name) or by_name.get(entity.name.upper())
            if iv is None:
                continue
            entity.metadata["bed_chrom"] = iv.chrom
            entity.metadata["bed_start"] = iv.start
            entity.metadata["bed_end"] = iv.end
            entity.metadata["bed_length"] = iv.length
            if isinstance(entity, Gene):
                entity.chromosomal_locus = f"{iv.chrom}:{iv.start}-{iv.end}"

    def fill_missing_kinetics(
        self,
        network: SignalingNetwork,
        ppi_edges: Sequence[PPIEdge],
        uniprot_records: Mapping[str, UniProtRecord],
    ) -> List[MissingnessReport]:
        """
        Assign approximate kinetics where UniProt enrichment did not supply them.

        A node is considered missing kinetics when it was not present in
        ``uniprot_records`` (primary annotation source for this pipeline).
        """
        reports: List[MissingnessReport] = []
        centrality = degree_centrality(network)
        string_weights = self.knowledge.string.neighbourhood_weights(ppi_edges)
        for entity in network.registry.entities():
            if not isinstance(entity, Protein):
                continue
            if entity.name in uniprot_records:
                continue
            # Also treat explicitly flagged missingness
            deg = centrality.get(entity.entity_id, 0.0)
            str_w = string_weights.get(entity.name, string_weights.get(entity.name.upper(), 0.0))
            seq_len = entity.sequence_length
            kinetics = approximate_kinetics(
                degree_cent=deg,
                string_weight=str_w,
                sequence_length=seq_len,
            )
            entity.kinetics = kinetics
            entity.metadata["kinetics_source"] = "missingness_fallback"
            entity.metadata["degree_centrality"] = deg
            entity.metadata["string_neighbourhood"] = str_w
            reports.append(
                MissingnessReport(
                    node_name=entity.name,
                    entity_id=entity.entity_id,
                    reason="no_uniprot_annotation",
                    degree_centrality=deg,
                    string_neighbourhood=str_w,
                    assigned_production_rate=kinetics.production_rate,
                    assigned_degradation_rate=kinetics.degradation_rate,
                )
            )
        if reports:
            logger.info("Applied missingness fallback kinetics to %d nodes", len(reports))
        return reports

    def build_gene_index(self, network: SignalingNetwork) -> Dict[str, str]:
        """Map gene / protein display names → entity_id (case-sensitive + upper)."""
        index: Dict[str, str] = {}
        for entity in network.registry.entities():
            index[entity.name] = entity.entity_id
            index[entity.name.upper()] = entity.entity_id
        return index

    def map_variants(
        self,
        variants: Sequence[VariantRecord],
        gene_to_entity_id: Mapping[str, str],
        *,
        gene_panel: Optional[Sequence[str]] = None,
    ) -> List[Mutation]:
        """Convert VCF records into Phase 1 mutations, optionally panel-filtered."""
        panel = {g.upper() for g in gene_panel} if gene_panel else None
        filtered = variants
        if panel is not None:
            filtered = [v for v in variants if v.gene and v.gene.upper() in panel]
        return variants_to_mutations(
            filtered,
            gene_to_entity_id,
            missense_rate_scale=self.missense_rate_scale,
        )

    # -- full run -----------------------------------------------------------

    async def run(
        self,
        dataset: LocalDataset,
        refs: Optional[PublicReferences] = None,
        *,
        base_network: Optional[SignalingNetwork] = None,
        uniprot_max_genes: Optional[int] = 25,
    ) -> PipelineResult:
        """
        Execute the full ETL pipeline.

        Parameters
        ----------
        uniprot_max_genes :
            Cap on UniProt live lookups (keeps demos responsive). ``None`` = all.
        """
        refs = refs or PublicReferences()
        local = self.load_local(dataset)

        seed = list(dataset.gene_panel or [])
        for variant in local["variants"]:
            if variant.gene and variant.gene not in seed:
                seed.append(variant.gene)

        network, ppi_edges, pathway = await self.assemble_network(
            refs,
            seed_genes=seed,
            base_network=base_network,
        )

        self.apply_sequence_lengths(network, local["fasta"], local["features"])
        self.apply_bed_locus_metadata(network, local["intervals"])

        uniprot_records: Dict[str, UniProtRecord] = {}
        if refs.enrich_uniprot:
            try:
                uniprot_records = await self.enrich_with_uniprot(
                    network,
                    organism_id=refs.uniprot_organism_id,
                    max_genes=uniprot_max_genes,
                )
            except Exception as exc:
                logger.exception("UniProt enrichment stage failed: %s", exc)

        missingness = self.fill_missing_kinetics(network, ppi_edges, uniprot_records)
        gene_index = self.build_gene_index(network)
        mutations = self.map_variants(
            local["variants"],
            gene_index,
            gene_panel=dataset.gene_panel,
        )

        issues = network.validate()
        if issues:
            logger.warning("Network validation issues: %s", issues)

        return PipelineResult(
            network=network,
            mutations=mutations,
            variants=local["variants"],
            fasta=local["fasta"],
            features=local["features"],
            intervals=local["intervals"],
            ppi_edges=ppi_edges,
            uniprot_records=uniprot_records,
            missingness=missingness,
            gene_to_entity_id=gene_index,
            metadata={
                "kegg_pathway_id": refs.kegg_pathway_id,
                "reactome_pathway_id": refs.reactome_pathway_id,
                "pathway_name": pathway.name if pathway else None,
                "n_nodes": len(network),
                "n_edges": len(network.edges()),
                "n_mutations": len(mutations),
                "n_missingness": len(missingness),
                "validation_issues": issues,
            },
        )

    def run_sync(
        self,
        dataset: LocalDataset,
        refs: Optional[PublicReferences] = None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Blocking convenience wrapper around :meth:`run`."""
        return asyncio.run(self.run(dataset, refs, **kwargs))


def build_network_from_kgml(
    kgml_text: str,
    *,
    pathway_id: str = "local",
    network: Optional[SignalingNetwork] = None,
) -> SignalingNetwork:
    """
    Offline helper: parse an on-disk KGML string into a Phase 1 network
    without touching the network. Useful for tests and air-gapped runs.
    """
    from voidsignal.knowledge_graph import KEGGClient

    pathway = KEGGClient().parse_kgml(kgml_text, pathway_id=pathway_id)
    return pathway_map_to_network(pathway, network=network)


# ---------------------------------------------------------------------------
# Platform lifecycle re-exports (implementation lives in ``lifecycle``)
# ---------------------------------------------------------------------------

_LIFECYCLE_EXPORTS = frozenset(
    {
        "PLATFORM_PRESETS",
        "DrugPerturbation",
        "VoidSignalPipeline",
        "VoidSignalPipelineConfig",
        "VoidSignalPipelineResult",
        "build_arg_parser",
        "config_from_args",
        "load_activity_graph",
        "render_export",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LIFECYCLE_EXPORTS or name == "main":
        from voidsignal import lifecycle as _lifecycle

        return getattr(_lifecycle, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry: ``python -m voidsignal.pipeline``."""
    from voidsignal.lifecycle import main as _lifecycle_main

    return _lifecycle_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
