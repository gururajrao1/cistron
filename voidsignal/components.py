"""
Biological entity data models and dual-state management for VOIDSIGNAL.

Each entity carries both a discrete Boolean activity flag (for logic-gate
dynamics) and a continuous concentration / abundance (for mass-action ODEs).
Compartments organise entities spatially so future trafficking and diffusion
layers can attach without rewriting entity identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Set, Tuple
import math
import uuid


class EntityType(Enum):
    """Canonical molecular / structural class tags."""

    GENE = auto()
    RNA = auto()
    PROTEIN = auto()
    COMPLEX = auto()
    LIGAND = auto()
    RECEPTOR = auto()
    COMPARTMENT = auto()


class ActivityState(Enum):
    """
    Discrete activity levels used by the Boolean engine.

    OFF / ON are the standard binary alphabet. PARTIAL is reserved for
    ternary / multi-valued Boolean extensions (e.g. hierarchical updating
    with intermediate phosphorylation states).
    """

    OFF = 0
    PARTIAL = 1
    ON = 2


class ModificationType(Enum):
    """Post-translational / covalent modification marks on proteins."""

    PHOSPHORYLATION = "phosphorylation"
    UBIQUITINATION = "ubiquitination"
    ACETYLATION = "acetylation"
    METHYLATION = "methylation"
    GLYCOSYLATION = "glycosylation"
    CLEAVAGE = "cleavage"
    NONE = "none"


@dataclass(frozen=True)
class KineticParameters:
    """
    Mass-action / Michaelis–Menten kinetic coefficients attached to an entity.

    Units are model-relative (concentration · time⁻¹). Absolute physical units
    can be mapped later via a calibration layer without changing this schema.

    Attributes
    ----------
    production_rate :
        Basal zero-order synthesis rate *k_synth* (conc / time).
    degradation_rate :
        First-order decay constant *k_deg* so half-life ≈ ln(2) / k_deg.
    basal_activity :
        Constitutive activity floor in [0, 1] used when no upstream edges fire.
    km :
        Michaelis constant for enzymatic forms (conc).
    vmax :
        Catalytic ceiling for enzymatic forms (conc / time).
    binding_affinity :
        Association constant *K_a* (1 / conc) for ligands / receptors.
    diffusion_coefficient :
        Reserved for multi-compartment trafficking (length² / time).
    """

    production_rate: float = 0.0
    degradation_rate: float = 0.1
    basal_activity: float = 0.0
    km: float = 1.0
    vmax: float = 1.0
    binding_affinity: float = 1.0
    diffusion_coefficient: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "production_rate",
            "degradation_rate",
            "basal_activity",
            "km",
            "vmax",
            "binding_affinity",
            "diffusion_coefficient",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
                raise ValueError(f"KineticParameters.{name} must be a finite number, got {value!r}")
            if value < 0.0:
                raise ValueError(f"KineticParameters.{name} must be non-negative, got {value}")
        if not 0.0 <= self.basal_activity <= 1.0:
            raise ValueError("basal_activity must lie in [0, 1]")

    def with_updates(self, **overrides: float) -> "KineticParameters":
        """Return a copy with selected fields replaced (immutable update)."""
        data = {
            "production_rate": self.production_rate,
            "degradation_rate": self.degradation_rate,
            "basal_activity": self.basal_activity,
            "km": self.km,
            "vmax": self.vmax,
            "binding_affinity": self.binding_affinity,
            "diffusion_coefficient": self.diffusion_coefficient,
        }
        data.update(overrides)
        return KineticParameters(**data)


@dataclass
class ModificationSite:
    """A named covalent-modification site on a protein or complex subunit."""

    name: str
    modification: ModificationType = ModificationType.NONE
    stoichiometry: float = 0.0
    rate_constant: float = 1.0
    residue: Optional[str] = None
    """Human residue label, e.g. ``Tyr1068`` / ``T202``."""
    occupancy: float = 0.0
    """Modified fraction ∈ [0, 1] when known from proteomics."""
    active: bool = False
    """Whether the modification is considered functionally engaged."""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ModificationSite.name must be non-empty")
        if self.stoichiometry < 0.0:
            raise ValueError("stoichiometry must be non-negative")
        if self.rate_constant < 0.0:
            raise ValueError("rate_constant must be non-negative")
        if not 0.0 <= self.occupancy <= 1.0:
            raise ValueError("occupancy must lie in [0, 1]")
        if self.residue is None and self.name:
            # Prefer explicit residue; fall back to site name when it looks like AA+pos
            self.residue = self.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "residue": self.residue,
            "modification": self.modification.value,
            "stoichiometry": self.stoichiometry,
            "occupancy": self.occupancy,
            "active": self.active,
            "rate_constant": self.rate_constant,
        }


@dataclass(frozen=True)
class ProteinDomain:
    """Annotated structural / functional domain on a polypeptide."""

    name: str
    start: Optional[int] = None
    end: Optional[int] = None
    domain_type: str = "unknown"
    """e.g. kinase, SH2, transmembrane, DNA-binding."""
    active: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ProteinDomain.name must be non-empty")
        if self.start is not None and self.start < 1:
            raise ValueError("domain start must be 1-based ≥ 1")
        if self.end is not None and self.start is not None and self.end < self.start:
            raise ValueError("domain end must be ≥ start")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "domain_type": self.domain_type,
            "active": self.active,
        }


@dataclass
class StructuralMetadata:
    """Structural biology annotations (PDB / AlphaFold / docking box)."""

    pdb_id: Optional[str] = None
    alphafold_plddt_score: Optional[float] = None
    """Mean pLDDT confidence ∈ [0, 100]."""
    active_site_center: Optional[Tuple[float, float, float]] = None
    active_site_size: Optional[Tuple[float, float, float]] = None
    """Bounding-box edge lengths (Å) around the active site."""
    disruption_delta: float = 0.0
    """Structural disruption coefficient δ ∈ [0, 1]."""

    def __post_init__(self) -> None:
        if self.alphafold_plddt_score is not None:
            if not 0.0 <= self.alphafold_plddt_score <= 100.0:
                raise ValueError("alphafold_plddt_score must lie in [0, 100]")
        if not 0.0 <= self.disruption_delta <= 1.0:
            raise ValueError("disruption_delta must lie in [0, 1]")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pdb_id": self.pdb_id,
            "alphafold_plddt_score": self.alphafold_plddt_score,
            "active_site_center": list(self.active_site_center) if self.active_site_center else None,
            "active_site_size": list(self.active_site_size) if self.active_site_size else None,
            "disruption_delta": self.disruption_delta,
        }


@dataclass
class DrugAssociation:
    """Known small-molecule / biologic association for a target protein."""

    name: str
    mechanism: str = "inhibitor"
    ic50_nM: Optional[float] = None
    ki_M: Optional[float] = None
    approval_status: str = "research"
    """research | clinical | approved."""
    smiles: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("DrugAssociation.name must be non-empty")
        if self.ic50_nM is not None and self.ic50_nM < 0.0:
            raise ValueError("ic50_nM must be non-negative")
        if self.ki_M is not None and self.ki_M < 0.0:
            raise ValueError("ki_M must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "mechanism": self.mechanism,
            "ic50_nM": self.ic50_nM,
            "ki_M": self.ki_M,
            "approval_status": self.approval_status,
            "smiles": self.smiles,
        }


@dataclass
class ClinicalAnnotation:
    """Disease and mutation context for a gene/protein."""

    diseases: List[str] = field(default_factory=list)
    somatic_mutations: List[str] = field(default_factory=list)
    """HGVS-style mutations, e.g. ``EGFR p.L858R``."""
    clinical_significance: Optional[str] = None
    oncogene: bool = False
    tumor_suppressor: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diseases": list(self.diseases),
            "somatic_mutations": list(self.somatic_mutations),
            "clinical_significance": self.clinical_significance,
            "oncogene": self.oncogene,
            "tumor_suppressor": self.tumor_suppressor,
        }


def _new_entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class BiologicalEntity:
    """
    Base class for all simulatable nodes.

    Dual-state contract
    -------------------
    * ``boolean_state`` — discrete ON/OFF(/PARTIAL) used by logic dynamics.
    * ``concentration`` — continuous abundance used by ODE mass-action.

    Perturbations mutate either (or both) through the public setters so that
    the Boolean and ODE engines never fight over raw attribute writes.
    """

    name: str
    entity_type: EntityType = EntityType.PROTEIN
    entity_id: str = field(default="")
    compartment_id: Optional[str] = None
    concentration: float = 0.0
    boolean_state: ActivityState = ActivityState.OFF
    kinetics: KineticParameters = field(default_factory=KineticParameters)
    metadata: Dict[str, Any] = field(default_factory=dict)
    locked: bool = False
    """When True, simulators and most perturbations refuse concentration writes."""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("BiologicalEntity.name must be non-empty")
        if not self.entity_id:
            self.entity_id = _new_entity_id(self.entity_type.name.lower())
        if self.concentration < 0.0:
            raise ValueError(f"{self.entity_id}: concentration cannot be negative")

    # -- state accessors -----------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True when the Boolean state is ON (PARTIAL counts as inactive for binary gates)."""
        return self.boolean_state is ActivityState.ON

    def set_boolean(self, state: ActivityState | bool | int) -> None:
        """
        Set discrete activity.

        Accepts ``ActivityState``, ``bool`` (True→ON, False→OFF), or ``0/1/2``.
        Locked entities may still change Boolean state unless ``metadata`` sets
        ``lock_boolean=True`` (used by hard knockouts).
        """
        if self.locked and self.metadata.get("lock_boolean", False):
            raise RuntimeError(f"Entity {self.entity_id!r} Boolean state is locked")
        if isinstance(state, bool):
            self.boolean_state = ActivityState.ON if state else ActivityState.OFF
            return
        if isinstance(state, int) and not isinstance(state, ActivityState):
            try:
                self.boolean_state = ActivityState(state)
            except ValueError as exc:
                raise ValueError(f"Invalid boolean state integer {state}") from exc
            return
        if isinstance(state, ActivityState):
            self.boolean_state = state
            return
        raise TypeError(f"Unsupported boolean state type: {type(state)!r}")

    def set_concentration(self, value: float) -> None:
        """Set continuous abundance; clamped to ≥ 0. Rejects writes when locked."""
        if self.locked:
            raise RuntimeError(f"Entity {self.entity_id!r} concentration is locked")
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"{self.entity_id}: concentration must be finite")
        self.concentration = max(0.0, float(value))

    def apply_delta(self, delta: float) -> None:
        """Additive concentration update (used by ODE integrators)."""
        self.set_concentration(self.concentration + delta)

    def sync_boolean_from_concentration(self, threshold: float = 0.5) -> None:
        """
        Map continuous abundance onto binary activity via a Heaviside threshold.

        Biology: rough correspondence to a cooperative promoter / activation
        threshold where the molecule is functionally 'present'.
        """
        if threshold < 0.0:
            raise ValueError("threshold must be non-negative")
        self.boolean_state = ActivityState.ON if self.concentration >= threshold else ActivityState.OFF

    def sync_concentration_from_boolean(self, on_level: float = 1.0, off_level: float = 0.0) -> None:
        """Lift Boolean activity into continuous space (Boolean→ODE hand-off)."""
        if on_level < off_level:
            raise ValueError("on_level must be ≥ off_level")
        if self.boolean_state is ActivityState.ON:
            level = on_level
        elif self.boolean_state is ActivityState.PARTIAL:
            level = 0.5 * (on_level + off_level)
        else:
            level = off_level
        # Bypass lock for intentional dual-engine coupling.
        previous_lock = self.locked
        self.locked = False
        try:
            self.set_concentration(level)
        finally:
            self.locked = previous_lock

    def copy_state(self) -> Dict[str, Any]:
        """Snapshot used by trajectory recorders and checkpoint-restart."""
        return {
            "entity_id": self.entity_id,
            "concentration": self.concentration,
            "boolean_state": self.boolean_state.value,
            "locked": self.locked,
        }

    def restore_state(self, snapshot: Mapping[str, Any]) -> None:
        """Restore a snapshot produced by :meth:`copy_state`."""
        previous_lock = self.locked
        self.locked = False
        try:
            self.set_concentration(float(snapshot["concentration"]))
            self.set_boolean(int(snapshot["boolean_state"]))
        finally:
            self.locked = bool(snapshot.get("locked", previous_lock))

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable view for export / visualisation adapters."""
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type.name,
            "compartment_id": self.compartment_id,
            "concentration": self.concentration,
            "boolean_state": self.boolean_state.name,
            "kinetics": {
                "production_rate": self.kinetics.production_rate,
                "degradation_rate": self.kinetics.degradation_rate,
                "basal_activity": self.kinetics.basal_activity,
                "km": self.kinetics.km,
                "vmax": self.kinetics.vmax,
                "binding_affinity": self.kinetics.binding_affinity,
                "diffusion_coefficient": self.kinetics.diffusion_coefficient,
            },
            "metadata": dict(self.metadata),
            "locked": self.locked,
        }


@dataclass
class Gene(BiologicalEntity):
    """
    Genomic locus that can be transcribed.

    Attributes
    ----------
    transcription_rate :
        Zero-order RNA production when the gene is transcriptionally ON.
    promoter_strength :
        Multiplier in [0, ∞) on transcription_rate (enhancer / promoter logic).
    chromosomal_locus :
        Optional genomic coordinate string (e.g. ``chr17:7577120``).
    gene_symbol / full_name / uniprot_id / kegg_id / aliases / species :
        Deep identity metadata for encyclopedia cards (solver-inert).
    """

    transcription_rate: float = 1.0
    promoter_strength: float = 1.0
    chromosomal_locus: Optional[str] = None
    expressed_rna_id: Optional[str] = None
    # -- rich biological identity (MassActionRHS-inert) ----------------------
    gene_symbol: Optional[str] = None
    full_name: Optional[str] = None
    uniprot_id: Optional[str] = None
    kegg_id: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    species: str = "Homo sapiens"
    cellular_localization: Optional[str] = None
    clinical: ClinicalAnnotation = field(default_factory=ClinicalAnnotation)
    pathway_membership: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.entity_type = EntityType.GENE
        super().__post_init__()
        if self.transcription_rate < 0.0:
            raise ValueError("transcription_rate must be non-negative")
        if self.promoter_strength < 0.0:
            raise ValueError("promoter_strength must be non-negative")
        if self.gene_symbol is None:
            self.gene_symbol = self.name

    def effective_transcription_rate(self) -> float:
        """Rate of RNA production given promoter strength and Boolean ON/OFF."""
        if not self.is_active and self.kinetics.basal_activity <= 0.0:
            return 0.0
        gate = 1.0 if self.is_active else self.kinetics.basal_activity
        return self.transcription_rate * self.promoter_strength * gate

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "transcription_rate": self.transcription_rate,
                "promoter_strength": self.promoter_strength,
                "chromosomal_locus": self.chromosomal_locus,
                "expressed_rna_id": self.expressed_rna_id,
                "gene_symbol": self.gene_symbol,
                "full_name": self.full_name,
                "uniprot_id": self.uniprot_id,
                "kegg_id": self.kegg_id,
                "aliases": list(self.aliases),
                "species": self.species,
                "cellular_localization": self.cellular_localization,
                "clinical": self.clinical.to_dict(),
                "pathway_membership": list(self.pathway_membership),
            }
        )
        return base

    def to_encyclopedia_card(self) -> Dict[str, Any]:
        """UniProt/Reactome-style identity card for frontend rendering."""
        return {
            "card_type": "gene",
            "title": self.gene_symbol or self.name,
            "subtitle": self.full_name or self.name,
            "identity": {
                "gene_symbol": self.gene_symbol,
                "full_name": self.full_name,
                "uniprot_id": self.uniprot_id,
                "kegg_id": self.kegg_id,
                "aliases": list(self.aliases),
                "species": self.species,
                "chromosomal_locus": self.chromosomal_locus,
            },
            "biology": {
                "cellular_localization": self.cellular_localization,
                "transcription_rate": self.transcription_rate,
                "promoter_strength": self.promoter_strength,
                "pathway_membership": list(self.pathway_membership),
            },
            "clinical": self.clinical.to_dict(),
            "kinetics": {
                "k_cat_proxy_vmax": self.kinetics.vmax,
                "Km": self.kinetics.km,
                "production_rate": self.kinetics.production_rate,
                "degradation_rate": self.kinetics.degradation_rate,
            },
            "entity_id": self.entity_id,
        }


@dataclass
class RNA(BiologicalEntity):
    """
    Transcript species (mRNA, miRNA, lncRNA, …).

    Attributes
    ----------
    translation_rate :
        First-order protein production rate from this RNA (mRNA only).
    half_life :
        RNA half-life; sets ``kinetics.degradation_rate = ln(2) / half_life``.
    is_coding :
        Whether the transcript encodes protein.
    """

    translation_rate: float = 1.0
    half_life: float = 2.0
    is_coding: bool = True
    source_gene_id: Optional[str] = None
    product_protein_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.entity_type = EntityType.RNA
        super().__post_init__()
        if self.translation_rate < 0.0:
            raise ValueError("translation_rate must be non-negative")
        if self.half_life <= 0.0:
            raise ValueError("half_life must be positive")
        deg = math.log(2.0) / self.half_life
        self.kinetics = self.kinetics.with_updates(degradation_rate=deg)


@dataclass
class Protein(BiologicalEntity):
    """
    Polypeptide with optional enzymatic activity and rich biological metadata.

    Kinetic fields (``kinetics.vmax`` ≈ k_cat, ``kinetics.km``, δ via
    ``structure.disruption_delta``) remain the sole MassActionRHS inputs;
    encyclopedia attributes are solver-inert wrappers.
    """

    is_enzyme: bool = False
    molecular_weight_kda: Optional[float] = None
    sequence_length: Optional[int] = None
    source_rna_id: Optional[str] = None
    modification_sites: List[ModificationSite] = field(default_factory=list)
    # -- rich biological identity -------------------------------------------
    gene_symbol: Optional[str] = None
    full_name: Optional[str] = None
    uniprot_id: Optional[str] = None
    kegg_id: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    species: str = "Homo sapiens"
    domains: List[ProteinDomain] = field(default_factory=list)
    cellular_localization: Optional[str] = None
    """e.g. Plasma Membrane, Cytosol, Nucleus."""
    structure: StructuralMetadata = field(default_factory=StructuralMetadata)
    clinical: ClinicalAnnotation = field(default_factory=ClinicalAnnotation)
    drugs: List[DrugAssociation] = field(default_factory=list)
    pathway_membership: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.entity_type = EntityType.PROTEIN
        super().__post_init__()
        if self.molecular_weight_kda is not None and self.molecular_weight_kda <= 0.0:
            raise ValueError("molecular_weight_kda must be positive when provided")
        if self.sequence_length is not None and self.sequence_length <= 0:
            raise ValueError("sequence_length must be positive when provided")
        if self.gene_symbol is None:
            self.gene_symbol = self.name

    @property
    def ptm_sites(self) -> List[ModificationSite]:
        """Alias for proteomics-style PTM occupancy lists."""
        return self.modification_sites

    def modification_level(self, modification: ModificationType) -> float:
        """Summed stoichiometry across sites carrying the given modification."""
        return sum(
            site.stoichiometry
            for site in self.modification_sites
            if site.modification is modification
        )

    def set_modification(
        self,
        site_name: str,
        modification: ModificationType,
        stoichiometry: float,
        *,
        residue: Optional[str] = None,
        occupancy: Optional[float] = None,
        active: Optional[bool] = None,
    ) -> None:
        """Update or create a named modification site."""
        for site in self.modification_sites:
            if site.name == site_name:
                site.modification = modification
                site.stoichiometry = max(0.0, stoichiometry)
                if residue is not None:
                    site.residue = residue
                if occupancy is not None:
                    site.occupancy = max(0.0, min(1.0, occupancy))
                if active is not None:
                    site.active = bool(active)
                return
        self.modification_sites.append(
            ModificationSite(
                name=site_name,
                modification=modification,
                stoichiometry=max(0.0, stoichiometry),
                residue=residue or site_name,
                occupancy=0.0 if occupancy is None else max(0.0, min(1.0, occupancy)),
                active=bool(active) if active is not None else stoichiometry > 0.0,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "is_enzyme": self.is_enzyme,
                "molecular_weight_kda": self.molecular_weight_kda,
                "sequence_length": self.sequence_length,
                "source_rna_id": self.source_rna_id,
                "gene_symbol": self.gene_symbol,
                "full_name": self.full_name,
                "uniprot_id": self.uniprot_id,
                "kegg_id": self.kegg_id,
                "aliases": list(self.aliases),
                "species": self.species,
                "cellular_localization": self.cellular_localization,
                "domains": [d.to_dict() for d in self.domains],
                "ptm_sites": [s.to_dict() for s in self.modification_sites],
                "structure": self.structure.to_dict(),
                "clinical": self.clinical.to_dict(),
                "drugs": [d.to_dict() for d in self.drugs],
                "pathway_membership": list(self.pathway_membership),
                "k_cat": self.kinetics.vmax,
                "Km": self.kinetics.km,
                "delta_disruption": self.structure.disruption_delta,
            }
        )
        return base

    def to_encyclopedia_card(self) -> Dict[str, Any]:
        """UniProt/Reactome-style protein card for Virtual Cellular Laboratory UI."""
        return {
            "card_type": "protein",
            "title": self.gene_symbol or self.name,
            "subtitle": self.full_name or ("Enzyme" if self.is_enzyme else "Protein"),
            "identity": {
                "gene_symbol": self.gene_symbol,
                "full_name": self.full_name,
                "uniprot_id": self.uniprot_id,
                "kegg_id": self.kegg_id,
                "aliases": list(self.aliases),
                "species": self.species,
            },
            "biology": {
                "is_enzyme": self.is_enzyme,
                "cellular_localization": self.cellular_localization,
                "domains": [d.to_dict() for d in self.domains],
                "ptm_sites": [s.to_dict() for s in self.modification_sites],
                "molecular_weight_kda": self.molecular_weight_kda,
                "sequence_length": self.sequence_length,
                "pathway_membership": list(self.pathway_membership),
            },
            "structure": self.structure.to_dict(),
            "clinical": self.clinical.to_dict(),
            "drugs": [d.to_dict() for d in self.drugs],
            "kinetics": {
                "k_cat": self.kinetics.vmax,
                "Km": self.kinetics.km,
                "production_rate": self.kinetics.production_rate,
                "degradation_rate": self.kinetics.degradation_rate,
                "binding_affinity": self.kinetics.binding_affinity,
                "delta_disruption": self.structure.disruption_delta,
            },
            "state": {
                "concentration": self.concentration,
                "boolean_state": self.boolean_state.name,
                "entity_id": self.entity_id,
            },
        }


@dataclass
class Complex(BiologicalEntity):
    """
    Multimeric assembly of proteins / ligands / other complexes.

    Stoichiometry map keys are member ``entity_id`` values; values are integer
    or float copy numbers per complex particle.

    Formation / dissociation rate constants feed the mass-action ODE layer:
        d[C]/dt = k_on · ∏[m_i]^{ν_i} − k_off · [C]
    """

    members: Dict[str, float] = field(default_factory=dict)
    association_rate: float = 1.0
    dissociation_rate: float = 0.1

    def __post_init__(self) -> None:
        self.entity_type = EntityType.COMPLEX
        super().__post_init__()
        if self.association_rate < 0.0 or self.dissociation_rate < 0.0:
            raise ValueError("association/dissociation rates must be non-negative")
        for member_id, stoich in self.members.items():
            if not member_id:
                raise ValueError("Complex member ids must be non-empty")
            if stoich <= 0.0:
                raise ValueError(f"Stoichiometry for {member_id!r} must be positive")

    def add_member(self, entity_id: str, stoichiometry: float = 1.0) -> None:
        if stoichiometry <= 0.0:
            raise ValueError("stoichiometry must be positive")
        self.members[entity_id] = float(stoichiometry)

    def remove_member(self, entity_id: str) -> None:
        if entity_id not in self.members:
            raise KeyError(f"Member {entity_id!r} not in complex {self.entity_id}")
        del self.members[entity_id]


@dataclass
class Ligand(BiologicalEntity):
    """
    Extracellular or small-molecule ligand.

    ``kd`` is the equilibrium dissociation constant for its cognate receptor.
    Competitive drug models read ``kd`` (or an override) when computing free
    receptor occupancy.
    """

    kd: float = 1.0
    is_agonist: bool = True
    molecular_weight: Optional[float] = None

    def __post_init__(self) -> None:
        self.entity_type = EntityType.LIGAND
        super().__post_init__()
        if self.kd <= 0.0:
            raise ValueError("kd must be positive")
        self.kinetics = self.kinetics.with_updates(binding_affinity=1.0 / self.kd)

    def occupancy(self, receptor_conc: float) -> float:
        """
        Simple Langmuir isotherm occupancy of a receptor by this ligand:

            θ = [L] / ([L] + K_d)

        Independent of absolute receptor concentration under excess-ligand
        assumption; ``receptor_conc`` is retained for future occupancy models.
        """
        if receptor_conc < 0.0:
            raise ValueError("receptor_conc must be non-negative")
        return self.concentration / (self.concentration + self.kd)


@dataclass
class Receptor(BiologicalEntity):
    """
    Membrane (or intracellular) receptor that binds ligands and transduces signal.

    Attributes
    ----------
    cognate_ligand_ids :
        Ligands that can bind this receptor.
    transduction_efficiency :
        Fraction of bound receptor that produces downstream signal ∈ [0, 1].
    internalisation_rate :
        First-order removal of active receptor (desensitisation).
    """

    cognate_ligand_ids: Set[str] = field(default_factory=set)
    transduction_efficiency: float = 1.0
    internalisation_rate: float = 0.0
    bound_fraction: float = 0.0

    def __post_init__(self) -> None:
        self.entity_type = EntityType.RECEPTOR
        super().__post_init__()
        if not 0.0 <= self.transduction_efficiency <= 1.0:
            raise ValueError("transduction_efficiency must lie in [0, 1]")
        if self.internalisation_rate < 0.0:
            raise ValueError("internalisation_rate must be non-negative")
        if not 0.0 <= self.bound_fraction <= 1.0:
            raise ValueError("bound_fraction must lie in [0, 1]")

    def active_signal(self) -> float:
        """Downstream drive = [R] · θ_bound · efficiency."""
        return self.concentration * self.bound_fraction * self.transduction_efficiency

    def bind_ligand(self, ligand: Ligand) -> float:
        """
        Update ``bound_fraction`` from a ligand via Langmuir binding and
        return the resulting active signal amplitude.
        """
        if ligand.entity_id not in self.cognate_ligand_ids and self.cognate_ligand_ids:
            raise ValueError(
                f"Ligand {ligand.entity_id!r} is not cognate to receptor {self.entity_id!r}"
            )
        self.bound_fraction = ligand.occupancy(self.concentration)
        return self.active_signal()


@dataclass
class CellularCompartment:
    """
    Spatial container for biological entities.

    Compartments are first-class graph nodes (type COMPARTMENT) *and* organisers
    of other entities via ``resident_ids``. Volume scales concentration↔count
    conversions in multi-compartment extensions.
    """

    name: str
    compartment_id: str = ""
    volume: float = 1.0
    parent_id: Optional[str] = None
    resident_ids: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("CellularCompartment.name must be non-empty")
        if not self.compartment_id:
            self.compartment_id = _new_entity_id("compartment")
        if self.volume <= 0.0:
            raise ValueError("volume must be positive")

    def add_resident(self, entity_id: str) -> None:
        self.resident_ids.add(entity_id)

    def remove_resident(self, entity_id: str) -> None:
        self.resident_ids.discard(entity_id)

    def as_entity(self) -> BiologicalEntity:
        """Expose the compartment as a graph-compatible BiologicalEntity node."""
        return BiologicalEntity(
            name=self.name,
            entity_type=EntityType.COMPARTMENT,
            entity_id=self.compartment_id,
            concentration=self.volume,
            metadata={"is_compartment": True, **self.metadata},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compartment_id": self.compartment_id,
            "name": self.name,
            "volume": self.volume,
            "parent_id": self.parent_id,
            "resident_ids": sorted(self.resident_ids),
            "metadata": dict(self.metadata),
        }


class EntityRegistry:
    """
    O(1) lookup store for all biological entities and compartments.

    Acts as the single source of truth for node payloads referenced by the
    topology layer. The graph stores only ``entity_id`` keys; simulators resolve
    live objects through this registry.
    """

    def __init__(self) -> None:
        self._entities: MutableMapping[str, BiologicalEntity] = {}
        self._compartments: MutableMapping[str, CellularCompartment] = {}

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self._entities or entity_id in self._compartments

    def __len__(self) -> int:
        return len(self._entities)

    def __iter__(self) -> Iterator[BiologicalEntity]:
        return iter(self._entities.values())

    def register(self, entity: BiologicalEntity) -> BiologicalEntity:
        if entity.entity_id in self._entities:
            raise KeyError(f"Duplicate entity_id {entity.entity_id!r}")
        if entity.compartment_id is not None and entity.compartment_id in self._compartments:
            self._compartments[entity.compartment_id].add_resident(entity.entity_id)
        self._entities[entity.entity_id] = entity
        return entity

    def register_compartment(self, compartment: CellularCompartment) -> CellularCompartment:
        if compartment.compartment_id in self._compartments:
            raise KeyError(f"Duplicate compartment_id {compartment.compartment_id!r}")
        self._compartments[compartment.compartment_id] = compartment
        # Also register as a BiologicalEntity so the graph can host it.
        if compartment.compartment_id not in self._entities:
            self.register(compartment.as_entity())
        return compartment

    def get(self, entity_id: str) -> BiologicalEntity:
        try:
            return self._entities[entity_id]
        except KeyError as exc:
            raise KeyError(f"Unknown entity_id {entity_id!r}") from exc

    def get_compartment(self, compartment_id: str) -> CellularCompartment:
        try:
            return self._compartments[compartment_id]
        except KeyError as exc:
            raise KeyError(f"Unknown compartment_id {compartment_id!r}") from exc

    def remove(self, entity_id: str) -> BiologicalEntity:
        entity = self.get(entity_id)
        if entity.compartment_id and entity.compartment_id in self._compartments:
            self._compartments[entity.compartment_id].remove_resident(entity_id)
        del self._entities[entity_id]
        return entity

    def ids(self) -> List[str]:
        return list(self._entities.keys())

    def by_type(self, entity_type: EntityType) -> List[BiologicalEntity]:
        return [e for e in self._entities.values() if e.entity_type is entity_type]

    def concentrations(self) -> Dict[str, float]:
        return {eid: e.concentration for eid, e in self._entities.items()}

    def boolean_states(self) -> Dict[str, ActivityState]:
        return {eid: e.boolean_state for eid, e in self._entities.items()}

    def apply_concentration_vector(self, values: Mapping[str, float]) -> None:
        for eid, value in values.items():
            self.get(eid).set_concentration(value)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {eid: entity.copy_state() for eid, entity in self._entities.items()}

    def restore(self, snap: Mapping[str, Mapping[str, Any]]) -> None:
        for eid, state in snap.items():
            self.get(eid).restore_state(state)

    def entities(self) -> Iterable[BiologicalEntity]:
        return self._entities.values()

    def compartments(self) -> Iterable[CellularCompartment]:
        return self._compartments.values()
