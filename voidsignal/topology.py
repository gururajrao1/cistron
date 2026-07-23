"""
Graph-based signalling-network topology for VOIDSIGNAL.

Nodes are biological entity IDs resolved through an :class:`EntityRegistry`.
Directed, typed edges encode regulatory / biochemical interactions with
kinetic annotations so the same graph drives Boolean updating rules and
mass-action ODE construction.

Designed for later plugging into NetworkX / graph-tool / visualisation
pipelines via :meth:`SignalingNetwork.to_edge_list` and
:meth:`SignalingNetwork.adjacency_matrix`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)
import uuid

from voidsignal.components import BiologicalEntity, EntityRegistry, EntityType


class InteractionType(Enum):
    """
    Directed edge semantics.

    Inhibitory types are those for which Boolean targets tend to be repressed
    and ODE contributions enter with a negative sign (or as saturating
    denominators in competitive models).
    """

    ACTIVATION = "activation"
    INHIBITION = "inhibition"
    PHOSPHORYLATION = "phosphorylation"
    DEPHOSPHORYLATION = "dephosphorylation"
    BINDING = "binding"
    DISSOCIATION = "dissociation"
    TRANSCRIPTION = "transcription"
    TRANSLATION = "translation"
    UBIQUITINATION = "ubiquitination"
    DEGRADATION = "degradation"
    TRANSLOCATION = "translocation"
    CATALYSIS = "catalysis"

    @property
    def is_inhibitory(self) -> bool:
        return self in {
            InteractionType.INHIBITION,
            InteractionType.DEPHOSPHORYLATION,
            InteractionType.UBIQUITINATION,
            InteractionType.DEGRADATION,
        }

    @property
    def is_catalytic(self) -> bool:
        return self in {
            InteractionType.PHOSPHORYLATION,
            InteractionType.DEPHOSPHORYLATION,
            InteractionType.CATALYSIS,
            InteractionType.UBIQUITINATION,
        }


class LogicGate(Enum):
    """
    How multiple incoming edges are combined for Boolean node updates.

    AND  — all activating inputs must be ON and no inhibitor ON
    OR   — any activator ON (and inhibitors can veto if ``inhibitor_veto``)
    MAJORITY — more activators ON than inhibitors ON
    NOT  — unary: output is negation of the single upstream input
    COPY — unary: output mirrors the single upstream input
    """

    AND = "and"
    OR = "or"
    MAJORITY = "majority"
    NOT = "not"
    COPY = "copy"


@dataclass
class InteractionEdge:
    """
    Directed typed interaction ``source → target``.

    Attributes
    ----------
    weight :
        Soft strength ∈ (0, ∞). Boolean layer treats weight ≥ 0.5 as a
        participating input; ODE layer multiplies rate laws by weight.
    rate_constant :
        Mass-action microscopic rate *k* for this channel.
    hill_coefficient :
        Cooperativity *n* in Hill-type transfer functions.
    ec50 :
        Half-maximal effective concentration for Hill activation / inhibition.
    delay :
        Discrete Boolean update delay in steps (0 = immediate).
    logic_role :
        Optional tag used by custom Boolean rules (``activator`` / ``inhibitor``).
    """

    source_id: str
    target_id: str
    interaction_type: InteractionType
    edge_id: str = ""
    weight: float = 1.0
    rate_constant: float = 1.0
    hill_coefficient: float = 1.0
    ec50: float = 0.5
    delay: int = 0
    logic_role: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    active: bool = True

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise ValueError("source_id and target_id are required")
        if not self.edge_id:
            self.edge_id = f"edge_{uuid.uuid4().hex[:12]}"
        if self.weight < 0.0:
            raise ValueError("weight must be non-negative")
        if self.rate_constant < 0.0:
            raise ValueError("rate_constant must be non-negative")
        if self.hill_coefficient <= 0.0:
            raise ValueError("hill_coefficient must be positive")
        if self.ec50 <= 0.0:
            raise ValueError("ec50 must be positive")
        if self.delay < 0:
            raise ValueError("delay must be non-negative")
        if self.logic_role is None:
            self.logic_role = "inhibitor" if self.interaction_type.is_inhibitory else "activator"

    def hill_activation(self, source_concentration: float) -> float:
        """
        Hill activation transfer:

            f(x) = w · x^n / (K^n + x^n)
        """
        if source_concentration < 0.0:
            raise ValueError("source_concentration must be non-negative")
        n = self.hill_coefficient
        k_n = self.ec50 ** n
        x_n = source_concentration ** n
        return self.weight * x_n / (k_n + x_n) if (k_n + x_n) > 0.0 else 0.0

    def hill_inhibition(self, source_concentration: float) -> float:
        """
        Hill repression transfer (multiplicative gated form):

            f(x) = w · K^n / (K^n + x^n)
        """
        if source_concentration < 0.0:
            raise ValueError("source_concentration must be non-negative")
        n = self.hill_coefficient
        k_n = self.ec50 ** n
        x_n = source_concentration ** n
        return self.weight * k_n / (k_n + x_n) if (k_n + x_n) > 0.0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "interaction_type": self.interaction_type.value,
            "weight": self.weight,
            "rate_constant": self.rate_constant,
            "hill_coefficient": self.hill_coefficient,
            "ec50": self.ec50,
            "delay": self.delay,
            "logic_role": self.logic_role,
            "active": self.active,
            "metadata": dict(self.metadata),
        }


@dataclass
class NodeLogic:
    """Per-node Boolean update rule configuration."""

    gate: LogicGate = LogicGate.OR
    inhibitor_veto: bool = True
    """If True, any ON inhibitor forces the node OFF regardless of activators."""
    threshold: float = 0.5
    """Minimum edge weight for an input to participate in Boolean logic."""


class SignalingNetwork:
    """
    Directed multigraph of signalling interactions.

    Storage is adjacency-list based for O(1) neighbour queries and sparse
    iteration — appropriate for typical pathway sizes (10²–10⁴ nodes) and
    compatible with future centrality / community algorithms that walk
    adjacency structures.
    """

    # Canonical multi-pathway hubs used when auto-annotating from gene symbols.
    CANONICAL_PATHWAYS: Dict[str, Tuple[str, ...]] = {
        "MAPK": ("EGFR", "RAS", "RAF", "MEK", "ERK", "KRAS", "HRAS", "NRAS", "BRAF", "MAP2K1", "MAPK1"),
        "PI3K-AKT": ("EGFR", "PI3K", "PIK3CA", "PIP3", "PDK1", "AKT", "AKT1", "MTOR", "PTEN", "RAS"),
        "JAK-STAT": ("JAK", "JAK1", "JAK2", "STAT", "STAT1", "STAT3", "CYTOKINE", "IL6R", "TP53"),
    }

    def __init__(self, registry: Optional[EntityRegistry] = None, name: str = "network") -> None:
        self.name = name
        self.registry: EntityRegistry = registry if registry is not None else EntityRegistry()
        self._edges: Dict[str, InteractionEdge] = {}
        self._out: Dict[str, Set[str]] = defaultdict(set)  # node → edge_ids
        self._in: Dict[str, Set[str]] = defaultdict(set)
        self._node_logic: Dict[str, NodeLogic] = {}
        self._nodes: Set[str] = set()
        self._pathways: Dict[str, Set[str]] = {}
        """pathway_name → set of entity_ids."""
        self.metadata: Dict[str, Any] = {}

    # -- node API ------------------------------------------------------------

    def add_node(self, entity: BiologicalEntity, logic: Optional[NodeLogic] = None) -> str:
        """Register an entity (if needed) and place it on the graph."""
        if entity.entity_id not in self.registry:
            self.registry.register(entity)
        self._nodes.add(entity.entity_id)
        if logic is not None:
            self._node_logic[entity.entity_id] = logic
        elif entity.entity_id not in self._node_logic:
            self._node_logic[entity.entity_id] = NodeLogic()
        return entity.entity_id

    def add_node_id(self, entity_id: str, logic: Optional[NodeLogic] = None) -> str:
        """Add a node that already exists in the registry."""
        if entity_id not in self.registry:
            raise KeyError(f"Entity {entity_id!r} is not in the registry")
        self._nodes.add(entity_id)
        if logic is not None:
            self._node_logic[entity_id] = logic
        elif entity_id not in self._node_logic:
            self._node_logic[entity_id] = NodeLogic()
        return entity_id

    def remove_node(self, entity_id: str) -> None:
        if entity_id not in self._nodes:
            raise KeyError(f"Node {entity_id!r} not in network")
        incident = list(self._out[entity_id] | self._in[entity_id])
        for edge_id in incident:
            self.remove_edge(edge_id)
        self._nodes.discard(entity_id)
        self._node_logic.pop(entity_id, None)
        self._out.pop(entity_id, None)
        self._in.pop(entity_id, None)

    def has_node(self, entity_id: str) -> bool:
        return entity_id in self._nodes

    def nodes(self) -> List[str]:
        return sorted(self._nodes)

    def set_node_logic(self, entity_id: str, logic: NodeLogic) -> None:
        if entity_id not in self._nodes:
            raise KeyError(f"Node {entity_id!r} not in network")
        self._node_logic[entity_id] = logic

    def get_node_logic(self, entity_id: str) -> NodeLogic:
        if entity_id not in self._nodes:
            raise KeyError(f"Node {entity_id!r} not in network")
        return self._node_logic[entity_id]

    # -- edge API ------------------------------------------------------------

    def add_edge(self, edge: InteractionEdge) -> str:
        """Insert a directed interaction; auto-creates endpoint nodes if registered."""
        for endpoint in (edge.source_id, edge.target_id):
            if endpoint not in self.registry:
                raise KeyError(f"Endpoint {endpoint!r} is not in the registry")
            self._nodes.add(endpoint)
            if endpoint not in self._node_logic:
                self._node_logic[endpoint] = NodeLogic()
        if edge.edge_id in self._edges:
            raise KeyError(f"Duplicate edge_id {edge.edge_id!r}")
        self._edges[edge.edge_id] = edge
        self._out[edge.source_id].add(edge.edge_id)
        self._in[edge.target_id].add(edge.edge_id)
        return edge.edge_id

    def connect(
        self,
        source_id: str,
        target_id: str,
        interaction_type: InteractionType,
        **kwargs: Any,
    ) -> InteractionEdge:
        """Convenience constructor for :class:`InteractionEdge`."""
        edge = InteractionEdge(
            source_id=source_id,
            target_id=target_id,
            interaction_type=interaction_type,
            **kwargs,
        )
        self.add_edge(edge)
        return edge

    def remove_edge(self, edge_id: str) -> InteractionEdge:
        if edge_id not in self._edges:
            raise KeyError(f"Unknown edge_id {edge_id!r}")
        edge = self._edges.pop(edge_id)
        self._out[edge.source_id].discard(edge_id)
        self._in[edge.target_id].discard(edge_id)
        return edge

    def get_edge(self, edge_id: str) -> InteractionEdge:
        try:
            return self._edges[edge_id]
        except KeyError as exc:
            raise KeyError(f"Unknown edge_id {edge_id!r}") from exc

    def edges(self) -> List[InteractionEdge]:
        return list(self._edges.values())

    def active_edges(self) -> List[InteractionEdge]:
        return [e for e in self._edges.values() if e.active]

    # -- adjacency queries ---------------------------------------------------

    def out_edges(self, entity_id: str) -> List[InteractionEdge]:
        return [self._edges[eid] for eid in self._out.get(entity_id, set())]

    def in_edges(self, entity_id: str) -> List[InteractionEdge]:
        return [self._edges[eid] for eid in self._in.get(entity_id, set())]

    def successors(self, entity_id: str) -> List[str]:
        return [self._edges[eid].target_id for eid in self._out.get(entity_id, set())]

    def predecessors(self, entity_id: str) -> List[str]:
        return [self._edges[eid].source_id for eid in self._in.get(entity_id, set())]

    def degree(self, entity_id: str) -> Tuple[int, int]:
        """Return ``(in_degree, out_degree)``."""
        return (len(self._in.get(entity_id, set())), len(self._out.get(entity_id, set())))

    def total_degree(self, entity_id: str) -> int:
        indeg, outdeg = self.degree(entity_id)
        return indeg + outdeg

    # -- structural analytics ------------------------------------------------

    def find_hubs(self, top_k: int = 5, mode: str = "total") -> List[Tuple[str, int]]:
        """
        Identify high-degree hub nodes.

        Parameters
        ----------
        top_k :
            Number of hubs to return.
        mode :
            ``total`` | ``in`` | ``out`` degree ranking.
        """
        if top_k < 1:
            raise ValueError("top_k must be ≥ 1")
        scores: List[Tuple[str, int]] = []
        for nid in self._nodes:
            indeg, outdeg = self.degree(nid)
            if mode == "total":
                score = indeg + outdeg
            elif mode == "in":
                score = indeg
            elif mode == "out":
                score = outdeg
            else:
                raise ValueError("mode must be 'total', 'in', or 'out'")
            scores.append((nid, score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        return scores[:top_k]

    # -- multi-pathway crosstalk ---------------------------------------------

    def annotate_pathway(self, pathway_name: str, node_ids: Iterable[str]) -> None:
        """Register or extend a named pathway membership set on this network."""
        name = pathway_name.strip()
        if not name:
            raise ValueError("pathway_name must be non-empty")
        ids = set(node_ids)
        unknown = ids - self._nodes
        if unknown:
            raise KeyError(f"Unknown pathway nodes: {sorted(unknown)}")
        self._pathways.setdefault(name, set()).update(ids)
        for nid in ids:
            entity = self.registry.get(nid)
            membership = getattr(entity, "pathway_membership", None)
            if isinstance(membership, list) and name not in membership:
                membership.append(name)

    def pathway_names(self) -> List[str]:
        return sorted(self._pathways)

    def pathway_nodes(self, pathway_name: str) -> Set[str]:
        if pathway_name not in self._pathways:
            raise KeyError(f"Unknown pathway {pathway_name!r}")
        return set(self._pathways[pathway_name])

    def auto_annotate_canonical_pathways(self) -> Dict[str, Set[str]]:
        """
        Tag nodes into MAPK / PI3K-AKT / JAK-STAT from gene symbols / names.

        Shared hubs (EGFR, RAS, TP53, …) land in multiple pathway sets so
        crosstalk routing can bridge signals across cascades.
        """
        symbol_index: Dict[str, str] = {}
        for nid in self._nodes:
            entity = self.registry.get(nid)
            symbol = getattr(entity, "gene_symbol", None) or entity.name
            symbol_index[str(symbol).upper()] = nid
            for alias in getattr(entity, "aliases", []) or []:
                symbol_index[str(alias).upper()] = nid

        assigned: Dict[str, Set[str]] = {}
        for pathway, symbols in self.CANONICAL_PATHWAYS.items():
            hits = {symbol_index[s] for s in symbols if s in symbol_index}
            if hits:
                self.annotate_pathway(pathway, hits)
                assigned[pathway] = hits
        return assigned

    def get_hub_nodes(
        self,
        top_k: int = 5,
        mode: str = "total",
        *,
        min_degree: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Degree hubs with pathway membership for Virtual Cellular Laboratory UI.

        Returns dicts ``{entity_id, name, degree, pathways}``.
        """
        hubs = self.find_hubs(top_k=max(top_k, 1), mode=mode)
        result: List[Dict[str, Any]] = []
        for nid, deg in hubs:
            if deg < min_degree:
                continue
            entity = self.registry.get(nid)
            result.append(
                {
                    "entity_id": nid,
                    "name": entity.name,
                    "gene_symbol": getattr(entity, "gene_symbol", entity.name),
                    "degree": deg,
                    "pathways": sorted(self.node_pathways(nid)),
                }
            )
            if len(result) >= top_k:
                break
        return result

    def get_bottlenecks(
        self,
        top_k: int = 5,
        *,
        sample_size: Optional[int] = None,
        min_betweenness: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        High betweenness-centrality bottlenecks (signal choke-points).

        Returns dicts ``{entity_id, name, betweenness, pathways}``.
        """
        if top_k < 1:
            raise ValueError("top_k must be ≥ 1")
        scores = self.betweenness_approximation(sample_size=sample_size)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        result: List[Dict[str, Any]] = []
        for nid, bc in ranked:
            if bc < min_betweenness:
                continue
            entity = self.registry.get(nid)
            result.append(
                {
                    "entity_id": nid,
                    "name": entity.name,
                    "gene_symbol": getattr(entity, "gene_symbol", entity.name),
                    "betweenness": bc,
                    "pathways": sorted(self.node_pathways(nid)),
                }
            )
            if len(result) >= top_k:
                break
        return result

    def node_pathways(self, entity_id: str) -> Set[str]:
        """Return pathway names that contain ``entity_id``."""
        if entity_id not in self._nodes:
            raise KeyError(f"Unknown node {entity_id!r}")
        found = {name for name, members in self._pathways.items() if entity_id in members}
        entity = self.registry.get(entity_id)
        membership = getattr(entity, "pathway_membership", None)
        if isinstance(membership, list):
            found.update(membership)
        return found

    def detect_crosstalk_switches(
        self,
        *,
        min_pathways: int = 2,
        include_bridge_edges: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Identify multi-pathway bridge nodes that route crosstalk.

        A *crosstalk switch* is either:
        1. a node annotated in ≥ ``min_pathways`` pathways (shared hub), or
        2. an endpoint of an edge that bridges two disjoint pathway sets.
        """
        if min_pathways < 2:
            raise ValueError("min_pathways must be ≥ 2")

        switches: Dict[str, Dict[str, Any]] = {}

        def _ensure(nid: str) -> Dict[str, Any]:
            if nid not in switches:
                entity = self.registry.get(nid)
                switches[nid] = {
                    "entity_id": nid,
                    "name": entity.name,
                    "gene_symbol": getattr(entity, "gene_symbol", entity.name),
                    "pathways": sorted(self.node_pathways(nid)),
                    "switch_kind": "shared_hub",
                    "bridge_edges": [],
                    "degree": self.total_degree(nid),
                }
            return switches[nid]

        for nid in self._nodes:
            pathways = self.node_pathways(nid)
            if len(pathways) >= min_pathways:
                _ensure(nid)

        if include_bridge_edges and len(self._pathways) >= 2:
            names = sorted(self._pathways)
            for i, pa in enumerate(names):
                for pb in names[i + 1 :]:
                    for edge in self.detect_crosstalk(self._pathways[pa], self._pathways[pb]):
                        for endpoint in (edge.source_id, edge.target_id):
                            rec = _ensure(endpoint)
                            if len(rec["pathways"]) < 2:
                                rec["switch_kind"] = "bridge_endpoint"
                            rec["bridge_edges"].append(
                                {
                                    "edge_id": edge.edge_id,
                                    "source_id": edge.source_id,
                                    "target_id": edge.target_id,
                                    "interaction_type": edge.interaction_type.value,
                                    "pathways": [pa, pb],
                                }
                            )

        ordered = sorted(
            switches.values(),
            key=lambda r: (-len(r["pathways"]), -r["degree"], r["name"]),
        )
        return ordered

    def detect_feedback_loops(self, max_length: int = 8) -> List[List[str]]:
        """
        Enumerate simple directed cycles up to ``max_length`` via DFS.

        Returns node-id cycles (first node repeated at the end for closure).
        Feedback / feed-forward motif discovery for larger graphs should move
        to a dedicated algorithm module; this implementation is exact for
        research-size pathways.
        """
        if max_length < 2:
            raise ValueError("max_length must be ≥ 2")
        cycles: List[List[str]] = []
        seen_canonical: Set[Tuple[str, ...]] = set()

        def canonical(cycle: Sequence[str]) -> Tuple[str, ...]:
            body = list(cycle[:-1])
            start = body.index(min(body))
            rotated = body[start:] + body[:start]
            return tuple(rotated)

        def dfs(start: str, current: str, path: List[str], visited: Set[str]) -> None:
            if len(path) > max_length:
                return
            for nxt in self.successors(current):
                if nxt == start and len(path) >= 2:
                    cycle = path + [start]
                    key = canonical(cycle)
                    if key not in seen_canonical:
                        seen_canonical.add(key)
                        cycles.append(cycle)
                elif nxt not in visited and len(path) < max_length:
                    visited.add(nxt)
                    path.append(nxt)
                    dfs(start, nxt, path, visited)
                    path.pop()
                    visited.remove(nxt)

        for node in sorted(self._nodes):
            dfs(node, node, [node], {node})
        return cycles

    def detect_crosstalk(
        self,
        pathway_a: Iterable[str],
        pathway_b: Iterable[str],
    ) -> List[InteractionEdge]:
        """
        Return edges that bridge two annotated pathway node sets.

        Crosstalk is any directed edge with source in one set and target in the
        other (either direction).
        """
        set_a = set(pathway_a)
        set_b = set(pathway_b)
        unknown = (set_a | set_b) - self._nodes
        if unknown:
            raise KeyError(f"Unknown pathway nodes: {sorted(unknown)}")
        bridges: List[InteractionEdge] = []
        for edge in self._edges.values():
            a_to_b = edge.source_id in set_a and edge.target_id in set_b
            b_to_a = edge.source_id in set_b and edge.target_id in set_a
            if a_to_b or b_to_a:
                bridges.append(edge)
        return bridges

    def betweenness_approximation(self, sample_size: Optional[int] = None) -> Dict[str, float]:
        """
        Brandes-style betweenness centrality (exact if sample_size is None).

        Normalised by ``(N-1)(N-2)`` for N > 2 so scores lie roughly in [0, 1].
        Suitable as a hub / bottleneck prior for experimental targeting.
        """
        nodes = self.nodes()
        n = len(nodes)
        if n == 0:
            return {}
        sources = nodes if sample_size is None else nodes[: max(1, min(sample_size, n))]
        centrality = {nid: 0.0 for nid in nodes}

        for s in sources:
            stack: List[str] = []
            pred: Dict[str, List[str]] = {nid: [] for nid in nodes}
            sigma: Dict[str, float] = {nid: 0.0 for nid in nodes}
            dist: Dict[str, int] = {nid: -1 for nid in nodes}
            sigma[s] = 1.0
            dist[s] = 0
            queue: deque[str] = deque([s])
            while queue:
                v = queue.popleft()
                stack.append(v)
                for w in self.successors(v):
                    if dist[w] < 0:
                        dist[w] = dist[v] + 1
                        queue.append(w)
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)
            delta = {nid: 0.0 for nid in nodes}
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    if sigma[w] > 0.0:
                        delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
                if w != s:
                    centrality[w] += delta[w]

        scale_sources = len(sources)
        if n > 2 and scale_sources > 0:
            norm = 1.0 / ((n - 1) * (n - 2))
            # If sampled, inflate by N / sample_size
            inflate = n / scale_sources
            for nid in centrality:
                centrality[nid] *= norm * inflate
        return centrality

    def robustness(
        self,
        target_id: str,
        knockout_ids: Optional[Iterable[str]] = None,
        reachability_depth: int = 12,
    ) -> Dict[str, Any]:
        """
        Estimate structural robustness of signal reaching ``target_id``.

        Method
        ------
        1. Compute basal number of distinct source nodes that can reach the
           target within ``reachability_depth`` steps (BFS on reversed edges).
        2. For each candidate knockout, remove that node and recompute.
        3. Robustness score = mean retained-fraction of source reachability
           over knockouts. 1.0 = every single-node loss is fully compensated;
           0.0 = every knockout abolishes all upstream sources.

        This is a topology-only prior (no kinetics); the ODE/Boolean engines
        provide dynamical robustness separately.
        """
        if target_id not in self._nodes:
            raise KeyError(f"Unknown target {target_id!r}")
        if reachability_depth < 1:
            raise ValueError("reachability_depth must be ≥ 1")

        candidates = list(knockout_ids) if knockout_ids is not None else [
            nid for nid in self._nodes if nid != target_id
        ]

        def upstream_sources(blocked: Set[str]) -> Set[str]:
            found: Set[str] = set()
            queue: deque[Tuple[str, int]] = deque([(target_id, 0)])
            seen = {target_id}
            while queue:
                node, depth = queue.popleft()
                if depth >= reachability_depth:
                    continue
                for pred in self.predecessors(node):
                    if pred in blocked or pred in seen:
                        continue
                    seen.add(pred)
                    found.add(pred)
                    queue.append((pred, depth + 1))
            return found

        basal = upstream_sources(set())
        basal_count = max(len(basal), 1)
        retained_fractions: Dict[str, float] = {}
        for kid in candidates:
            if kid not in self._nodes or kid == target_id:
                continue
            remaining = upstream_sources({kid})
            retained_fractions[kid] = len(remaining) / basal_count

        mean_retention = (
            sum(retained_fractions.values()) / len(retained_fractions)
            if retained_fractions
            else 1.0
        )
        critical = sorted(
            (kid for kid, frac in retained_fractions.items() if frac == 0.0),
            key=lambda x: x,
        )
        return {
            "target_id": target_id,
            "basal_upstream_count": len(basal),
            "mean_retention": mean_retention,
            "retained_fractions": retained_fractions,
            "critical_nodes": critical,
            "is_structurally_robust": mean_retention >= 0.5 and len(critical) == 0,
        }

    # -- export / interoperability -------------------------------------------

    def adjacency_matrix(
        self,
        nodelist: Optional[Sequence[str]] = None,
        weighted: bool = True,
    ) -> Tuple[List[str], List[List[float]]]:
        """
        Dense adjacency matrix for linear-algebra / viz backends.

        Returns ``(ordered_node_ids, matrix)`` where ``matrix[i][j]`` is the
        sum of weights (or 1) of edges i → j.
        """
        order = list(nodelist) if nodelist is not None else self.nodes()
        index = {nid: i for i, nid in enumerate(order)}
        n = len(order)
        matrix = [[0.0 for _ in range(n)] for _ in range(n)]
        for edge in self.active_edges():
            if edge.source_id not in index or edge.target_id not in index:
                continue
            i = index[edge.source_id]
            j = index[edge.target_id]
            matrix[i][j] += edge.weight if weighted else 1.0
        return order, matrix

    def to_edge_list(self) -> List[Dict[str, Any]]:
        """NetworkX-friendly list of edge attribute dicts."""
        return [edge.to_dict() for edge in self.edges()]

    def to_node_list(self) -> List[Dict[str, Any]]:
        """NetworkX-friendly list of node attribute dicts."""
        result: List[Dict[str, Any]] = []
        for nid in self.nodes():
            entity = self.registry.get(nid)
            payload = entity.to_dict()
            logic = self._node_logic[nid]
            payload["logic_gate"] = logic.gate.value
            payload["inhibitor_veto"] = logic.inhibitor_veto
            indeg, outdeg = self.degree(nid)
            payload["in_degree"] = indeg
            payload["out_degree"] = outdeg
            result.append(payload)
        return result

    def subgraph(self, node_ids: Iterable[str]) -> "SignalingNetwork":
        """Induce a subgraph on ``node_ids`` (shared registry reference)."""
        keep = set(node_ids)
        unknown = keep - self._nodes
        if unknown:
            raise KeyError(f"Unknown nodes for subgraph: {sorted(unknown)}")
        sub = SignalingNetwork(registry=self.registry, name=f"{self.name}_subgraph")
        for nid in keep:
            sub._nodes.add(nid)
            sub._node_logic[nid] = self._node_logic[nid]
        for edge in self._edges.values():
            if edge.source_id in keep and edge.target_id in keep:
                # Copy edge object identity intentionally — shared mutability for
                # live rate updates; clone if isolation is required downstream.
                sub._edges[edge.edge_id] = edge
                sub._out[edge.source_id].add(edge.edge_id)
                sub._in[edge.target_id].add(edge.edge_id)
        return sub

    def validate(self) -> List[str]:
        """
        Structural integrity checks. Returns a list of human-readable issues
        (empty list ⇒ healthy).
        """
        issues: List[str] = []
        for nid in self._nodes:
            if nid not in self.registry:
                issues.append(f"Node {nid!r} missing from registry")
        for edge in self._edges.values():
            if edge.source_id not in self._nodes:
                issues.append(f"Edge {edge.edge_id} source {edge.source_id!r} not a node")
            if edge.target_id not in self._nodes:
                issues.append(f"Edge {edge.edge_id} target {edge.target_id!r} not a node")
            if edge.source_id == edge.target_id and edge.interaction_type is InteractionType.TRANSCRIPTION:
                issues.append(
                    f"Edge {edge.edge_id}: self-transcription is unusual — verify intentional autofeedback"
                )
        # Complex members should exist
        for entity in self.registry.by_type(EntityType.COMPLEX):
            members = getattr(entity, "members", {})
            for mid in members:
                if mid not in self.registry:
                    issues.append(f"Complex {entity.entity_id} references missing member {mid!r}")
        return issues

    def summary(self) -> Dict[str, Any]:
        type_counts: Dict[str, int] = defaultdict(int)
        for edge in self._edges.values():
            type_counts[edge.interaction_type.value] += 1
        return {
            "name": self.name,
            "n_nodes": len(self._nodes),
            "n_edges": len(self._edges),
            "interaction_type_counts": dict(type_counts),
            "n_feedback_loops": len(self.detect_feedback_loops()),
            "hubs": self.find_hubs(top_k=min(5, max(1, len(self._nodes)))),
            "pathways": {name: sorted(members) for name, members in self._pathways.items()},
            "crosstalk_switches": [
                {"entity_id": s["entity_id"], "name": s["name"], "pathways": s["pathways"]}
                for s in self.detect_crosstalk_switches()[:5]
            ]
            if self._pathways
            else [],
        }

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self._nodes

    def __iter__(self) -> Iterator[str]:
        return iter(self.nodes())
