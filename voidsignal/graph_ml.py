"""
Graph serialization & tensor translation for VOIDSIGNAL Phase 5.

Converts :class:`~voidsignal.topology.SignalingNetwork` snapshots and
:class:`~voidsignal.simulation.TrajectoryResult` dynamics into geometric-ML
ready tensors:

* ``X`` — node feature matrix ``[N × F]``
* ``E`` — edge index ``[2 × M]`` (source row, target row)
* ``U`` — edge attribute matrix ``[M × D]``

All row / column indices stay aligned with explicit entity-id namespaces from
``topology.py``. Numerics use built-in lists by default; optional NumPy / mock
torch views are available without hard dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import logging
import math

from voidsignal.components import BiologicalEntity, EntityType
from voidsignal.simulation import TrajectoryResult
from voidsignal.topology import InteractionEdge, InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)

ArrayLike = List[List[float]]
IndexPair = List[List[int]]


# ---------------------------------------------------------------------------
# Index alignment
# ---------------------------------------------------------------------------


@dataclass
class NodeIndexMap:
    """Bijective map between entity string IDs and contiguous tensor rows."""

    node_ids: List[str]
    id_to_index: Dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.id_to_index = {nid: i for i, nid in enumerate(self.node_ids)}
        if len(self.id_to_index) != len(self.node_ids):
            raise ValueError("Duplicate node ids in NodeIndexMap")

    def __len__(self) -> int:
        return len(self.node_ids)

    def index(self, entity_id: str) -> int:
        try:
            return self.id_to_index[entity_id]
        except KeyError as exc:
            raise KeyError(f"Entity {entity_id!r} not in graph tensor index") from exc

    def entity_id(self, index: int) -> str:
        return self.node_ids[index]

    def names(self, network: SignalingNetwork) -> List[str]:
        return [network.registry.get(nid).name for nid in self.node_ids]

    @classmethod
    def from_network(
        cls,
        network: SignalingNetwork,
        *,
        include_compartments: bool = False,
        order: Optional[Sequence[str]] = None,
    ) -> "NodeIndexMap":
        if order is not None:
            ids = list(order)
            missing = [nid for nid in ids if nid not in network]
            if missing:
                raise KeyError(f"Ordered nodes absent from network: {missing}")
            return cls(node_ids=ids)
        ids = []
        for nid in network.nodes():
            ent = network.registry.get(nid)
            if not include_compartments and ent.entity_type is EntityType.COMPARTMENT:
                continue
            ids.append(nid)
        ids.sort()  # stable deterministic order
        return cls(node_ids=ids)


# ---------------------------------------------------------------------------
# Feature schemas
# ---------------------------------------------------------------------------


class NodeFeature(Enum):
    """Named channels of the node feature matrix ``X``."""

    CONCENTRATION = auto()
    BOOLEAN = auto()
    PRODUCTION = auto()
    DEGRADATION = auto()
    VMAX = auto()
    KM = auto()
    BINDING = auto()
    BASAL = auto()
    IN_DEGREE = auto()
    OUT_DEGREE = auto()
    BETWEENNESS = auto()
    IS_RECEPTOR = auto()
    IS_ENZYME = auto()
    MEAN_TRAJECTORY = auto()
    STD_TRAJECTORY = auto()
    FINAL_TRAJECTORY = auto()
    VELOCITY_PROXY = auto()
    DRUG_EXPOSURE = auto()
    DELTA_CLEARANCE = auto()
    COMPARTMENT_RANK = auto()


class EdgeFeature(Enum):
    """Named channels of the edge attribute matrix ``U``."""

    WEIGHT = auto()
    RATE = auto()
    HILL = auto()
    EC50 = auto()
    INHIBITORY = auto()
    CATALYTIC = auto()
    DELAY = auto()
    TYPE_ONEHOT_0 = auto()
    TYPE_ONEHOT_1 = auto()
    TYPE_ONEHOT_2 = auto()
    TYPE_ONEHOT_3 = auto()
    VELOCITY = auto()


_INTERACTION_BUCKETS: Tuple[Tuple[InteractionType, ...], ...] = (
    (InteractionType.ACTIVATION, InteractionType.BINDING, InteractionType.TRANSLOCATION),
    (InteractionType.INHIBITION, InteractionType.DEGRADATION, InteractionType.DISSOCIATION),
    (
        InteractionType.PHOSPHORYLATION,
        InteractionType.DEPHOSPHORYLATION,
        InteractionType.CATALYSIS,
        InteractionType.UBIQUITINATION,
    ),
    (InteractionType.TRANSCRIPTION, InteractionType.TRANSLATION),
)


def _type_bucket(itype: InteractionType) -> int:
    for i, bucket in enumerate(_INTERACTION_BUCKETS):
        if itype in bucket:
            return i
    return 3


DEFAULT_NODE_FEATURES: Tuple[NodeFeature, ...] = (
    NodeFeature.CONCENTRATION,
    NodeFeature.BOOLEAN,
    NodeFeature.PRODUCTION,
    NodeFeature.DEGRADATION,
    NodeFeature.VMAX,
    NodeFeature.KM,
    NodeFeature.BINDING,
    NodeFeature.BASAL,
    NodeFeature.IN_DEGREE,
    NodeFeature.OUT_DEGREE,
    NodeFeature.BETWEENNESS,
    NodeFeature.IS_RECEPTOR,
    NodeFeature.IS_ENZYME,
    NodeFeature.MEAN_TRAJECTORY,
    NodeFeature.STD_TRAJECTORY,
    NodeFeature.FINAL_TRAJECTORY,
    NodeFeature.VELOCITY_PROXY,
    NodeFeature.DRUG_EXPOSURE,
    NodeFeature.DELTA_CLEARANCE,
    NodeFeature.COMPARTMENT_RANK,
)

DEFAULT_EDGE_FEATURES: Tuple[EdgeFeature, ...] = (
    EdgeFeature.WEIGHT,
    EdgeFeature.RATE,
    EdgeFeature.HILL,
    EdgeFeature.EC50,
    EdgeFeature.INHIBITORY,
    EdgeFeature.CATALYTIC,
    EdgeFeature.DELAY,
    EdgeFeature.TYPE_ONEHOT_0,
    EdgeFeature.TYPE_ONEHOT_1,
    EdgeFeature.TYPE_ONEHOT_2,
    EdgeFeature.TYPE_ONEHOT_3,
    EdgeFeature.VELOCITY,
)


# ---------------------------------------------------------------------------
# Numeric helpers (dependency-free)
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return x


def _mean(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(max(var, 0.0))


def zeros(rows: int, cols: int) -> ArrayLike:
    return [[0.0 for _ in range(cols)] for _ in range(rows)]


def deepcopy_matrix(m: ArrayLike) -> ArrayLike:
    return [row[:] for row in m]


def mat_shape(m: ArrayLike) -> Tuple[int, int]:
    if not m:
        return (0, 0)
    return (len(m), len(m[0]) if m[0] else 0)


def column_stats(m: ArrayLike) -> Tuple[List[float], List[float]]:
    n, f = mat_shape(m)
    if n == 0 or f == 0:
        return [], []
    means = [0.0] * f
    stds = [0.0] * f
    for j in range(f):
        col = [m[i][j] for i in range(n)]
        means[j] = _mean(col)
        s = _std(col)
        stds[j] = s if s > 1e-12 else 1.0
    return means, stds


def zscore_inplace(m: ArrayLike, means: Sequence[float], stds: Sequence[float]) -> None:
    n, f = mat_shape(m)
    for i in range(n):
        for j in range(f):
            m[i][j] = (m[i][j] - means[j]) / stds[j]


def minmax_inplace(m: ArrayLike) -> Tuple[List[float], List[float]]:
    n, f = mat_shape(m)
    mins = [float("inf")] * f
    maxs = [float("-inf")] * f
    for i in range(n):
        for j in range(f):
            v = m[i][j]
            if v < mins[j]:
                mins[j] = v
            if v > maxs[j]:
                maxs[j] = v
    for j in range(f):
        if not math.isfinite(mins[j]):
            mins[j] = 0.0
            maxs[j] = 1.0
        if maxs[j] - mins[j] < 1e-12:
            maxs[j] = mins[j] + 1.0
    for i in range(n):
        for j in range(f):
            m[i][j] = (m[i][j] - mins[j]) / (maxs[j] - mins[j])
    return mins, maxs


# ---------------------------------------------------------------------------
# Tensor bundle
# ---------------------------------------------------------------------------


@dataclass
class GraphTensors:
    """
    Geometric-learning tensor pack with namespace metadata.

    Shapes
    ------
    ``x`` : ``[N, F]``
    ``edge_index`` : ``[2, M]`` integer
    ``edge_attr`` : ``[M, D]``
    """

    x: ArrayLike
    edge_index: IndexPair
    edge_attr: ArrayLike
    index_map: NodeIndexMap
    edge_ids: List[str]
    node_feature_names: List[str]
    edge_feature_names: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def num_nodes(self) -> int:
        return len(self.index_map)

    @property
    def num_edges(self) -> int:
        return len(self.edge_ids)

    @property
    def num_node_features(self) -> int:
        return mat_shape(self.x)[1]

    @property
    def num_edge_features(self) -> int:
        return mat_shape(self.edge_attr)[1]

    def node_id(self, row: int) -> str:
        return self.index_map.entity_id(row)

    def row_of(self, entity_id: str) -> int:
        return self.index_map.index(entity_id)

    def clone(self) -> "GraphTensors":
        return GraphTensors(
            x=deepcopy_matrix(self.x),
            edge_index=[self.edge_index[0][:], self.edge_index[1][:]],
            edge_attr=deepcopy_matrix(self.edge_attr),
            index_map=NodeIndexMap(node_ids=list(self.index_map.node_ids)),
            edge_ids=list(self.edge_ids),
            node_feature_names=list(self.node_feature_names),
            edge_feature_names=list(self.edge_feature_names),
            metadata=dict(self.metadata),
        )

    def normalize(
        self,
        *,
        mode: str = "zscore",
        normalize_edges: bool = True,
    ) -> "GraphTensors":
        """Return a normalized copy. Zero-variance features collapse to 0."""
        out = self.clone()
        if mode == "zscore":
            means, stds = column_stats(out.x)
            if means:
                zscore_inplace(out.x, means, stds)
                out.metadata["x_mean"] = means
                out.metadata["x_std"] = stds
            if normalize_edges and out.edge_attr:
                em, es = column_stats(out.edge_attr)
                zscore_inplace(out.edge_attr, em, es)
                out.metadata["u_mean"] = em
                out.metadata["u_std"] = es
        elif mode == "minmax":
            out.metadata["x_minmax"] = minmax_inplace(out.x)
            if normalize_edges and out.edge_attr:
                out.metadata["u_minmax"] = minmax_inplace(out.edge_attr)
        elif mode == "none":
            pass
        else:
            raise ValueError("mode must be 'zscore', 'minmax', or 'none'")
        out.metadata["normalize_mode"] = mode
        return out

    def to_numpy(self) -> Dict[str, Any]:
        """
        Best-effort NumPy conversion. Falls back to nested lists when NumPy
        is unavailable (unit-test friendly).
        """
        try:
            import numpy as np  # type: ignore
        except ImportError:
            return self.as_dict()
        return {
            "x": np.asarray(self.x, dtype=float),
            "edge_index": np.asarray(self.edge_index, dtype=int),
            "edge_attr": np.asarray(self.edge_attr, dtype=float),
            "node_ids": list(self.index_map.node_ids),
            "edge_ids": list(self.edge_ids),
            "node_feature_names": list(self.node_feature_names),
            "edge_feature_names": list(self.edge_feature_names),
            "metadata": dict(self.metadata),
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "x": deepcopy_matrix(self.x),
            "edge_index": [self.edge_index[0][:], self.edge_index[1][:]],
            "edge_attr": deepcopy_matrix(self.edge_attr),
            "node_ids": list(self.index_map.node_ids),
            "edge_ids": list(self.edge_ids),
            "node_feature_names": list(self.node_feature_names),
            "edge_feature_names": list(self.edge_feature_names),
            "metadata": dict(self.metadata),
        }

    def mock_torch(self) -> "MockGeometricData":
        """Lightweight stand-in for ``torch_geometric.data.Data``."""
        return MockGeometricData.from_tensors(self)


@dataclass
class MockTensor:
    """Minimal tensor façade used when PyTorch is not installed."""

    data: ArrayLike
    dtype: str = "float32"

    @property
    def shape(self) -> Tuple[int, ...]:
        if not self.data:
            return (0,)
        if isinstance(self.data[0], list):
            return (len(self.data), len(self.data[0]))  # type: ignore[arg-type]
        return (len(self.data),)

    def tolist(self) -> Any:
        return self.data

    def __repr__(self) -> str:
        return f"MockTensor(shape={self.shape}, dtype={self.dtype})"


@dataclass
class MockGeometricData:
    """PyG-like container: ``.x``, ``.edge_index``, ``.edge_attr``."""

    x: MockTensor
    edge_index: MockTensor
    edge_attr: MockTensor
    node_ids: List[str]
    edge_ids: List[str]
    num_nodes: int
    num_edges: int

    @classmethod
    def from_tensors(cls, tensors: GraphTensors) -> "MockGeometricData":
        return cls(
            x=MockTensor(deepcopy_matrix(tensors.x)),
            edge_index=MockTensor(tensors.edge_index, dtype="int64"),
            edge_attr=MockTensor(deepcopy_matrix(tensors.edge_attr)),
            node_ids=list(tensors.index_map.node_ids),
            edge_ids=list(tensors.edge_ids),
            num_nodes=tensors.num_nodes,
            num_edges=tensors.num_edges,
        )


# ---------------------------------------------------------------------------
# Trajectory / velocity packaging
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryFeatures:
    """Per-node summary statistics from an ODE / Boolean trajectory."""

    mean: Dict[str, float]
    std: Dict[str, float]
    final: Dict[str, float]
    velocity: Dict[str, float]
    """Mean absolute finite-difference d[X]/dt proxy."""


def encode_trajectory(
    trajectory: TrajectoryResult,
    node_ids: Sequence[str],
) -> TrajectoryFeatures:
    means: Dict[str, float] = {}
    stds: Dict[str, float] = {}
    finals: Dict[str, float] = {}
    velocities: Dict[str, float] = {}
    times = trajectory.times
    for nid in node_ids:
        series = []
        for sample in trajectory.concentrations:
            series.append(_safe_float(sample.get(nid, 0.0)))
        if not series:
            means[nid] = 0.0
            stds[nid] = 0.0
            finals[nid] = 0.0
            velocities[nid] = 0.0
            continue
        means[nid] = _mean(series)
        stds[nid] = _std(series)
        finals[nid] = series[-1]
        if len(series) >= 2 and len(times) >= 2:
            acc = 0.0
            count = 0
            for i in range(1, len(series)):
                dt = times[i] - times[i - 1]
                if dt <= 0.0:
                    continue
                acc += abs(series[i] - series[i - 1]) / dt
                count += 1
            velocities[nid] = acc / count if count else 0.0
        else:
            velocities[nid] = 0.0
    return TrajectoryFeatures(mean=means, std=stds, final=finals, velocity=velocities)


def estimate_edge_velocities(
    network: SignalingNetwork,
    concentrations: Mapping[str, float],
) -> Dict[str, float]:
    """
    Mass-action-like edge flux proxy::

        v ≈ k · w · [src] / (EC50^n + [src]^n)
    """
    out: Dict[str, float] = {}
    for edge in network.active_edges():
        src = max(_safe_float(concentrations.get(edge.source_id, 0.0)), 0.0)
        n = max(edge.hill_coefficient, 1e-6)
        ec = max(edge.ec50, 1e-12)
        drive = (src**n) / ((ec**n) + (src**n)) if src > 0.0 else 0.0
        out[edge.edge_id] = max(0.0, edge.rate_constant) * max(0.0, edge.weight) * drive
    return out


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class GraphBuildConfig:
    """Controls which features land in ``X`` / ``U``."""

    node_features: Sequence[NodeFeature] = DEFAULT_NODE_FEATURES
    edge_features: Sequence[EdgeFeature] = DEFAULT_EDGE_FEATURES
    include_compartments: bool = False
    use_betweenness: bool = True
    normalize: str = "none"  # deferred; call GraphTensors.normalize


class GraphTensorFactory:
    """
    Primary conversion utility: SignalingNetwork (+ optional dynamics) → tensors.
    """

    def __init__(self, config: Optional[GraphBuildConfig] = None) -> None:
        self.config = config or GraphBuildConfig()

    def from_network(
        self,
        network: SignalingNetwork,
        *,
        trajectory: Optional[TrajectoryResult] = None,
        concentrations: Optional[Mapping[str, float]] = None,
        drug_exposure: Optional[Mapping[str, float]] = None,
        spatial_tiers: Optional[Mapping[str, float]] = None,
        index_map: Optional[NodeIndexMap] = None,
    ) -> GraphTensors:
        idx = index_map or NodeIndexMap.from_network(
            network, include_compartments=self.config.include_compartments
        )
        conc = dict(concentrations or network.registry.concentrations())
        traj_feat: Optional[TrajectoryFeatures] = None
        if trajectory is not None:
            traj_feat = encode_trajectory(trajectory, idx.node_ids)
            # Prefer live trajectory finals when explicit concentrations omitted
            if concentrations is None and traj_feat.final:
                conc = dict(traj_feat.final)

        betweenness: Dict[str, float] = {}
        if self.config.use_betweenness and NodeFeature.BETWEENNESS in self.config.node_features:
            try:
                betweenness = network.betweenness_approximation()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("betweenness unavailable: %s", exc)
                betweenness = {nid: 0.0 for nid in idx.node_ids}

        in_deg = {nid: 0 for nid in idx.node_ids}
        out_deg = {nid: 0 for nid in idx.node_ids}
        for edge in network.active_edges():
            if edge.source_id in out_deg:
                out_deg[edge.source_id] += 1
            if edge.target_id in in_deg:
                in_deg[edge.target_id] += 1

        drug = dict(drug_exposure or {})
        tiers = dict(spatial_tiers or {})
        # Auto-pull compartment rank / clearance / exposure from entity metadata
        for nid in idx.node_ids:
            ent = network.registry.get(nid)
            if nid not in drug:
                drug[nid] = _safe_float(ent.metadata.get("drug_free_conc", ent.metadata.get("drug_concentration", 0.0)))
            if nid not in tiers:
                tiers[nid] = _safe_float(ent.metadata.get("compartment_rank", 0.0))

        edge_vel = estimate_edge_velocities(network, conc)

        node_names = [f.name.lower() for f in self.config.node_features]
        edge_names = [f.name.lower() for f in self.config.edge_features]
        x = zeros(len(idx), len(self.config.node_features))
        for i, nid in enumerate(idx.node_ids):
            ent = network.registry.get(nid)
            x[i] = self._node_row(
                ent,
                nid,
                conc=conc,
                in_deg=in_deg.get(nid, 0),
                out_deg=out_deg.get(nid, 0),
                betweenness=betweenness.get(nid, 0.0),
                traj=traj_feat,
                drug=drug.get(nid, 0.0),
                tier=tiers.get(nid, 0.0),
            )

        edges = [
            e
            for e in network.active_edges()
            if e.source_id in idx.id_to_index and e.target_id in idx.id_to_index
        ]
        src_row: List[int] = []
        tgt_row: List[int] = []
        u = zeros(len(edges), len(self.config.edge_features))
        edge_ids: List[str] = []
        for m, edge in enumerate(edges):
            src_row.append(idx.index(edge.source_id))
            tgt_row.append(idx.index(edge.target_id))
            edge_ids.append(edge.edge_id)
            u[m] = self._edge_row(edge, velocity=edge_vel.get(edge.edge_id, 0.0))

        tensors = GraphTensors(
            x=x,
            edge_index=[src_row, tgt_row],
            edge_attr=u,
            index_map=idx,
            edge_ids=edge_ids,
            node_feature_names=node_names,
            edge_feature_names=edge_names,
            metadata={
                "network_name": network.name,
                "has_trajectory": trajectory is not None,
                "disease_phenotype": network.metadata.get("disease_phenotype"),
            },
        )
        if self.config.normalize != "none":
            tensors = tensors.normalize(mode=self.config.normalize)
        return tensors

    def from_dual_engine_snapshot(
        self,
        network: SignalingNetwork,
        trajectory: TrajectoryResult,
        *,
        drug_exposure: Optional[Mapping[str, float]] = None,
    ) -> GraphTensors:
        """Pair topology with DualEngineSimulator output tensors."""
        return self.from_network(
            network,
            trajectory=trajectory,
            drug_exposure=drug_exposure,
        )

    def _node_row(
        self,
        ent: BiologicalEntity,
        nid: str,
        *,
        conc: Mapping[str, float],
        in_deg: int,
        out_deg: int,
        betweenness: float,
        traj: Optional[TrajectoryFeatures],
        drug: float,
        tier: float,
    ) -> List[float]:
        k = ent.kinetics
        c = max(_safe_float(conc.get(nid, ent.concentration)), 0.0)
        row: List[float] = []
        for feat in self.config.node_features:
            if feat is NodeFeature.CONCENTRATION:
                row.append(c)
            elif feat is NodeFeature.BOOLEAN:
                row.append(float(ent.boolean_state.value))
            elif feat is NodeFeature.PRODUCTION:
                row.append(_safe_float(k.production_rate))
            elif feat is NodeFeature.DEGRADATION:
                row.append(_safe_float(k.degradation_rate))
            elif feat is NodeFeature.VMAX:
                row.append(_safe_float(k.vmax))
            elif feat is NodeFeature.KM:
                row.append(_safe_float(k.km, 1.0))
            elif feat is NodeFeature.BINDING:
                row.append(_safe_float(k.binding_affinity))
            elif feat is NodeFeature.BASAL:
                row.append(_safe_float(k.basal_activity))
            elif feat is NodeFeature.IN_DEGREE:
                row.append(float(in_deg))
            elif feat is NodeFeature.OUT_DEGREE:
                row.append(float(out_deg))
            elif feat is NodeFeature.BETWEENNESS:
                row.append(_safe_float(betweenness))
            elif feat is NodeFeature.IS_RECEPTOR:
                row.append(1.0 if ent.entity_type is EntityType.RECEPTOR else 0.0)
            elif feat is NodeFeature.IS_ENZYME:
                row.append(1.0 if getattr(ent, "is_enzyme", False) else 0.0)
            elif feat is NodeFeature.MEAN_TRAJECTORY:
                row.append(_safe_float(traj.mean.get(nid, c) if traj else c))
            elif feat is NodeFeature.STD_TRAJECTORY:
                row.append(_safe_float(traj.std.get(nid, 0.0) if traj else 0.0))
            elif feat is NodeFeature.FINAL_TRAJECTORY:
                row.append(_safe_float(traj.final.get(nid, c) if traj else c))
            elif feat is NodeFeature.VELOCITY_PROXY:
                row.append(_safe_float(traj.velocity.get(nid, 0.0) if traj else 0.0))
            elif feat is NodeFeature.DRUG_EXPOSURE:
                row.append(max(0.0, _safe_float(drug)))
            elif feat is NodeFeature.DELTA_CLEARANCE:
                row.append(_safe_float(ent.metadata.get("delta_clearance", 0.0)))
            elif feat is NodeFeature.COMPARTMENT_RANK:
                row.append(_safe_float(tier))
            else:
                row.append(0.0)
        return row

    def _edge_row(self, edge: InteractionEdge, *, velocity: float) -> List[float]:
        bucket = _type_bucket(edge.interaction_type)
        onehots = [1.0 if bucket == i else 0.0 for i in range(4)]
        row: List[float] = []
        for feat in self.config.edge_features:
            if feat is EdgeFeature.WEIGHT:
                row.append(_safe_float(edge.weight))
            elif feat is EdgeFeature.RATE:
                row.append(_safe_float(edge.rate_constant))
            elif feat is EdgeFeature.HILL:
                row.append(_safe_float(edge.hill_coefficient, 1.0))
            elif feat is EdgeFeature.EC50:
                row.append(_safe_float(edge.ec50, 0.5))
            elif feat is EdgeFeature.INHIBITORY:
                row.append(1.0 if edge.interaction_type.is_inhibitory else 0.0)
            elif feat is EdgeFeature.CATALYTIC:
                row.append(1.0 if edge.interaction_type.is_catalytic else 0.0)
            elif feat is EdgeFeature.DELAY:
                row.append(float(edge.delay))
            elif feat is EdgeFeature.TYPE_ONEHOT_0:
                row.append(onehots[0])
            elif feat is EdgeFeature.TYPE_ONEHOT_1:
                row.append(onehots[1])
            elif feat is EdgeFeature.TYPE_ONEHOT_2:
                row.append(onehots[2])
            elif feat is EdgeFeature.TYPE_ONEHOT_3:
                row.append(onehots[3])
            elif feat is EdgeFeature.VELOCITY:
                row.append(max(0.0, _safe_float(velocity)))
            else:
                row.append(0.0)
        return row


def build_graph_tensors(
    network: SignalingNetwork,
    *,
    trajectory: Optional[TrajectoryResult] = None,
    normalize: str = "zscore",
    **kwargs: Any,
) -> GraphTensors:
    """Convenience one-shot builder with z-score normalization by default."""
    factory = GraphTensorFactory(GraphBuildConfig(normalize="none"))
    tensors = factory.from_network(network, trajectory=trajectory, **kwargs)
    if normalize != "none":
        return tensors.normalize(mode=normalize)
    return tensors
