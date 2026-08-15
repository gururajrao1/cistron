"""In-process async job board — Celery/Redis-free substitute for Render Free.

Jobs run in a bounded thread pool. State is process-local (lost on restart).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
import threading
import time
import uuid

_LOCK = threading.Lock()
_JOBS: Dict[str, "JobRecord"] = {}
_EXEC = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cistron-job")


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Any = None
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "has_result": self.result is not None,
        }


def submit_job(kind: str, fn: Callable[[], Any]) -> str:
    jid = uuid.uuid4().hex[:16]
    rec = JobRecord(id=jid, kind=kind)
    with _LOCK:
        _JOBS[jid] = rec
        # Cap memory: drop oldest finished jobs beyond 32
        if len(_JOBS) > 40:
            done = sorted(
                (j for j in _JOBS.values() if j.status in {"done", "error"}),
                key=lambda j: j.updated_at,
            )
            for old in done[: max(0, len(_JOBS) - 32)]:
                _JOBS.pop(old.id, None)

    def _run() -> None:
        with _LOCK:
            rec.status = "running"
            rec.updated_at = time.time()
        try:
            out = fn()
            with _LOCK:
                rec.result = out
                rec.status = "done"
                rec.updated_at = time.time()
        except Exception as exc:  # noqa: BLE001
            with _LOCK:
                rec.error = f"{type(exc).__name__}: {exc}"
                rec.status = "error"
                rec.updated_at = time.time()

    _EXEC.submit(_run)
    return jid


def get_job(job_id: str) -> Optional[JobRecord]:
    with _LOCK:
        return _JOBS.get(job_id)
