"""
Structured persistence & versioned ETL for CISTRON Phase 6.

SQLite-backed run store that snapshots networks, trajectories, PK concentration
paths, and Graph-ML embeddings with content hashes so saved runs can be
reconstructed without structural drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid

from cistron.components import (
    ActivityState,
    BiologicalEntity,
    Complex,
    EntityType,
    Gene,
    KineticParameters,
    Ligand,
    Protein,
    RNA,
    Receptor,
)
from cistron.graph_ml import GraphTensors, NodeIndexMap
from cistron.simulation import (
    SimulationConfig,
    SimulatorBackend,
    TrajectoryResult,
)
from cistron.topology import (
    InteractionEdge,
    InteractionType,
    LogicGate,
    NodeLogic,
    SignalingNetwork,
)

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

SCHEMA_VERSION = 1
_DEFAULT_DB_NAME = "cistron_runs.sqlite3"


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if hasattr(obj, "value") and not isinstance(obj, (str, bytes)):
        try:
            return obj.value  # Enum
        except Exception:
            pass
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serialisable")


def _json_loads(text: str) -> Any:
    return json.loads(text)


def content_hash(payload: Any) -> str:
    """Stable SHA-256 of a JSON-normalised payload."""
    blob = _json_dumps(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def default_storage_path() -> Path:
    root = Path.home() / ".cistron"
    root.mkdir(parents=True, exist_ok=True)
    return root / _DEFAULT_DB_NAME


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def serialize_kinetics(k: KineticParameters) -> Dict[str, float]:
    return {
        "production_rate": k.production_rate,
        "degradation_rate": k.degradation_rate,
        "basal_activity": k.basal_activity,
        "km": k.km,
        "vmax": k.vmax,
        "binding_affinity": k.binding_affinity,
        "diffusion_coefficient": k.diffusion_coefficient,
    }


def serialize_entity(entity: BiologicalEntity) -> Dict[str, Any]:
    base = entity.to_dict()
    base["kinetics"] = serialize_kinetics(entity.kinetics)
    if isinstance(entity, Gene):
        base["gene"] = {
            "transcription_rate": entity.transcription_rate,
            "promoter_strength": entity.promoter_strength,
            "chromosomal_locus": entity.chromosomal_locus,
            "expressed_rna_id": entity.expressed_rna_id,
        }
    elif isinstance(entity, RNA):
        base["rna"] = {
            "translation_rate": entity.translation_rate,
            "half_life": entity.half_life,
            "is_coding": entity.is_coding,
            "source_gene_id": entity.source_gene_id,
            "product_protein_id": entity.product_protein_id,
        }
    elif isinstance(entity, Protein):
        base["protein"] = {
            "is_enzyme": entity.is_enzyme,
            "molecular_weight_kda": entity.molecular_weight_kda,
            "sequence_length": entity.sequence_length,
            "source_rna_id": entity.source_rna_id,
        }
    elif isinstance(entity, Receptor):
        base["receptor"] = {
            "cognate_ligand_ids": sorted(entity.cognate_ligand_ids),
        }
    elif isinstance(entity, Ligand):
        base["ligand"] = {}
    elif isinstance(entity, Complex):
        base["complex"] = {"members": dict(getattr(entity, "members", {}))}
    elif entity.entity_type is EntityType.COMPARTMENT:
        base["compartment"] = {"volume": float(entity.concentration)}
    return base


def deserialize_entity(payload: Mapping[str, Any]) -> BiologicalEntity:
    etype = str(payload.get("entity_type", "PROTEIN")).upper()
    kin_raw = dict(payload.get("kinetics") or {})
    kinetics = KineticParameters(**{k: float(kin_raw[k]) for k in kin_raw})
    common = {
        "name": str(payload["name"]),
        "entity_id": str(payload["entity_id"]),
        "compartment_id": payload.get("compartment_id"),
        "concentration": float(payload.get("concentration", 0.0)),
        "kinetics": kinetics,
        "metadata": dict(payload.get("metadata") or {}),
        "locked": bool(payload.get("locked", False)),
    }
    bool_raw = payload.get("boolean_state", "OFF")
    if isinstance(bool_raw, int):
        boolean = ActivityState(bool_raw)
    else:
        boolean = ActivityState[str(bool_raw)]

    if etype == "GENE":
        g = dict(payload.get("gene") or {})
        ent: BiologicalEntity = Gene(
            transcription_rate=float(g.get("transcription_rate", 1.0)),
            promoter_strength=float(g.get("promoter_strength", 1.0)),
            chromosomal_locus=g.get("chromosomal_locus"),
            expressed_rna_id=g.get("expressed_rna_id"),
            **common,
        )
    elif etype == "RNA":
        r = dict(payload.get("rna") or {})
        ent = RNA(
            translation_rate=float(r.get("translation_rate", 1.0)),
            half_life=float(r.get("half_life", 2.0)),
            is_coding=bool(r.get("is_coding", True)),
            source_gene_id=r.get("source_gene_id"),
            product_protein_id=r.get("product_protein_id"),
            **common,
        )
    elif etype == "RECEPTOR":
        rc = dict(payload.get("receptor") or {})
        ent = Receptor(
            cognate_ligand_ids=set(rc.get("cognate_ligand_ids") or []),
            **common,
        )
    elif etype == "LIGAND":
        ent = Ligand(**common)
    elif etype == "COMPLEX":
        cx = dict(payload.get("complex") or {})
        ent = Complex(members=dict(cx.get("members") or {}), **common)
    elif etype == "COMPARTMENT":
        cp = dict(payload.get("compartment") or {})
        vol = float(cp.get("volume", payload.get("concentration", 1.0)))
        ent = BiologicalEntity(
            name=str(payload["name"]),
            entity_type=EntityType.COMPARTMENT,
            entity_id=str(payload["entity_id"]),
            compartment_id=payload.get("compartment_id"),
            concentration=vol,
            kinetics=kinetics,
            metadata=dict(payload.get("metadata") or {}),
            locked=bool(payload.get("locked", False)),
        )
    else:
        pr = dict(payload.get("protein") or {})
        ent = Protein(
            is_enzyme=bool(pr.get("is_enzyme", False)),
            molecular_weight_kda=pr.get("molecular_weight_kda"),
            sequence_length=pr.get("sequence_length"),
            source_rna_id=pr.get("source_rna_id"),
            **common,
        )
    ent.boolean_state = boolean
    return ent


def serialize_network(network: SignalingNetwork) -> Dict[str, Any]:
    nodes = []
    for nid in network.nodes():
        entity = network.registry.get(nid)
        payload = serialize_entity(entity)
        logic = network.get_node_logic(nid)
        payload["logic_gate"] = logic.gate.value
        payload["inhibitor_veto"] = logic.inhibitor_veto
        payload["logic_threshold"] = logic.threshold
        nodes.append(payload)
    edges = [e.to_dict() for e in network.edges()]
    return {
        "schema_version": SCHEMA_VERSION,
        "name": network.name,
        "metadata": dict(network.metadata),
        "nodes": nodes,
        "edges": edges,
    }


def deserialize_network(payload: Mapping[str, Any]) -> SignalingNetwork:
    validate_network_payload(payload)
    net = SignalingNetwork(name=str(payload.get("name", "restored")))
    net.metadata = dict(payload.get("metadata") or {})
    for node in payload["nodes"]:
        entity = deserialize_entity(node)
        logic = NodeLogic(
            gate=LogicGate(str(node.get("logic_gate", "or"))),
            inhibitor_veto=bool(node.get("inhibitor_veto", True)),
            threshold=float(node.get("logic_threshold", 0.5)),
        )
        net.add_node(entity, logic=logic)
    for edge in payload["edges"]:
        itype = InteractionType(str(edge["interaction_type"]))
        rebuilt = InteractionEdge(
            source_id=str(edge["source_id"]),
            target_id=str(edge["target_id"]),
            interaction_type=itype,
            edge_id=str(edge.get("edge_id") or ""),
            weight=float(edge.get("weight", 1.0)),
            rate_constant=float(edge.get("rate_constant", 1.0)),
            hill_coefficient=float(edge.get("hill_coefficient", 1.0)),
            ec50=float(edge.get("ec50", 0.5)),
            delay=int(edge.get("delay", 0)),
            logic_role=edge.get("logic_role"),
            metadata=dict(edge.get("metadata") or {}),
            active=bool(edge.get("active", True)),
        )
        # Register without regenerating id
        net._edges[rebuilt.edge_id] = rebuilt
        net._out[rebuilt.source_id].add(rebuilt.edge_id)
        net._in[rebuilt.target_id].add(rebuilt.edge_id)
        for endpoint in (rebuilt.source_id, rebuilt.target_id):
            if endpoint not in net._nodes:
                raise ValueError(f"Edge endpoint {endpoint!r} missing from restored nodes")
            if endpoint not in net._node_logic:
                net._node_logic[endpoint] = NodeLogic()
    return net


def validate_network_payload(payload: Mapping[str, Any]) -> None:
    if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
        raise SchemaValidationError(
            f"Unsupported network schema_version={payload.get('schema_version')}; "
            f"expected {SCHEMA_VERSION}"
        )
    if "nodes" not in payload or "edges" not in payload:
        raise SchemaValidationError("Network payload requires nodes and edges")
    ids = {str(n["entity_id"]) for n in payload["nodes"]}
    if len(ids) != len(payload["nodes"]):
        raise SchemaValidationError("Duplicate entity_id in network snapshot")
    for edge in payload["edges"]:
        if edge["source_id"] not in ids or edge["target_id"] not in ids:
            raise SchemaValidationError(
                f"Edge {edge.get('edge_id')} references unknown endpoints"
            )


def serialize_trajectory(traj: TrajectoryResult) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "times": list(traj.times),
        "concentrations": [dict(sample) for sample in traj.concentrations],
        "boolean_states": [dict(sample) for sample in traj.boolean_states],
        "backend": traj.backend.name if isinstance(traj.backend, SimulatorBackend) else str(traj.backend),
        "metadata": dict(traj.metadata),
    }


def deserialize_trajectory(payload: Mapping[str, Any]) -> TrajectoryResult:
    validate_trajectory_payload(payload)
    backend_name = str(payload.get("backend", "ODE"))
    try:
        backend = SimulatorBackend[backend_name]
    except KeyError:
        backend = SimulatorBackend.ODE
    return TrajectoryResult(
        times=[float(t) for t in payload["times"]],
        concentrations=[dict(s) for s in payload["concentrations"]],
        boolean_states=[{k: int(v) for k, v in dict(s).items()} for s in payload["boolean_states"]],
        backend=backend,
        metadata=dict(payload.get("metadata") or {}),
    )


def validate_trajectory_payload(payload: Mapping[str, Any]) -> None:
    if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
        raise SchemaValidationError(
            f"Unsupported trajectory schema_version={payload.get('schema_version')}"
        )
    times = payload.get("times")
    conc = payload.get("concentrations")
    bools = payload.get("boolean_states")
    if not isinstance(times, list) or not isinstance(conc, list) or not isinstance(bools, list):
        raise SchemaValidationError("Trajectory arrays must be lists")
    if not (len(times) == len(conc) == len(bools)):
        raise SchemaValidationError(
            f"Trajectory length mismatch: times={len(times)} conc={len(conc)} bool={len(bools)}"
        )
    if times:
        keys0 = set(conc[0].keys())
        for i, sample in enumerate(conc):
            if set(sample.keys()) != keys0:
                raise SchemaValidationError(f"Concentration key drift at sample {i}")


def serialize_graph_tensors(tensors: GraphTensors) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "x": [row[:] for row in tensors.x],
        "edge_index": [tensors.edge_index[0][:], tensors.edge_index[1][:]],
        "edge_attr": [row[:] for row in tensors.edge_attr],
        "node_ids": list(tensors.index_map.node_ids),
        "edge_ids": list(tensors.edge_ids),
        "node_feature_names": list(tensors.node_feature_names),
        "edge_feature_names": list(tensors.edge_feature_names),
        "metadata": dict(tensors.metadata),
    }


def deserialize_graph_tensors(payload: Mapping[str, Any]) -> GraphTensors:
    if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
        raise SchemaValidationError("Unsupported graph tensor schema_version")
    node_ids = list(payload["node_ids"])
    x = payload["x"]
    if len(x) != len(node_ids):
        raise SchemaValidationError("Graph tensor X rows != node_ids")
    return GraphTensors(
        x=[list(map(float, row)) for row in x],
        edge_index=[list(map(int, payload["edge_index"][0])), list(map(int, payload["edge_index"][1]))],
        edge_attr=[list(map(float, row)) for row in payload.get("edge_attr") or []],
        index_map=NodeIndexMap(node_ids=node_ids),
        edge_ids=list(payload.get("edge_ids") or []),
        node_feature_names=list(payload.get("node_feature_names") or []),
        edge_feature_names=list(payload.get("edge_feature_names") or []),
        metadata=dict(payload.get("metadata") or {}),
    )


class SchemaValidationError(ValueError):
    """Raised when a persisted payload fails structural validation."""


# ---------------------------------------------------------------------------
# Run records
# ---------------------------------------------------------------------------


@dataclass
class RunRecord:
    run_id: str
    name: str
    created_at: float
    schema_version: int
    backend: str
    config: Dict[str, Any]
    tags: Dict[str, Any]
    content_hash: str
    network_hash: str = ""
    trajectory_hash: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "backend": self.backend,
            "config": dict(self.config),
            "tags": dict(self.tags),
            "content_hash": self.content_hash,
            "network_hash": self.network_hash,
            "trajectory_hash": self.trajectory_hash,
        }


@dataclass
class StoredRun:
    """Fully materialised run package."""

    record: RunRecord
    network: SignalingNetwork
    trajectory: TrajectoryResult
    pk_paths: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    embeddings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    graph_tensors: Optional[GraphTensors] = None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class SimulationStore:
    """
    High-throughput SQLite registry for versioned simulation runs.

    Thread-safe via a re-entrant lock around connection use.
    """

    def __init__(self, path: Optional[PathLike] = None) -> None:
        if path is None:
            path = default_storage_path()
        self.path = Path(path) if path != ":memory:" else Path(":memory:")
        self._memory = str(path) == ":memory:"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            ":memory:" if self._memory else str(self.path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SimulationStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    schema_version INTEGER NOT NULL,
                    backend TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS network_snapshots (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS trajectories (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS pk_paths (
                    run_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    times_json TEXT NOT NULL,
                    concentrations_json TEXT NOT NULL,
                    PRIMARY KEY(run_id, agent_name),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS embeddings (
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY(run_id, kind),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY(run_id, name),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
                """
            )
            cur.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    # -- save ---------------------------------------------------------------

    def save_run(
        self,
        network: SignalingNetwork,
        trajectory: TrajectoryResult,
        *,
        name: str = "",
        config: Optional[SimulationConfig] = None,
        tags: Optional[Mapping[str, Any]] = None,
        pk_paths: Optional[Mapping[str, Mapping[str, Sequence[float]]]] = None,
        embeddings: Optional[Mapping[str, Sequence[Sequence[float]]]] = None,
        embedding_node_ids: Optional[Mapping[str, Sequence[str]]] = None,
        graph_tensors: Optional[GraphTensors] = None,
        run_id: Optional[str] = None,
    ) -> RunRecord:
        """
        Persist a complete run. Returns the :class:`RunRecord` with hashes.
        """
        rid = run_id or f"run_{uuid.uuid4().hex[:16]}"
        net_payload = serialize_network(network)
        traj_payload = serialize_trajectory(trajectory)
        validate_network_payload(net_payload)
        validate_trajectory_payload(traj_payload)
        net_hash = content_hash(net_payload)
        traj_hash = content_hash(traj_payload)
        cfg = {}
        if config is not None:
            cfg = {
                "t_start": config.t_start,
                "t_end": config.t_end,
                "dt": config.dt,
                "boolean_steps": config.boolean_steps,
                "stepper": getattr(config.stepper, "value", str(config.stepper)),
                "record_every": config.record_every,
            }
        tag_map = dict(tags or {})
        envelope = {
            "network_hash": net_hash,
            "trajectory_hash": traj_hash,
            "config": cfg,
            "tags": tag_map,
        }
        rec_hash = content_hash(envelope)
        backend = traj_payload.get("backend", "ODE")
        created = time.time()
        display = name or f"{network.name}:{rid}"

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO runs(run_id, name, created_at, schema_version, backend,
                                 config_json, tags_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    display,
                    created,
                    SCHEMA_VERSION,
                    backend,
                    _json_dumps(cfg),
                    _json_dumps(tag_map),
                    rec_hash,
                ),
            )
            cur.execute(
                """
                INSERT INTO network_snapshots(run_id, payload_json, content_hash)
                VALUES (?, ?, ?)
                """,
                (rid, _json_dumps(net_payload), net_hash),
            )
            cur.execute(
                """
                INSERT INTO trajectories(run_id, payload_json, content_hash)
                VALUES (?, ?, ?)
                """,
                (rid, _json_dumps(traj_payload), traj_hash),
            )
            if pk_paths:
                for agent, path in pk_paths.items():
                    times = list(path.get("times") or [])
                    concs = list(path.get("concentrations") or [])
                    if len(times) != len(concs):
                        raise SchemaValidationError(
                            f"PK path {agent!r} times/concentrations length mismatch"
                        )
                    cur.execute(
                        """
                        INSERT INTO pk_paths(run_id, agent_name, times_json, concentrations_json)
                        VALUES (?, ?, ?, ?)
                        """,
                        (rid, agent, _json_dumps(times), _json_dumps(concs)),
                    )
            if embeddings:
                for kind, matrix in embeddings.items():
                    node_ids = list((embedding_node_ids or {}).get(kind) or [])
                    emb_payload = {
                        "schema_version": SCHEMA_VERSION,
                        "kind": kind,
                        "node_ids": node_ids,
                        "matrix": [list(map(float, row)) for row in matrix],
                    }
                    cur.execute(
                        """
                        INSERT INTO embeddings(run_id, kind, payload_json, content_hash)
                        VALUES (?, ?, ?, ?)
                        """,
                        (rid, kind, _json_dumps(emb_payload), content_hash(emb_payload)),
                    )
            if graph_tensors is not None:
                gt = serialize_graph_tensors(graph_tensors)
                cur.execute(
                    """
                    INSERT INTO artifacts(run_id, name, payload_json, content_hash)
                    VALUES (?, ?, ?, ?)
                    """,
                    (rid, "graph_tensors", _json_dumps(gt), content_hash(gt)),
                )

        logger.info("Saved run %s (net=%s traj=%s)", rid, net_hash[:8], traj_hash[:8])
        return RunRecord(
            run_id=rid,
            name=display,
            created_at=created,
            schema_version=SCHEMA_VERSION,
            backend=str(backend),
            config=cfg,
            tags=tag_map,
            content_hash=rec_hash,
            network_hash=net_hash,
            trajectory_hash=traj_hash,
        )

    # -- load ---------------------------------------------------------------

    def get_record(self, run_id: str) -> RunRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown run_id {run_id!r}")
        net_hash = ""
        traj_hash = ""
        with self._lock:
            n = self._conn.execute(
                "SELECT content_hash FROM network_snapshots WHERE run_id = ?", (run_id,)
            ).fetchone()
            t = self._conn.execute(
                "SELECT content_hash FROM trajectories WHERE run_id = ?", (run_id,)
            ).fetchone()
            if n:
                net_hash = n["content_hash"]
            if t:
                traj_hash = t["content_hash"]
        return RunRecord(
            run_id=row["run_id"],
            name=row["name"],
            created_at=row["created_at"],
            schema_version=row["schema_version"],
            backend=row["backend"],
            config=_json_loads(row["config_json"]),
            tags=_json_loads(row["tags_json"]),
            content_hash=row["content_hash"],
            network_hash=net_hash,
            trajectory_hash=traj_hash,
        )

    def load_run(self, run_id: str, *, verify: bool = True) -> StoredRun:
        record = self.get_record(run_id)
        if record.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"Run {run_id} schema_version={record.schema_version} != {SCHEMA_VERSION}"
            )
        with self._lock:
            net_row = self._conn.execute(
                "SELECT payload_json, content_hash FROM network_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            traj_row = self._conn.execute(
                "SELECT payload_json, content_hash FROM trajectories WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            pk_rows = self._conn.execute(
                "SELECT agent_name, times_json, concentrations_json FROM pk_paths WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            emb_rows = self._conn.execute(
                "SELECT kind, payload_json FROM embeddings WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            art = self._conn.execute(
                "SELECT payload_json FROM artifacts WHERE run_id = ? AND name = ?",
                (run_id, "graph_tensors"),
            ).fetchone()

        if net_row is None or traj_row is None:
            raise KeyError(f"Incomplete run {run_id!r}")

        net_payload = _json_loads(net_row["payload_json"])
        traj_payload = _json_loads(traj_row["payload_json"])
        if verify:
            validate_network_payload(net_payload)
            validate_trajectory_payload(traj_payload)
            if content_hash(net_payload) != net_row["content_hash"]:
                raise SchemaValidationError(f"Network hash mismatch for {run_id}")
            if content_hash(traj_payload) != traj_row["content_hash"]:
                raise SchemaValidationError(f"Trajectory hash mismatch for {run_id}")

        network = deserialize_network(net_payload)
        trajectory = deserialize_trajectory(traj_payload)
        pk_paths: Dict[str, Dict[str, List[float]]] = {}
        for row in pk_rows:
            pk_paths[row["agent_name"]] = {
                "times": list(map(float, _json_loads(row["times_json"]))),
                "concentrations": list(map(float, _json_loads(row["concentrations_json"]))),
            }
        embeddings: Dict[str, Dict[str, Any]] = {}
        for row in emb_rows:
            embeddings[row["kind"]] = _json_loads(row["payload_json"])
        gt = None
        if art is not None:
            gt = deserialize_graph_tensors(_json_loads(art["payload_json"]))

        # Reproducibility: restored network node set must match trajectory keys
        if verify and trajectory.concentrations:
            traj_keys = set(trajectory.concentrations[0].keys())
            net_keys = set(network.nodes())
            # Compartment nodes may be absent from ODE state
            missing = traj_keys - net_keys
            if missing:
                raise SchemaValidationError(
                    f"Trajectory entities absent from restored network: {sorted(missing)[:5]}"
                )

        return StoredRun(
            record=record,
            network=network,
            trajectory=trajectory,
            pk_paths=pk_paths,
            embeddings=embeddings,
            graph_tensors=gt,
        )

    def list_runs(self, *, limit: int = 100) -> List[RunRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self.get_record(r["run_id"]) for r in rows]

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pk_paths WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM embeddings WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM artifacts WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM trajectories WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM network_snapshots WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    def verify_run(self, run_id: str) -> bool:
        """Load with hash checks; returns True if intact."""
        self.load_run(run_id, verify=True)
        return True
