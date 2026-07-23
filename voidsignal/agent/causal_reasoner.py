"""
Causal biology & explainability engine for VOIDSIGNAL.

Translates ODE trajectories and optional GNN integrated-gradient attributions
into step-by-step biological narratives suitable for the Virtual Cellular
Laboratory UI ("Why did ERK rise?", "Why did AKT stay off?").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

from voidsignal.components import BiologicalEntity, DrugAssociation, Protein
from voidsignal.simulation import TrajectoryResult
from voidsignal.topology import InteractionType, SignalingNetwork


# ---------------------------------------------------------------------------
# Narrative records
# ---------------------------------------------------------------------------


@dataclass
class CausalChainStep:
    """One hop in a causal narrative (upstream → target)."""

    source_name: str
    target_name: str
    interaction: str
    evidence: str
    attribution: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "target_name": self.target_name,
            "interaction": self.interaction,
            "evidence": self.evidence,
            "attribution": self.attribution,
        }


@dataclass
class CausalExplanation:
    """Structured answer to a biological Why? question."""

    node_id: str
    node_name: str
    kind: str
    """``activation`` | ``inactivation`` | ``delta``."""
    percent_change: float
    control_final: float
    perturbed_final: float
    narrative: str
    chain: List[CausalChainStep] = field(default_factory=list)
    mutations: List[str] = field(default_factory=list)
    drugs: List[str] = field(default_factory=list)
    pathways: List[str] = field(default_factory=list)
    confidence: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "kind": self.kind,
            "percent_change": self.percent_change,
            "control_final": self.control_final,
            "perturbed_final": self.perturbed_final,
            "narrative": self.narrative,
            "chain": [s.as_dict() for s in self.chain],
            "mutations": list(self.mutations),
            "drugs": list(self.drugs),
            "pathways": list(self.pathways),
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass
class DeltaSummaryReport:
    """Side-by-side Control vs Perturbed comparative narratives."""

    control_label: str
    perturbed_label: str
    activated: List[CausalExplanation]
    inactivated: List[CausalExplanation]
    stable: List[str]
    overview_narrative: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "control_label": self.control_label,
            "perturbed_label": self.perturbed_label,
            "activated": [e.as_dict() for e in self.activated],
            "inactivated": [e.as_dict() for e in self.inactivated],
            "stable": list(self.stable),
            "overview_narrative": self.overview_narrative,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct_change(control: float, perturbed: float) -> float:
    if not math.isfinite(control) or not math.isfinite(perturbed):
        return 0.0
    denom = abs(control) if abs(control) > 1e-12 else 1e-12
    out = 100.0 * (perturbed - control) / denom
    return out if math.isfinite(out) else 0.0


def _display_name(entity: BiologicalEntity) -> str:
    symbol = getattr(entity, "gene_symbol", None)
    return str(symbol or entity.name)


def _final_conc(traj: TrajectoryResult, entity_id: str) -> float:
    finals = traj.final_concentrations()
    if entity_id in finals:
        return float(finals[entity_id])
    # Fallback: last sample that contains the id
    for sample in reversed(traj.concentrations):
        if entity_id in sample:
            return float(sample[entity_id])
    return 0.0


def _format_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f}%"


def _mutation_phrase(mutations: Sequence[str]) -> Optional[str]:
    if not mutations:
        return None
    if len(mutations) == 1:
        return f"an oncogenic {mutations[0]} mutation"
    return "oncogenic mutations " + ", ".join(mutations)


def _drug_phrase(drugs: Sequence[DrugAssociation] | Sequence[str]) -> Optional[str]:
    if not drugs:
        return None
    names: List[str] = []
    for d in drugs:
        if isinstance(d, DrugAssociation):
            names.append(d.name)
        else:
            names.append(str(d))
    if len(names) == 1:
        return names[0]
    return " and ".join(names)


# ---------------------------------------------------------------------------
# CausalBioReasoner
# ---------------------------------------------------------------------------


class CausalBioReasoner:
    """
    Trajectory + topology → natural-language causal biology narratives.

    Parameters
    ----------
    network :
        Annotated signalling graph (preferably with pathway membership).
    control :
        Healthy / baseline ODE trajectory.
    perturbed :
        Mutant / drug-treated trajectory.
    attributions :
        Optional map ``entity_id → attribution_score`` from integrated gradients
        or other XAI methods (higher ⇒ more causal weight).
    activation_threshold_pct :
        Minimum |Δ%| to classify a node as activated / inactivated.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        control: TrajectoryResult,
        perturbed: TrajectoryResult,
        *,
        attributions: Optional[Mapping[str, float]] = None,
        activation_threshold_pct: float = 15.0,
        control_label: str = "Control (Healthy)",
        perturbed_label: str = "Perturbed (Mutant/Treated)",
    ) -> None:
        self.network = network
        self.control = control
        self.perturbed = perturbed
        self.attributions = dict(attributions or {})
        self.activation_threshold_pct = float(activation_threshold_pct)
        self.control_label = control_label
        self.perturbed_label = perturbed_label

    # -- public API ----------------------------------------------------------

    def explain_activation(self, node_id: str) -> CausalExplanation:
        """Explain why a node became (more) active under perturbation."""
        return self._explain_node(node_id, prefer_kind="activation")

    def explain_inactivation(self, node_id: str) -> CausalExplanation:
        """Explain why a node remained suppressed or decreased."""
        return self._explain_node(node_id, prefer_kind="inactivation")

    def delta_summary(
        self,
        node_ids: Optional[Iterable[str]] = None,
        *,
        top_n: int = 8,
    ) -> DeltaSummaryReport:
        """
        Side-by-side comparative narratives between control and perturbed runs.
        """
        ids = list(node_ids) if node_ids is not None else list(self.network.nodes())
        activated: List[CausalExplanation] = []
        inactivated: List[CausalExplanation] = []
        stable: List[str] = []

        scored: List[Tuple[float, str, float, float]] = []
        for nid in ids:
            if nid not in self.network:
                continue
            c = _final_conc(self.control, nid)
            p = _final_conc(self.perturbed, nid)
            pct = _pct_change(c, p)
            scored.append((abs(pct), nid, c, p))

        scored.sort(key=lambda t: (-t[0], t[1]))

        for abs_pct, nid, c, p in scored:
            name = _display_name(self.network.registry.get(nid))
            pct = _pct_change(c, p)
            if abs_pct < self.activation_threshold_pct:
                stable.append(name)
                continue
            if pct >= self.activation_threshold_pct:
                activated.append(self.explain_activation(nid))
            elif pct <= -self.activation_threshold_pct:
                inactivated.append(self.explain_inactivation(nid))
            else:
                stable.append(name)

        activated = activated[:top_n]
        inactivated = inactivated[:top_n]

        overview = self._build_overview(activated, inactivated, stable)
        return DeltaSummaryReport(
            control_label=self.control_label,
            perturbed_label=self.perturbed_label,
            activated=activated,
            inactivated=inactivated,
            stable=stable[:top_n],
            overview_narrative=overview,
            metadata={
                "n_nodes_scored": len(scored),
                "activation_threshold_pct": self.activation_threshold_pct,
            },
        )

    def explain_all(self, node_ids: Optional[Iterable[str]] = None) -> List[CausalExplanation]:
        """Generate explanations for every node exceeding the Δ threshold."""
        report = self.delta_summary(node_ids=node_ids, top_n=10_000)
        return list(report.activated) + list(report.inactivated)

    # -- internals -----------------------------------------------------------

    def _explain_node(self, node_id: str, *, prefer_kind: str) -> CausalExplanation:
        if node_id not in self.network:
            raise KeyError(f"Unknown node {node_id!r}")
        entity = self.network.registry.get(node_id)
        name = _display_name(entity)
        control_f = _final_conc(self.control, node_id)
        pert_f = _final_conc(self.perturbed, node_id)
        pct = _pct_change(control_f, pert_f)

        if prefer_kind == "activation" or (prefer_kind != "inactivation" and pct >= 0):
            kind = "activation"
        else:
            kind = "inactivation"

        chain = self._build_causal_chain(node_id, kind=kind)
        mutations = self._collect_mutations(node_id, upstream=True)
        drugs = self._collect_drug_names(node_id, upstream=True)
        pathways = sorted(self.network.node_pathways(node_id)) if hasattr(
            self.network, "node_pathways"
        ) else list(getattr(entity, "pathway_membership", []) or [])

        narrative = self._compose_narrative(
            entity=entity,
            name=name,
            kind=kind,
            pct=pct,
            chain=chain,
            mutations=mutations,
            drugs=drugs,
        )
        conf = self._confidence(node_id, chain)
        return CausalExplanation(
            node_id=node_id,
            node_name=name,
            kind=kind,
            percent_change=pct,
            control_final=control_f,
            perturbed_final=pert_f,
            narrative=narrative,
            chain=chain,
            mutations=mutations,
            drugs=drugs,
            pathways=pathways,
            confidence=conf,
            metadata={"prefer_kind": prefer_kind},
        )

    def _build_causal_chain(self, node_id: str, *, kind: str) -> List[CausalChainStep]:
        """Walk immediate upstream regulators ranked by attribution / edge weight."""
        steps: List[CausalChainStep] = []
        in_edges = self.network.in_edges(node_id)
        ranked = sorted(
            in_edges,
            key=lambda e: (
                -abs(self.attributions.get(e.source_id, 0.0)),
                -e.weight,
                e.source_id,
            ),
        )
        for edge in ranked[:4]:
            src = self.network.registry.get(edge.source_id)
            tgt = self.network.registry.get(edge.target_id)
            src_name = _display_name(src)
            tgt_name = _display_name(tgt)
            itype = edge.interaction_type.value
            inhibitory = edge.interaction_type.is_inhibitory
            if kind == "activation":
                if inhibitory:
                    evidence = (
                        f"{src_name} normally restrains {tgt_name}; reduced inhibitory "
                        f"tone or bypass allows {tgt_name} activity to rise."
                    )
                else:
                    evidence = (
                        f"{src_name} drives {tgt_name} via {itype}, elevating "
                        f"downstream signalling flux."
                    )
            else:
                if inhibitory:
                    evidence = (
                        f"{src_name} competitively / catalytically suppresses {tgt_name} "
                        f"({itype}), keeping the target inactive."
                    )
                else:
                    evidence = (
                        f"Loss or blockade of {src_name}→{tgt_name} {itype} input "
                        f"starves {tgt_name} of activating signal."
                    )
            steps.append(
                CausalChainStep(
                    source_name=src_name,
                    target_name=tgt_name,
                    interaction=itype,
                    evidence=evidence,
                    attribution=self.attributions.get(edge.source_id),
                )
            )
        return steps

    def _collect_mutations(self, node_id: str, *, upstream: bool) -> List[str]:
        found: List[str] = []
        seeds = [node_id]
        if upstream:
            # BFS up to depth 4 so RAS→RAF→MEK→ERK mutations are visible
            frontier = list(self.network.predecessors(node_id))
            seen_nodes = {node_id}
            depth = 0
            while frontier and depth < 4:
                nxt: List[str] = []
                for pred in frontier:
                    if pred in seen_nodes:
                        continue
                    seen_nodes.add(pred)
                    seeds.append(pred)
                    nxt.extend(self.network.predecessors(pred))
                frontier = nxt
                depth += 1
        seen: set[str] = set()
        for nid in seeds:
            if nid in seen:
                continue
            seen.add(nid)
            entity = self.network.registry.get(nid)
            clinical = getattr(entity, "clinical", None)
            if clinical is None:
                continue
            for mut in getattr(clinical, "somatic_mutations", []) or []:
                if mut not in found:
                    found.append(mut)
        return found

    def _collect_drug_names(self, node_id: str, *, upstream: bool) -> List[str]:
        names: List[str] = []
        seeds = [node_id]
        if upstream:
            seeds.extend(self.network.predecessors(node_id))
        seen: set[str] = set()
        for nid in seeds:
            if nid in seen:
                continue
            seen.add(nid)
            entity = self.network.registry.get(nid)
            drugs = getattr(entity, "drugs", None) or []
            for d in drugs:
                label = d.name if isinstance(d, DrugAssociation) else str(d)
                if label not in names:
                    names.append(label)
            # metadata fallback used by older perturbation hooks
            meta_drug = (getattr(entity, "metadata", {}) or {}).get("drug")
            if meta_drug and str(meta_drug) not in names:
                names.append(str(meta_drug))
        return names

    def _compose_narrative(
        self,
        *,
        entity: BiologicalEntity,
        name: str,
        kind: str,
        pct: float,
        chain: Sequence[CausalChainStep],
        mutations: Sequence[str],
        drugs: Sequence[str],
    ) -> str:
        pct_s = _format_pct(pct)
        mut_phrase = _mutation_phrase(mutations)
        drug_phrase = _drug_phrase(drugs)

        if kind == "activation":
            lead = f"{name} became hyperactive ({pct_s})"
            if mut_phrase:
                # Prefer classic RAS→MAPK wording when KRAS/RAS appears
                cascade = self._cascade_phrase(chain)
                if any("RAS" in m.upper() or "KRAS" in m.upper() or "G12" in m.upper() for m in mutations):
                    body = (
                        f"because {mut_phrase} locked RAS in a GTP-bound state, "
                        f"continuously driving {cascade}."
                    )
                else:
                    body = f"because {mut_phrase} constitutively energised upstream input"
                    if cascade:
                        body += f", driving {cascade}."
                    else:
                        body += "."
            elif drug_phrase:
                body = (
                    f"despite {drug_phrase}; residual or bypass signalling still elevated "
                    f"{name} relative to control."
                )
            elif chain:
                drivers = " → ".join(
                    [chain[0].source_name] + [s.target_name for s in chain[:3]]
                )
                body = f"because upstream flux through {drivers} increased under perturbation."
            else:
                body = "because local production / reduced clearance raised steady-state abundance."
            return f"{lead} {body}"

        # inactivation
        lead = f"{name} remained inactive" if pct > -5 else f"{name} was suppressed ({pct_s})"
        if drug_phrase:
            # Prefer naming the drug's direct target when it is upstream
            target_hint = name
            for pred_id in self.network.predecessors(entity.entity_id):
                pred = self.network.registry.get(pred_id)
                pred_drugs = getattr(pred, "drugs", None) or []
                pred_names = {
                    d.name if isinstance(d, DrugAssociation) else str(d) for d in pred_drugs
                }
                if any(d in pred_names for d in drugs):
                    target_hint = _display_name(pred)
                    break
            if isinstance(entity, Protein) and entity.drugs:
                # Drug annotated on the explained node itself
                target_hint = name
            return f"{lead} because {target_hint} was competitively blocked by {drug_phrase}."
        if mut_phrase and any("loss" in m.lower() or "null" in m.lower() for m in mutations):
            return f"{lead} because {mut_phrase} abolished required activating input."
        if chain:
            inhibitors = [s for s in chain if s.interaction in {
                InteractionType.INHIBITION.value,
                InteractionType.DEPHOSPHORYLATION.value,
                InteractionType.DEGRADATION.value,
                InteractionType.UBIQUITINATION.value,
            }]
            if inhibitors:
                s0 = inhibitors[0]
                return (
                    f"{lead} because {s0.source_name} continued to repress {name} "
                    f"via {s0.interaction}."
                )
            return (
                f"{lead} because activating input from "
                f"{chain[0].source_name} was insufficient under perturbation."
            )
        return f"{lead} because no upstream activator reached the engagement threshold."

    def _cascade_phrase(self, chain: Sequence[CausalChainStep]) -> str:
        if not chain:
            return "downstream phosphorylation"
        # Prefer MAPK-style labels when present in the chain names
        names = [chain[0].source_name] + [s.target_name for s in chain]
        # Deduplicate while preserving order
        ordered: List[str] = []
        for n in names:
            if n not in ordered:
                ordered.append(n)
        # Classic RAF → MEK → ERK if those symbols appear anywhere upstream
        mapk = [s for s in ("RAF", "MEK", "ERK") if any(s in x.upper() for x in ordered)]
        if len(mapk) >= 2:
            return " → ".join(mapk) + " phosphorylation"
        return " → ".join(ordered[:4]) + (" phosphorylation" if len(ordered) >= 2 else "")

    def _confidence(self, node_id: str, chain: Sequence[CausalChainStep]) -> float:
        base = 0.35
        if chain:
            base += 0.25
        if any(s.attribution is not None for s in chain):
            base += 0.2
        if self.network.node_pathways(node_id):
            base += 0.1
        attr = abs(self.attributions.get(node_id, 0.0))
        if attr > 0:
            base += min(0.2, 0.05 + 0.15 * math.tanh(attr))
        return max(0.0, min(1.0, base))

    def _build_overview(
        self,
        activated: Sequence[CausalExplanation],
        inactivated: Sequence[CausalExplanation],
        stable: Sequence[str],
    ) -> str:
        parts: List[str] = [
            f"Comparing {self.control_label} vs {self.perturbed_label}:"
        ]
        if activated:
            names = ", ".join(e.node_name for e in activated[:4])
            parts.append(
                f"hyperactivated nodes include {names}"
                + ("." if len(activated) <= 4 else f" (+{len(activated) - 4} more).")
            )
        if inactivated:
            names = ", ".join(e.node_name for e in inactivated[:4])
            parts.append(
                f"suppressed nodes include {names}"
                + ("." if len(inactivated) <= 4 else f" (+{len(inactivated) - 4} more).")
            )
        if not activated and not inactivated:
            parts.append("no node exceeded the configured activity-change threshold.")
        elif stable:
            parts.append(f"{len(stable)} node(s) remained relatively stable.")
        # Stitch into one paragraph
        if len(parts) == 1:
            return parts[0]
        return parts[0] + " " + " ".join(parts[1:])
