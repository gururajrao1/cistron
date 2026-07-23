"""
Target discovery & link-prediction engines for VOIDSIGNAL Phase 5.

Blueprint Graph Attention (GAT) and Message-Passing (MPNN) encoders operate on
:class:`~voidsignal.graph_ml.GraphTensors` without requiring PyTorch. They score:

* **Node classification / target prioritization** — therapeutic rescue vs Phase-4
  toxicology bounds.
* **Link prediction / crosstalk inference** — unobserved edges from structural
  embeddings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import logging
import math
import random

from voidsignal.graph_ml import GraphTensors
from voidsignal.perturbation import Mutation, MutationKind, PerturbationManager
from voidsignal.simulation import DualEngineSimulator, SimulationConfig, TrajectoryResult
from voidsignal.topology import SignalingNetwork
from voidsignal.toxicology import SafetyTarget, SafetyTargetPanel, ToxicologyMonitor, ToxicologyReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tiny autograd-free linear algebra
# ---------------------------------------------------------------------------


def _vec(n: int, fill: float = 0.0) -> List[float]:
    return [fill] * n


def _clone_vec(v: Sequence[float]) -> List[float]:
    return [float(x) for x in v]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _softmax(logits: Sequence[float]) -> List[float]:
    if not logits:
        return []
    m = max(logits)
    exps = [math.exp(min(max(x - m, -60.0), 60.0)) for x in logits]
    s = sum(exps)
    if s <= 0.0:
        return [1.0 / len(logits)] * len(logits)
    return [e / s for e in exps]


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _leaky_relu(x: float, alpha: float = 0.2) -> float:
    return x if x >= 0.0 else alpha * x


def _tanh(x: float) -> float:
    return math.tanh(max(-20.0, min(20.0, x)))


def _xavier(rows: int, cols: int, rng: random.Random) -> List[List[float]]:
    limit = math.sqrt(6.0 / max(rows + cols, 1))
    return [[rng.uniform(-limit, limit) for _ in range(cols)] for _ in range(rows)]


def _matvec(w: Sequence[Sequence[float]], x: Sequence[float]) -> List[float]:
    return [_dot(row, x) for row in w]


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------


class EncoderKind(Enum):
    GAT = "gat"
    MPNN = "mpnn"


@dataclass
class GATLayer:
    """
    Single-head graph attention::

        e_ij = LeakyReLU(aᵀ [W h_i ‖ W h_j ‖ u_ij])
        α_ij = softmax_j(e_ij)
        h'_i = σ(Σ_j α_ij W h_j)
    """

    in_dim: int
    out_dim: int
    edge_dim: int
    seed: int = 0
    W: List[List[float]] = field(init=False)
    a: List[float] = field(init=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self.W = _xavier(self.out_dim, self.in_dim, rng)
        self.a = [rng.uniform(-0.1, 0.1) for _ in range(2 * self.out_dim + max(self.edge_dim, 0))]

    def forward(
        self,
        H: Sequence[Sequence[float]],
        edge_index: Sequence[Sequence[int]],
        edge_attr: Sequence[Sequence[float]],
    ) -> Tuple[List[List[float]], List[float]]:
        n = len(H)
        Wh = [_matvec(self.W, h) for h in H]
        # Collect inbound edges per node
        inbound: List[List[int]] = [[] for _ in range(n)]
        for m, (s, t) in enumerate(zip(edge_index[0], edge_index[1])):
            if 0 <= t < n and 0 <= s < n:
                inbound[t].append(m)

        out = [_vec(self.out_dim) for _ in range(n)]
        attn_all: List[float] = [0.0] * len(edge_index[0])

        for i in range(n):
            edges = inbound[i]
            if not edges:
                # Self retain
                out[i] = [_tanh(v) for v in Wh[i]]
                continue
            logits: List[float] = []
            msgs: List[List[float]] = []
            for m in edges:
                j = edge_index[0][m]
                u = edge_attr[m] if m < len(edge_attr) else []
                cat = Wh[j] + Wh[i] + list(u[: self.edge_dim])
                if len(cat) < len(self.a):
                    cat = cat + [0.0] * (len(self.a) - len(cat))
                logits.append(_leaky_relu(_dot(self.a, cat[: len(self.a)])))
                msgs.append(Wh[j])
            alpha = _softmax(logits)
            acc = _vec(self.out_dim)
            for w, msg, m in zip(alpha, msgs, edges):
                attn_all[m] = w
                for d in range(self.out_dim):
                    acc[d] += w * msg[d]
            out[i] = [_tanh(v) for v in acc]
        return out, attn_all


@dataclass
class MPNNLayer:
    """
    Softmax-free message passing::

        m_ij = tanh(W_msg · (h_j ‖ u_ij))
        h'_i = tanh(W_self · h_i + Σ_j m_ij)
    """

    in_dim: int
    out_dim: int
    edge_dim: int
    seed: int = 0
    W_self: List[List[float]] = field(init=False)
    W_msg: List[List[float]] = field(init=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self.W_self = _xavier(self.out_dim, self.in_dim, rng)
        self.W_msg = _xavier(self.out_dim, self.in_dim + max(self.edge_dim, 0), rng)

    def forward(
        self,
        H: Sequence[Sequence[float]],
        edge_index: Sequence[Sequence[int]],
        edge_attr: Sequence[Sequence[float]],
    ) -> List[List[float]]:
        n = len(H)
        agg = [_vec(self.out_dim) for _ in range(n)]
        for m, (s, t) in enumerate(zip(edge_index[0], edge_index[1])):
            if not (0 <= s < n and 0 <= t < n):
                continue
            u = list(edge_attr[m][: self.edge_dim]) if m < len(edge_attr) else []
            if len(u) < self.edge_dim:
                u = u + [0.0] * (self.edge_dim - len(u))
            cat = list(H[s]) + u
            msg = _matvec(self.W_msg, cat)
            for d in range(self.out_dim):
                agg[t][d] += msg[d]
        out: List[List[float]] = []
        for i in range(n):
            self_part = _matvec(self.W_self, H[i])
            out.append([_tanh(self_part[d] + agg[i][d]) for d in range(self.out_dim)])
        return out


@dataclass
class GraphEncoder:
    """Stack of GAT or MPNN layers → node embeddings."""

    kind: EncoderKind = EncoderKind.GAT
    hidden_dim: int = 16
    out_dim: int = 8
    n_layers: int = 2
    seed: int = 7
    layers: List[Any] = field(default_factory=list, init=False)
    in_dim: int = 0
    edge_dim: int = 0
    last_attention: List[float] = field(default_factory=list, init=False)

    def build(self, in_dim: int, edge_dim: int) -> "GraphEncoder":
        self.in_dim = in_dim
        self.edge_dim = edge_dim
        self.layers = []
        dims = [in_dim] + [self.hidden_dim] * max(self.n_layers - 1, 0) + [self.out_dim]
        for i in range(len(dims) - 1):
            if self.kind is EncoderKind.GAT:
                self.layers.append(
                    GATLayer(dims[i], dims[i + 1], edge_dim, seed=self.seed + i)
                )
            else:
                self.layers.append(
                    MPNNLayer(dims[i], dims[i + 1], edge_dim, seed=self.seed + i)
                )
        return self

    def encode(self, tensors: GraphTensors) -> List[List[float]]:
        if not self.layers:
            self.build(tensors.num_node_features, tensors.num_edge_features)
        H: List[List[float]] = [row[:] for row in tensors.x]
        attn: List[float] = []
        for layer in self.layers:
            if isinstance(layer, GATLayer):
                H, attn = layer.forward(H, tensors.edge_index, tensors.edge_attr)
            else:
                H = layer.forward(H, tensors.edge_index, tensors.edge_attr)
        self.last_attention = attn
        return H


# ---------------------------------------------------------------------------
# Supervised heads
# ---------------------------------------------------------------------------


@dataclass
class LinearHead:
    """Softmax / sigmoid classifier on embeddings."""

    in_dim: int
    out_dim: int = 1
    seed: int = 1
    W: List[List[float]] = field(init=False)
    b: List[float] = field(init=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self.W = _xavier(self.out_dim, self.in_dim, rng)
        self.b = [0.0] * self.out_dim

    def logits(self, h: Sequence[float]) -> List[float]:
        return [_dot(self.W[k], h) + self.b[k] for k in range(self.out_dim)]

    def score(self, h: Sequence[float]) -> float:
        return _sigmoid(self.logits(h)[0])

    def sgd_step(
        self,
        h: Sequence[float],
        target: float,
        *,
        lr: float = 0.05,
        weight_decay: float = 1e-4,
    ) -> float:
        """Binary cross-entropy step; returns loss."""
        s = self.score(h)
        # dL/dz = s - y
        err = s - target
        loss = -(target * math.log(max(s, 1e-12)) + (1.0 - target) * math.log(max(1.0 - s, 1e-12)))
        for j in range(self.in_dim):
            self.W[0][j] -= lr * (err * h[j] + weight_decay * self.W[0][j])
        self.b[0] -= lr * err
        return loss


@dataclass
class BilinearLinkHead:
    """Link score σ(h_iᵀ W h_j + bᵀ(h_i − h_j))."""

    dim: int
    seed: int = 2
    W: List[List[float]] = field(init=False)
    b: List[float] = field(init=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self.W = _xavier(self.dim, self.dim, rng)
        self.b = [rng.uniform(-0.05, 0.05) for _ in range(self.dim)]

    def score(self, hi: Sequence[float], hj: Sequence[float]) -> float:
        whj = _matvec(self.W, hj)
        diff = [hi[k] - hj[k] for k in range(self.dim)]
        logit = _dot(hi, whj) + _dot(self.b, diff)
        return _sigmoid(logit)

    def sgd_step(
        self,
        hi: Sequence[float],
        hj: Sequence[float],
        target: float,
        *,
        lr: float = 0.05,
    ) -> float:
        s = self.score(hi, hj)
        err = s - target
        loss = -(target * math.log(max(s, 1e-12)) + (1.0 - target) * math.log(max(1.0 - s, 1e-12)))
        # Gradients w.r.t. W: err * outer(hi, hj)
        for i in range(self.dim):
            for j in range(self.dim):
                self.W[i][j] -= lr * err * hi[i] * hj[j]
            self.b[i] -= lr * err * (hi[i] - hj[i])
        return loss


# ---------------------------------------------------------------------------
# Therapeutic label heuristics (Phase-4 aware)
# ---------------------------------------------------------------------------


@dataclass
class RescueLabelConfig:
    """How to score a knockout as a therapeutic target."""

    disease_readouts: Sequence[str]
    """Entity names/ids that should decrease under successful rescue."""
    tox_panel: Optional[SafetyTargetPanel] = None
    max_tox_index: float = 2.5
    sim_config: SimulationConfig = field(
        default_factory=lambda: SimulationConfig(t_end=20.0, dt=0.25, record_every=20)
    )
    network_factory: Optional[Callable[[], SignalingNetwork]] = None


def _resolve(network: SignalingNetwork, name_or_id: str) -> str:
    if name_or_id in network.registry:
        return name_or_id
    for ent in network.registry.entities():
        if ent.name == name_or_id:
            return ent.entity_id
    raise KeyError(name_or_id)


def therapeutic_label(
    network_factory: Callable[[], SignalingNetwork],
    target_id_or_name: str,
    *,
    disease_readouts: Sequence[str],
    baseline: Optional[TrajectoryResult] = None,
    tox_panel: Optional[SafetyTargetPanel] = None,
    max_tox_index: float = 2.5,
    config: Optional[SimulationConfig] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Label ∈ [0, 1]: high when knockouts reduce disease readouts without
    violating the toxicology panel.
    """
    cfg = config or SimulationConfig(t_end=20.0, dt=0.25, record_every=20)
    net0 = network_factory()
    if baseline is None:
        baseline = DualEngineSimulator(net0).run_ode(cfg)
    base_final = baseline.final_concentrations()

    net = network_factory()
    tid = _resolve(net, target_id_or_name)
    mgr = PerturbationManager()
    mgr.add(Mutation(target_id=tid, kind=MutationKind.KNOCKOUT, t_start=0.0))
    mon: Optional[ToxicologyMonitor] = None
    engine = DualEngineSimulator(net)
    hooks = mgr.hooks()
    if tox_panel is not None and tox_panel.targets:
        # Remap panel entity ids onto the fresh network by name
        remapped = SafetyTargetPanel()
        probe = network_factory()
        for t in tox_panel.targets:
            nm = t.name
            if t.entity_id in probe.registry:
                nm = probe.registry.get(t.entity_id).name
            try:
                eid = _resolve(net, nm)
            except KeyError:
                continue
            remapped.add(
                SafetyTarget(
                    entity_id=eid,
                    pathway=t.pathway,
                    threshold=t.threshold,
                    direction=t.direction,
                    name=nm,
                    weight=t.weight,
                )
            )
        mon = ToxicologyMonitor(remapped, cooldown=0.5)
        hooks = hooks + [mon.as_hook()]
    traj = engine.run_ode(cfg, perturbation_hooks=hooks)
    final = traj.final_concentrations()

    reductions: List[float] = []
    for r in disease_readouts:
        try:
            rid0 = _resolve(network_factory(), r)
            rid = _resolve(net, r)
        except KeyError:
            continue
        b = max(base_final.get(rid0, 0.0), 1e-12)
        a = max(final.get(rid, 0.0), 0.0)
        reductions.append(max(0.0, min(1.0, (b - a) / b)))
    rescue = sum(reductions) / len(reductions) if reductions else 0.0

    tox_index = 0.0
    if mon is not None:
        report: ToxicologyReport = mon.report()
        tox_index = report.tox_index
        if not report.events:
            report = mon.evaluate_trajectory(traj)
            tox_index = report.tox_index
    tox_penalty = 0.0
    if tox_index > max_tox_index:
        tox_penalty = min(1.0, (tox_index - max_tox_index) / max(max_tox_index, 1e-6))
    label = max(0.0, min(1.0, rescue * (1.0 - tox_penalty)))
    return label, {"rescue": rescue, "tox_index": tox_index, "tox_penalty": tox_penalty}


# ---------------------------------------------------------------------------
# Public models
# ---------------------------------------------------------------------------


@dataclass
class TargetScore:
    entity_id: str
    name: str
    score: float
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "score": self.score,
            "embedding": list(self.embedding),
            "metadata": dict(self.metadata),
        }


@dataclass
class LinkScore:
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    score: float
    exists: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "score": self.score,
            "exists": self.exists,
        }


class TargetDiscoveryModel:
    """
    GAT/MPNN encoder + linear head for therapeutic target prioritization.
    """

    def __init__(
        self,
        *,
        encoder_kind: EncoderKind = EncoderKind.GAT,
        hidden_dim: int = 16,
        embed_dim: int = 8,
        seed: int = 11,
    ) -> None:
        self.encoder = GraphEncoder(
            kind=encoder_kind, hidden_dim=hidden_dim, out_dim=embed_dim, seed=seed
        )
        self.head: Optional[LinearHead] = None
        self.embed_dim = embed_dim
        self._trained = False
        self.train_history: List[float] = []

    def fit(
        self,
        tensors: GraphTensors,
        labels: Mapping[str, float],
        *,
        epochs: int = 80,
        lr: float = 0.08,
    ) -> List[float]:
        emb = self.encoder.encode(tensors)
        self.head = LinearHead(self.embed_dim, seed=self.encoder.seed + 99)
        history: List[float] = []
        idx = tensors.index_map
        pairs = [(idx.index(eid), float(y)) for eid, y in labels.items() if eid in idx.id_to_index]
        if not pairs:
            raise ValueError("No training labels aligned with tensor node ids")
        for _ in range(epochs):
            total = 0.0
            random.shuffle(pairs)
            for row, y in pairs:
                total += self.head.sgd_step(emb[row], y, lr=lr)
            history.append(total / len(pairs))
        self._trained = True
        self.train_history = history
        return history

    def fit_from_simulations(
        self,
        tensors: GraphTensors,
        network_factory: Callable[[], SignalingNetwork],
        *,
        disease_readouts: Sequence[str],
        candidate_ids: Optional[Sequence[str]] = None,
        tox_panel: Optional[SafetyTargetPanel] = None,
        epochs: int = 60,
    ) -> Dict[str, float]:
        """Generate Phase-4-aware labels then fit."""
        net = network_factory()
        cands = list(candidate_ids or tensors.index_map.node_ids)
        labels: Dict[str, float] = {}
        meta: Dict[str, Any] = {}
        baseline = DualEngineSimulator(network_factory()).run_ode(
            SimulationConfig(t_end=20.0, dt=0.25, record_every=20)
        )
        for cid in cands:
            # Map tensor id onto factory network by name
            name = tensors.index_map.names(net)[tensors.row_of(cid)] if cid in net else (
                net.registry.get(cid).name if cid in net.registry else cid
            )
            try:
                label, info = therapeutic_label(
                    network_factory,
                    name,
                    disease_readouts=disease_readouts,
                    baseline=baseline,
                    tox_panel=tox_panel,
                )
            except KeyError:
                continue
            labels[cid] = label
            meta[cid] = info
        self.fit(tensors, labels, epochs=epochs)
        self._label_meta = meta  # type: ignore[attr-defined]
        return labels

    def predict(self, tensors: GraphTensors) -> List[TargetScore]:
        if self.head is None:
            # Unsupervised proxy: centrality-like norm of embedding
            emb = self.encoder.encode(tensors)
            scores = []
            for i, nid in enumerate(tensors.index_map.node_ids):
                s = _sigmoid(_norm(emb[i]) - 1.0)
                name = nid
                scores.append(TargetScore(nid, name, s, emb[i]))
            scores.sort(key=lambda t: t.score, reverse=True)
            return scores
        emb = self.encoder.encode(tensors)
        out: List[TargetScore] = []
        for i, nid in enumerate(tensors.index_map.node_ids):
            out.append(
                TargetScore(
                    entity_id=nid,
                    name=nid,
                    score=self.head.score(emb[i]),
                    embedding=emb[i],
                )
            )
        out.sort(key=lambda t: t.score, reverse=True)
        return out

    def rank(
        self,
        tensors: GraphTensors,
        network: SignalingNetwork,
        *,
        top_k: int = 5,
    ) -> List[TargetScore]:
        ranked = self.predict(tensors)
        for item in ranked:
            if item.entity_id in network.registry:
                item.name = network.registry.get(item.entity_id).name
        return ranked[:top_k]


class LinkPredictionModel:
    """Infer missing interaction / crosstalk edges from embeddings."""

    def __init__(
        self,
        *,
        encoder_kind: EncoderKind = EncoderKind.MPNN,
        hidden_dim: int = 16,
        embed_dim: int = 8,
        seed: int = 23,
    ) -> None:
        self.encoder = GraphEncoder(
            kind=encoder_kind, hidden_dim=hidden_dim, out_dim=embed_dim, seed=seed
        )
        self.head: Optional[BilinearLinkHead] = None
        self.embed_dim = embed_dim

    def fit(
        self,
        tensors: GraphTensors,
        *,
        epochs: int = 100,
        lr: float = 0.05,
        neg_ratio: int = 2,
        seed: int = 0,
    ) -> List[float]:
        emb = self.encoder.encode(tensors)
        self.head = BilinearLinkHead(self.embed_dim, seed=seed + 3)
        existing: Set[Tuple[int, int]] = set(zip(tensors.edge_index[0], tensors.edge_index[1]))
        pos = list(existing)
        n = tensors.num_nodes
        rng = random.Random(seed)
        history: List[float] = []
        for _ in range(epochs):
            total = 0.0
            count = 0
            for s, t in pos:
                total += self.head.sgd_step(emb[s], emb[t], 1.0, lr=lr)
                count += 1
                for _k in range(neg_ratio):
                    ns, nt = rng.randrange(n), rng.randrange(n)
                    if ns == nt or (ns, nt) in existing:
                        continue
                    total += self.head.sgd_step(emb[ns], emb[nt], 0.0, lr=lr)
                    count += 1
            history.append(total / max(count, 1))
        return history

    def score_pair(self, tensors: GraphTensors, source_id: str, target_id: str) -> float:
        if self.head is None:
            raise RuntimeError("Call fit() before score_pair")
        emb = self.encoder.encode(tensors)
        i = tensors.row_of(source_id)
        j = tensors.row_of(target_id)
        return self.head.score(emb[i], emb[j])

    def suggest(
        self,
        tensors: GraphTensors,
        network: SignalingNetwork,
        *,
        top_k: int = 10,
        exclude_existing: bool = True,
    ) -> List[LinkScore]:
        if self.head is None:
            raise RuntimeError("Call fit() before suggest")
        emb = self.encoder.encode(tensors)
        existing = set(zip(tensors.edge_index[0], tensors.edge_index[1]))
        scores: List[LinkScore] = []
        n = tensors.num_nodes
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                exists = (i, j) in existing
                if exclude_existing and exists:
                    continue
                s = self.head.score(emb[i], emb[j])
                sid = tensors.node_id(i)
                tid = tensors.node_id(j)
                scores.append(
                    LinkScore(
                        source_id=sid,
                        target_id=tid,
                        source_name=network.registry.get(sid).name,
                        target_name=network.registry.get(tid).name,
                        score=s,
                        exists=exists,
                    )
                )
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_k]


class PredictiveModelingSuite:
    """Facade binding tensor build → target / link models."""

    def __init__(
        self,
        *,
        target_kind: EncoderKind = EncoderKind.GAT,
        link_kind: EncoderKind = EncoderKind.MPNN,
    ) -> None:
        self.targets = TargetDiscoveryModel(encoder_kind=target_kind)
        self.links = LinkPredictionModel(encoder_kind=link_kind)

    def attach_names(self, scores: Sequence[TargetScore], network: SignalingNetwork) -> None:
        for s in scores:
            if s.entity_id in network.registry:
                s.name = network.registry.get(s.entity_id).name
