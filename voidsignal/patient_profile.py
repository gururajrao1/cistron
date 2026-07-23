"""
Patient-specific pathway synthesizer for VOIDSIGNAL Phase 7.

Ingests multi-variant VCF streams and quantitative expression panels (RNA-seq
style scaling), maps them onto a baseline :class:`~voidsignal.topology.SignalingNetwork`,
and produces a personalized :class:`PatientSignalingNetwork` ready for DualEngine
simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple, Union
import copy
import logging
import math

from voidsignal.components import BiologicalEntity, KineticParameters, Protein
from voidsignal.parsers import (
    VCFParser,
    VariantRecord,
    variants_to_mutations,
)
from voidsignal.perturbation import Mutation, MutationKind, PerturbationManager
from voidsignal.simulation import DualEngineSimulator, PerturbationHook
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


@dataclass(frozen=True)
class ExpressionRecord:
    """Quantitative expression scaling for one gene / protein symbol."""

    symbol: str
    fold_change: float = 1.0
    """Multiplicative expression scale relative to baseline (RNA-seq TPM ratio proxy)."""
    tpm: Optional[float] = None
    """Optional absolute abundance; used when ``fold_change`` is unset/1 and TPM baseline known."""
    z_score: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("ExpressionRecord.symbol must be non-empty")
        if self.fold_change <= 0.0 or not math.isfinite(self.fold_change):
            raise ValueError("fold_change must be finite and positive")


@dataclass
class PatientGenomicProfile:
    """Bundle of patient identifiers, variants, and expression panels."""

    patient_id: str
    variants: List[VariantRecord] = field(default_factory=list)
    expression: List[ExpressionRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def gene_symbols(self) -> List[str]:
        genes = set()
        for v in self.variants:
            if v.gene:
                genes.add(v.gene)
        for e in self.expression:
            genes.add(e.symbol)
        return sorted(genes)


@dataclass
class PatientSignalingNetwork:
    """
    Personalized pathway matrix wrapping a mutated/expression-scaled network.

    Attributes
    ----------
    network :
        Live simulatable graph (entity ids preserved from the baseline clone).
    baseline_fingerprint :
        Content summary of the template used for reproducibility checks.
    applied_mutations / expression_scales :
        Provenance of genomic and transcriptomic edits.
    """

    patient_id: str
    network: SignalingNetwork
    applied_mutations: List[Mutation] = field(default_factory=list)
    expression_scales: Dict[str, float] = field(default_factory=dict)
    unresolved_genes: List[str] = field(default_factory=list)
    baseline_fingerprint: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def gene_to_entity_id(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for ent in self.network.registry.entities():
            mapping[ent.name] = ent.entity_id
            mapping[ent.name.upper()] = ent.entity_id
            gs = ent.metadata.get("gene_symbol")
            if gs:
                mapping[str(gs)] = ent.entity_id
                mapping[str(gs).upper()] = ent.entity_id
        return mapping

    def mutation_hooks(self) -> List[PerturbationHook]:
        mgr = PerturbationManager()
        mgr.extend(self.applied_mutations)
        return mgr.hooks()

    def load_into(self, engine: DualEngineSimulator) -> PerturbationManager:
        """Attach patient mutations to a DualEngineSimulator (network should be this one)."""
        if engine.network is not self.network:
            logger.warning(
                "Engine network is not the PatientSignalingNetwork.network — "
                "hooks still attach, verify intentional"
            )
        mgr = PerturbationManager()
        mgr.extend(self.applied_mutations)
        for hook in mgr.hooks():
            engine.add_hook(hook)
        engine.network.metadata["patient_id"] = self.patient_id
        engine.network.metadata.update(self.metadata)
        return mgr

    def summary(self) -> Dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "n_nodes": len(self.network.nodes()),
            "n_edges": len(list(self.network.edges())),
            "n_mutations": len(self.applied_mutations),
            "n_expression_scales": len(self.expression_scales),
            "unresolved_genes": list(self.unresolved_genes),
            "baseline_fingerprint": dict(self.baseline_fingerprint),
        }


def _clone_network(baseline: SignalingNetwork) -> SignalingNetwork:
    """
    Structural deep clone via storage serializers when available, else manual copy.
    """
    try:
        from voidsignal.storage import deserialize_network, serialize_network

        return deserialize_network(serialize_network(baseline))
    except Exception:
        # Fallback: shallow-safe rebuild of proteins + edges
        net = SignalingNetwork(name=f"{baseline.name}_patient")
        net.metadata = dict(baseline.metadata)
        id_map: Dict[str, str] = {}
        for nid in baseline.nodes():
            ent = baseline.registry.get(nid)
            if isinstance(ent, Protein):
                clone = Protein(
                    name=ent.name,
                    entity_id=ent.entity_id,
                    concentration=ent.concentration,
                    kinetics=KineticParameters(
                        production_rate=ent.kinetics.production_rate,
                        degradation_rate=ent.kinetics.degradation_rate,
                        basal_activity=ent.kinetics.basal_activity,
                        km=ent.kinetics.km,
                        vmax=ent.kinetics.vmax,
                        binding_affinity=ent.kinetics.binding_affinity,
                        diffusion_coefficient=ent.kinetics.diffusion_coefficient,
                    ),
                    metadata=dict(ent.metadata),
                    is_enzyme=ent.is_enzyme,
                    sequence_length=ent.sequence_length,
                    source_rna_id=ent.source_rna_id,
                )
                clone.boolean_state = ent.boolean_state
                clone.locked = False
                net.add_node(clone, logic=copy.deepcopy(baseline.get_node_logic(nid)))
                id_map[nid] = clone.entity_id
            else:
                # Generic entity: reuse serialize path only; skip exotic types in fallback
                continue
        for edge in baseline.edges():
            if edge.source_id not in id_map or edge.target_id not in id_map:
                continue
            net.connect(
                id_map[edge.source_id],
                id_map[edge.target_id],
                edge.interaction_type,
                rate_constant=edge.rate_constant,
                weight=edge.weight,
                hill_coefficient=edge.hill_coefficient,
                ec50=edge.ec50,
                delay=edge.delay,
                metadata=dict(edge.metadata),
            )
        return net


def parse_expression_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    symbol_key: str = "gene",
    fold_key: str = "fold_change",
    tpm_key: str = "tpm",
) -> List[ExpressionRecord]:
    """Parse a list of dict rows (CSV/JSON-like) into expression records."""
    out: List[ExpressionRecord] = []
    for row in rows:
        sym = str(row.get(symbol_key) or row.get("symbol") or "").strip()
        if not sym:
            continue
        fc = row.get(fold_key, row.get("fc", 1.0))
        tpm = row.get(tpm_key)
        z = row.get("z_score")
        out.append(
            ExpressionRecord(
                symbol=sym,
                fold_change=float(fc) if fc is not None else 1.0,
                tpm=float(tpm) if tpm is not None else None,
                z_score=float(z) if z is not None else None,
            )
        )
    return out


def load_expression_tsv(path: PathLike) -> List[ExpressionRecord]:
    """
    Load a simple TSV/CSV with headers including ``gene`` and ``fold_change``.
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return []
    sep = "\t" if "\t" in lines[0] else ","
    headers = [h.strip().lower() for h in lines[0].split(sep)]
    rows: List[Dict[str, Any]] = []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(sep)]
        row = {headers[i]: parts[i] for i in range(min(len(headers), len(parts)))}
        rows.append(row)
    return parse_expression_table(rows, symbol_key="gene", fold_key="fold_change")


class PatientProfileEngine:
    """
    Build :class:`PatientSignalingNetwork` instances from genomic + expression data.
    """

    def __init__(
        self,
        baseline: SignalingNetwork,
        *,
        missense_rate_scale: float = 0.5,
        expression_cap: float = 20.0,
        expression_floor: float = 0.05,
        apply_expression_to_concentration: bool = True,
        apply_expression_to_production: bool = True,
    ) -> None:
        self.baseline = baseline
        if missense_rate_scale <= 0.0:
            raise ValueError("missense_rate_scale must be positive")
        if expression_cap < expression_floor:
            raise ValueError("expression_cap must be ≥ expression_floor")
        self.missense_rate_scale = missense_rate_scale
        self.expression_cap = expression_cap
        self.expression_floor = expression_floor
        self.apply_expression_to_concentration = apply_expression_to_concentration
        self.apply_expression_to_production = apply_expression_to_production

    def _fingerprint(self) -> Dict[str, Any]:
        return {
            "name": self.baseline.name,
            "n_nodes": len(self.baseline.nodes()),
            "n_edges": len(list(self.baseline.edges())),
            "node_names": sorted(self.baseline.registry.get(n).name for n in self.baseline.nodes()),
        }

    def _clamp_fc(self, fc: float) -> float:
        return max(self.expression_floor, min(self.expression_cap, float(fc)))

    def _resolve_symbol(self, network: SignalingNetwork, symbol: str) -> Optional[str]:
        if symbol in network.registry:
            return symbol
        upper = symbol.upper()
        for ent in network.registry.entities():
            if ent.name.upper() == upper:
                return ent.entity_id
            if str(ent.metadata.get("gene_symbol", "")).upper() == upper:
                return ent.entity_id
            if str(ent.metadata.get("uniprot_accession", "")).upper() == upper:
                return ent.entity_id
        return None

    def apply_expression(
        self,
        network: SignalingNetwork,
        panel: Sequence[ExpressionRecord],
    ) -> Tuple[Dict[str, float], List[str]]:
        scales: Dict[str, float] = {}
        unresolved: List[str] = []
        for rec in panel:
            eid = self._resolve_symbol(network, rec.symbol)
            if eid is None:
                unresolved.append(rec.symbol)
                continue
            fc = self._clamp_fc(rec.fold_change)
            # Optional z-score soft adjustment: z>0 boosts, z<0 suppresses mildly
            if rec.z_score is not None and math.isfinite(rec.z_score):
                fc *= math.exp(0.15 * max(-3.0, min(3.0, rec.z_score)))
                fc = self._clamp_fc(fc)
            ent = network.registry.get(eid)
            was_locked = ent.locked
            ent.locked = False
            k = ent.kinetics
            updates: Dict[str, float] = {}
            if self.apply_expression_to_production:
                updates["production_rate"] = max(0.0, k.production_rate * fc)
                updates["vmax"] = max(0.0, k.vmax * min(fc, 4.0) ** 0.5)
            ent.kinetics = k.with_updates(**updates) if updates else k
            if self.apply_expression_to_concentration:
                ent.set_concentration(max(0.0, ent.concentration * fc))
            ent.metadata["expression_fold_change"] = fc
            ent.metadata["patient_expression"] = True
            ent.locked = was_locked
            scales[eid] = fc
        return scales, unresolved

    def synthesize(
        self,
        profile: PatientGenomicProfile,
        *,
        include_filtered_variants: bool = False,
        mutation_t_start: float = 0.0,
    ) -> PatientSignalingNetwork:
        net = _clone_network(self.baseline)
        gene_map = {}
        for ent in net.registry.entities():
            gene_map[ent.name] = ent.entity_id
            gene_map[ent.name.upper()] = ent.entity_id
            gs = ent.metadata.get("gene_symbol")
            if gs:
                gene_map[str(gs)] = ent.entity_id
                gene_map[str(gs).upper()] = ent.entity_id

        mutations = variants_to_mutations(
            profile.variants,
            gene_map,
            t_start=mutation_t_start,
            missense_rate_scale=self.missense_rate_scale,
            include_filtered=include_filtered_variants,
        )
        scales, unresolved_expr = self.apply_expression(net, profile.expression)
        unresolved_var = [
            v.gene
            for v in profile.variants
            if v.gene and self._resolve_symbol(net, v.gene) is None
        ]
        unresolved = sorted(set([g for g in unresolved_var if g] + unresolved_expr))

        net.metadata["patient_id"] = profile.patient_id
        net.metadata["patient_n_variants"] = len(profile.variants)
        net.metadata["patient_n_mutations"] = len(mutations)
        net.metadata["is_patient_network"] = True
        net.name = f"{self.baseline.name}__{profile.patient_id}"

        return PatientSignalingNetwork(
            patient_id=profile.patient_id,
            network=net,
            applied_mutations=mutations,
            expression_scales=scales,
            unresolved_genes=unresolved,
            baseline_fingerprint=self._fingerprint(),
            metadata=dict(profile.metadata),
        )

    def synthesize_from_vcf(
        self,
        patient_id: str,
        vcf_path: PathLike,
        *,
        expression: Optional[Sequence[ExpressionRecord]] = None,
        expression_path: Optional[PathLike] = None,
        **kwargs: Any,
    ) -> PatientSignalingNetwork:
        variants = list(VCFParser(vcf_path).parse())
        panel: List[ExpressionRecord] = list(expression or [])
        if expression_path is not None:
            panel.extend(load_expression_tsv(expression_path))
        profile = PatientGenomicProfile(
            patient_id=patient_id,
            variants=variants,
            expression=panel,
            metadata={"vcf": str(vcf_path)},
        )
        return self.synthesize(profile, **kwargs)


def build_patient_network(
    baseline: SignalingNetwork,
    patient_id: str,
    variants: Sequence[VariantRecord],
    expression: Optional[Sequence[ExpressionRecord]] = None,
    **kwargs: Any,
) -> PatientSignalingNetwork:
    """Convenience one-shot synthesizer."""
    engine = PatientProfileEngine(baseline, **{
        k: kwargs.pop(k)
        for k in list(kwargs)
        if k in {
            "missense_rate_scale",
            "expression_cap",
            "expression_floor",
            "apply_expression_to_concentration",
            "apply_expression_to_production",
        }
    })
    profile = PatientGenomicProfile(
        patient_id=patient_id,
        variants=list(variants),
        expression=list(expression or []),
    )
    return engine.synthesize(profile, **kwargs)
