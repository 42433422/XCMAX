from __future__ import annotations

import json
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from retort_engine.models import EmployeeTaskRecord, EmployeeTaskResult, ImprovementTask


class RetortEmployeeQueue:
    """Durable JSONL queue with process-wide arbitration and logical identities.

    A repeated (source, task_id) is a replay, not a new execution. Unknown
    dispatch outcomes remain blocked for reconciliation instead of being retried.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + ".lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write(self, rows: list[dict[str, Any]]) -> None:
        """Caller holds the lock; replacement never exposes a partial JSON line."""
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                temporary = handle.name
                if self.path.exists():
                    os.chmod(temporary, stat.S_IMODE(self.path.stat().st_mode))
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            if os.name == "posix":
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _record(row: dict[str, Any]) -> EmployeeTaskRecord:
        return EmployeeTaskRecord(
            str(row["queue_id"]), ImprovementTask(**row["task"]),
            str(row["source"]), str(row.get("status", "queued")),
            str(row.get("created_at", "")),
        )

    def enqueue_employee_task(
        self, task: ImprovementTask, *, source: str, status: str = "queued"
    ) -> EmployeeTaskRecord:
        if not source.strip() or not task.task_id.strip():
            raise ValueError("source and task_id are required for idempotent submission")
        with self._locked():
            rows = list(self.load())
            matches = [row for row in rows if row.get("source") == source
                       and row.get("task", {}).get("task_id") == task.task_id]
            if len(matches) > 1:
                raise ValueError("duplicate legacy logical task; reconciliation required")
            if matches:
                existing = self._record(matches[0])
                if existing.task != task:
                    raise ValueError("logical task identity reused with a different payload")
                return existing
            identity = json.dumps([source, task.task_id], ensure_ascii=False)
            record = EmployeeTaskRecord(
                str(uuid.uuid5(uuid.NAMESPACE_URL, identity)), task, source, status,
                datetime.now(timezone.utc).isoformat(),
            )
            rows.append(record.to_dict())
            self._write(rows)
            return record

    def enqueue_tasks(
        self, tasks: tuple[ImprovementTask, ...] | list[ImprovementTask], *, source: str
    ) -> tuple[EmployeeTaskRecord, ...]:
        return tuple(self.enqueue_employee_task(task, source=source) for task in tasks)

    def claim_dispatch(self, record: EmployeeTaskRecord) -> EmployeeTaskRecord | None:
        with self._locked():
            rows = list(self.load())
            matches = [row for row in rows if row.get("queue_id") == record.queue_id]
            if len(matches) != 1:
                raise ValueError("queue record is missing or ambiguous")
            row = matches[0]
            stored = self._record(row)
            if stored.source != record.source or stored.task != record.task:
                raise ValueError("dispatch payload does not match persisted task")
            if stored.status != "queued":
                return None
            row["status"] = "dispatching"
            self._write(rows)
            return self._record(row)

    def finish_dispatch(self, queue_id: str, *, status: str) -> None:
        if status not in {"dispatched", "dispatch_unknown"}:
            raise ValueError("invalid dispatch outcome")
        with self._locked():
            rows = list(self.load())
            matches = [row for row in rows if row.get("queue_id") == queue_id]
            if len(matches) != 1 or matches[0].get("status") != "dispatching":
                raise ValueError("dispatch claim is no longer current")
            matches[0]["status"] = status
            self._write(rows)

    def load(self) -> tuple[dict[str, Any], ...]:
        if not self.path.is_file():
            return ()
        rows = tuple(json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line)
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid queue record; refusing to overwrite durable data")
        return rows


def parse_employee_task_result(payload: dict[str, Any]) -> EmployeeTaskResult:
    evidence = payload.get("evidence") or ()
    if isinstance(evidence, str):
        evidence = (evidence,)
    score_after = payload.get("score_after") or {}
    if not isinstance(score_after, dict):
        score_after = {}
    return EmployeeTaskResult(
        task_id=str(payload.get("task_id") or ""),
        status=str(payload.get("status") or "unknown"),
        summary=str(payload.get("summary") or ""),
        evidence=tuple(str(item) for item in evidence),
        score_after={str(k): float(v) for k, v in score_after.items()},
    )
