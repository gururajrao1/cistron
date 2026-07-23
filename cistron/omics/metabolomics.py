"""
Metabolic Flux Balance Analysis (FBA) — pure-Python stoichiometric solver.

Builds metabolite×reaction matrix S, solves steady-state fluxes under bounds,
and couples flux limits to signaling ODE rates via Michaelis–Menten multipliers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

from cistron.components import BiologicalEntity
from cistron.structures import KineticScaleFactors
from cistron.topology import SignalingNetwork


@dataclass(frozen=True)
class Metabolite:
    """Named metabolite pool (ATP, NADH, …)."""

    metabolite_id: str
    name: str = ""
    compartment: str = "cytosol"

    def __post_init__(self) -> None:
        if not self.metabolite_id:
            raise ValueError("metabolite_id must be non-empty")


@dataclass(frozen=True)
class MetabolicReaction:
    """
    Reaction with stoichiometric coefficients and flux bounds.

    ``stoich`` maps metabolite_id → coefficient (negative = substrate).
    """

    reaction_id: str
    stoich: Dict[str, float]
    lb: float = 0.0
    ub: float = 1000.0
    objective_coeff: float = 0.0
    name: str = ""

    def __post_init__(self) -> None:
        if not self.reaction_id:
            raise ValueError("reaction_id must be non-empty")
        if self.lb > self.ub:
            raise ValueError("lb must be <= ub")
        if not self.stoich:
            raise ValueError("stoich must be non-empty")


@dataclass
class MetabolicNetwork:
    """Stoichiometric metabolic model."""

    metabolites: List[Metabolite] = field(default_factory=list)
    reactions: List[MetabolicReaction] = field(default_factory=list)
    name: str = "metabolic"

    def metabolite_index(self) -> Dict[str, int]:
        return {m.metabolite_id: i for i, m in enumerate(self.metabolites)}

    def reaction_index(self) -> Dict[str, int]:
        return {r.reaction_id: i for i, r in enumerate(self.reactions)}

    def stoichiometric_matrix(self) -> List[List[float]]:
        """Return S as list-of-rows (n_metabolites × n_reactions)."""
        m_idx = self.metabolite_index()
        n_m = len(self.metabolites)
        n_r = len(self.reactions)
        S = [[0.0] * n_r for _ in range(n_m)]
        for j, rxn in enumerate(self.reactions):
            for met, coeff in rxn.stoich.items():
                if met not in m_idx:
                    raise KeyError(f"metabolite {met!r} not in network")
                S[m_idx[met]][j] += float(coeff)
        return S

    def objective(self) -> List[float]:
        return [float(r.objective_coeff) for r in self.reactions]

    def bounds(self) -> Tuple[List[float], List[float]]:
        return [float(r.lb) for r in self.reactions], [float(r.ub) for r in self.reactions]


@dataclass(frozen=True)
class FBAResult:
    """Optimal (or near-optimal) flux distribution."""

    fluxes: Dict[str, float]
    objective_value: float
    residual_norm: float
    converged: bool
    iterations: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def flux(self, reaction_id: str) -> float:
        return float(self.fluxes.get(reaction_id, 0.0))


def _matvec(S: Sequence[Sequence[float]], v: Sequence[float]) -> List[float]:
    return [sum(row[j] * v[j] for j in range(len(v))) for row in S]


def _matvec_t(S: Sequence[Sequence[float]], y: Sequence[float]) -> List[float]:
    n_r = len(S[0]) if S else 0
    out = [0.0] * n_r
    for i, row in enumerate(S):
        yi = y[i]
        for j in range(n_r):
            out[j] += row[j] * yi
    return out


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def _project_nullspace(
    S: Sequence[Sequence[float]],
    v: List[float],
    *,
    steps: int = 8,
) -> List[float]:
    """
    Approximate projection onto {v | S v = 0} via gradient descent on ||Sv||².
    """
    x = list(v)
    for _ in range(steps):
        r = _matvec(S, x)  # residual Sv
        # grad = 2 S^T S v
        g = _matvec_t(S, r)
        g2 = _dot(g, g)
        if g2 < 1e-18:
            break
        # step length from exact line search on quadratic ||S(x - a g)||²
        Sg = _matvec(S, g)
        denom = _dot(Sg, Sg)
        if denom < 1e-18:
            break
        alpha = _dot(r, Sg) / denom
        x = [xi - alpha * gi for xi, gi in zip(x, g)]
    return x


def solve_fba(
    network: MetabolicNetwork,
    *,
    max_iter: int = 4000,
    tol: float = 1e-7,
    step: float = 0.15,
) -> FBAResult:
    """
    Maximize c·v subject to S v ≈ 0 and lb ≤ v ≤ ub.

    Pure-Python projected gradient ascent — suitable for small pathway models
    (ATP / NADH / lactate / glutamine) without native LP solvers.
    """
    S = network.stoichiometric_matrix()
    c = network.objective()
    lb, ub = network.bounds()
    n = len(c)
    if n == 0:
        return FBAResult(fluxes={}, objective_value=0.0, residual_norm=0.0, converged=True, iterations=0)

    # Initialize at bound midpoints (or 0 if straddling)
    v = [0.5 * (lo + hi) if lo < hi else lo for lo, hi in zip(lb, ub)]
    v = _project_nullspace(S, v)
    v = [min(ub[j], max(lb[j], v[j])) for j in range(n)]

    best_v = list(v)
    best_obj = _dot(c, v)
    converged = False
    it = 0
    residual = _norm(_matvec(S, v))

    for it in range(1, max_iter + 1):
        # Ascend objective
        v = [v[j] + step * c[j] for j in range(n)]
        # Clamp bounds
        v = [min(ub[j], max(lb[j], v[j])) for j in range(n)]
        # Re-project to steady state
        v = _project_nullspace(S, v, steps=6)
        v = [min(ub[j], max(lb[j], v[j])) for j in range(n)]

        residual = _norm(_matvec(S, v))
        obj = _dot(c, v)
        if obj > best_obj and residual < max(tol * 100, 1e-4):
            best_obj = obj
            best_v = list(v)
        if residual < tol and abs(obj - best_obj) < tol:
            converged = True
            best_v = list(v)
            best_obj = obj
            break
        # Mild step decay for stability
        if it % 500 == 0:
            step *= 0.85

    fluxes = {rxn.reaction_id: best_v[j] for j, rxn in enumerate(network.reactions)}
    return FBAResult(
        fluxes=fluxes,
        objective_value=best_obj,
        residual_norm=_norm(_matvec(S, best_v)),
        converged=converged or residual < 1e-4,
        iterations=it,
        metadata={"n_metabolites": len(network.metabolites), "n_reactions": n},
    )


def michaelis_menten_multiplier(
    flux: float,
    *,
    km: float = 1.0,
    vmax_frac: float = 1.0,
    floor: float = 0.05,
) -> float:
    """
    Map metabolic flux → ODE rate multiplier via MM saturation.

    ``rate_scaled = rate * (vmax_frac * flux / (km + flux))``, floored.
    """
    f = max(0.0, float(flux))
    k = max(1e-12, float(km))
    sat = f / (k + f)
    return max(floor, float(vmax_frac) * sat)


@dataclass(frozen=True)
class MetabolicCoupling:
    """Wire a metabolic flux to a signaling node / edge kinetic axis."""

    reaction_id: str
    target: str
    """Network entity name (protein / gene)."""
    axis: str = "kcat"
    """One of: kcat, km, production, binding, edge."""
    km: float = 1.0
    vmax_frac: float = 1.0
    floor: float = 0.08


@dataclass
class MetabolomicProfile:
    """FBA model + coupling rules for one sample."""

    sample_id: str = "sample"
    network: MetabolicNetwork = field(default_factory=MetabolicNetwork)
    couplings: List[MetabolicCoupling] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetabolicFeedbackState:
    """Per-target kinetic scales derived from FBA fluxes."""

    target: str
    scales: KineticScaleFactors
    multipliers: Dict[str, float]
    source_fluxes: Dict[str, float]


class MetabolicCoupler:
    """Solve FBA and stamp Michaelis–Menten feedback onto a signaling network."""

    def __init__(self, *, also_edges: bool = True) -> None:
        self.also_edges = also_edges

    def solve(self, profile: MetabolomicProfile) -> FBAResult:
        return solve_fba(profile.network)

    def compute_feedback(
        self, profile: MetabolomicProfile, fba: Optional[FBAResult] = None
    ) -> Dict[str, MetabolicFeedbackState]:
        result = fba or self.solve(profile)
        by_target: Dict[str, List[Tuple[MetabolicCoupling, float]]] = {}
        for coup in profile.couplings:
            flux = result.flux(coup.reaction_id)
            mult = michaelis_menten_multiplier(
                flux, km=coup.km, vmax_frac=coup.vmax_frac, floor=coup.floor
            )
            by_target.setdefault(coup.target.upper(), []).append((coup, mult))

        states: Dict[str, MetabolicFeedbackState] = {}
        for target, items in by_target.items():
            kcat = km = prod = bind = edge_m = 1.0
            mults: Dict[str, float] = {}
            fluxes: Dict[str, float] = {}
            for coup, mult in items:
                mults[coup.reaction_id] = mult
                fluxes[coup.reaction_id] = result.flux(coup.reaction_id)
                if coup.axis == "kcat":
                    kcat *= mult
                elif coup.axis == "km":
                    km *= max(0.2, 2.0 - mult)
                elif coup.axis == "production":
                    prod *= mult
                elif coup.axis == "binding":
                    bind *= mult
                elif coup.axis == "edge":
                    edge_m *= mult
                else:
                    raise ValueError(f"unknown coupling axis {coup.axis!r}")
            states[target] = MetabolicFeedbackState(
                target=target,
                scales=KineticScaleFactors(
                    kcat_scale=max(1e-4, kcat),
                    km_scale=max(1e-4, km),
                    binding_scale=max(1e-4, bind),
                    production_scale=max(1e-4, prod),
                ),
                multipliers={**mults, "_edge": edge_m},
                source_fluxes=fluxes,
            )
        return states

    def apply(
        self,
        signaling: SignalingNetwork,
        profile: MetabolomicProfile,
        *,
        gene_aliases: Optional[Mapping[str, str]] = None,
        fba: Optional[FBAResult] = None,
    ) -> Tuple[FBAResult, Dict[str, MetabolicFeedbackState]]:
        result = fba or self.solve(profile)
        states = self.compute_feedback(profile, result)
        name_map = _entity_name_index(signaling)
        aliases = {k.upper(): v for k, v in (gene_aliases or {}).items()}

        for target, state in states.items():
            name = aliases.get(target, target)
            ent = _resolve_entity(name_map, name)
            if ent is None:
                continue
            sc = state.scales
            k = ent.kinetics
            ent.kinetics = k.with_updates(
                vmax=max(0.0, k.vmax * sc.kcat_scale),
                km=max(1e-9, k.km * sc.km_scale),
                production_rate=max(0.0, k.production_rate * sc.production_scale),
                binding_affinity=max(0.0, k.binding_affinity * sc.binding_scale),
            )
            ent.metadata["fba_kcat_scale"] = sc.kcat_scale
            ent.metadata["fba_fluxes"] = dict(state.source_fluxes)
            edge_m = float(state.multipliers.get("_edge", 1.0))
            if self.also_edges:
                scale = sc.kcat_scale * (edge_m if edge_m != 1.0 else 1.0)
                for edge in signaling.out_edges(ent.entity_id):
                    edge.rate_constant = max(0.0, edge.rate_constant * scale)
        return result, states


def build_core_energy_network() -> MetabolicNetwork:
    """
    Minimal ATP / NADH / lactate / glutamine core for demo FBA.

    Reactions (irreversible unless noted):
    - glycolysis: Glc → 2 Lac + 2 ATP + 2 NADH  (lumped)
    - oxphos: NADH + ADP → ATP (respiration)
    - glutaminolysis: Gln → ATP + NADH
    - ATP maintenance: ATP → ∅
    - lactate export: Lac → ∅
    - biomass proxy objective on ATP_synth effective drain
    """
    mets = [
        Metabolite("glc", "glucose"),
        Metabolite("lac", "lactate"),
        Metabolite("atp", "ATP"),
        Metabolite("adp", "ADP"),
        Metabolite("nadh", "NADH"),
        Metabolite("nad", "NAD+"),
        Metabolite("gln", "glutamine"),
    ]
    rxns = [
        MetabolicReaction(
            "glycolysis",
            {"glc": -1.0, "lac": 2.0, "adp": -2.0, "atp": 2.0, "nad": -2.0, "nadh": 2.0},
            lb=0.0,
            ub=10.0,
            objective_coeff=0.0,
            name="lumped glycolysis",
        ),
        MetabolicReaction(
            "respiration",
            {"nadh": -1.0, "nad": 1.0, "adp": -2.5, "atp": 2.5},
            lb=0.0,
            ub=8.0,
            objective_coeff=0.0,
            name="OXPHOS",
        ),
        MetabolicReaction(
            "glutaminolysis",
            {"gln": -1.0, "adp": -1.0, "atp": 1.0, "nad": -0.5, "nadh": 0.5},
            lb=0.0,
            ub=5.0,
            objective_coeff=0.0,
        ),
        MetabolicReaction(
            "atp_maintenance",
            {"atp": -1.0, "adp": 1.0},
            lb=0.5,
            ub=12.0,
            objective_coeff=1.0,  # maximize useful ATP turnover
            name="ATP demand / biomass proxy",
        ),
        MetabolicReaction(
            "lac_export",
            {"lac": -1.0},
            lb=0.0,
            ub=20.0,
            objective_coeff=0.0,
        ),
        # Exchange / uptake
        MetabolicReaction("glc_uptake", {"glc": 1.0}, lb=0.0, ub=6.0),
        MetabolicReaction("gln_uptake", {"gln": 1.0}, lb=0.0, ub=4.0),
        # Cofactor balances closed by pairs above; add leak drains for numerics
        MetabolicReaction("nadh_sink", {"nadh": -1.0, "nad": 1.0}, lb=0.0, ub=5.0),
    ]
    return MetabolicNetwork(metabolites=mets, reactions=rxns, name="core_energy")


def make_demo_metabolomic_profile(sample_id: str = "MET_DEMO") -> MetabolomicProfile:
    net = build_core_energy_network()
    return MetabolomicProfile(
        sample_id=sample_id,
        network=net,
        couplings=[
            MetabolicCoupling("atp_maintenance", "MEK", axis="kcat", km=1.5, vmax_frac=1.2),
            MetabolicCoupling("glycolysis", "ERK", axis="production", km=2.0, vmax_frac=1.0),
            MetabolicCoupling("respiration", "EGFR", axis="kcat", km=1.0, vmax_frac=1.1),
            MetabolicCoupling("glutaminolysis", "RAS", axis="binding", km=1.2, vmax_frac=1.0),
        ],
    )


def _entity_name_index(network: SignalingNetwork) -> Dict[str, BiologicalEntity]:
    idx: Dict[str, BiologicalEntity] = {}
    for ent in network.registry.entities():
        idx[ent.name.upper()] = ent
        gs = ent.metadata.get("gene_symbol")
        if isinstance(gs, str) and gs:
            idx[gs.upper()] = ent
    return idx


def _resolve_entity(
    name_map: Mapping[str, BiologicalEntity], name: str
) -> Optional[BiologicalEntity]:
    key = name.upper()
    if key in name_map:
        return name_map[key]
    return name_map.get(key.split("-")[0].split("_")[0])
