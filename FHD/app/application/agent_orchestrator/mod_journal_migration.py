"""Migrate historical Mod task journals without deleting or replaying them."""

import json
import threading
from typing import Any, cast

from sqlalchemy import Table, inspect, select
from sqlalchemy.engine import Engine

from app.db.models.agent import (
    AgentRunRecord,
    AgentTaskCommandRecord,
    AgentTaskExecutionRecord,
    AgentTaskRecord,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class LegacyJournalMigrationError(RuntimeError):
    """Never replace a failed history migration with an empty memory store."""


_lock = threading.RLock()
_copied: set[tuple[int, int, str]] = set()
_terminal = {"completed", "failed", "cancelled"}


def copy_legacy_journal(source: Engine, host: Engine, mod_id: str) -> dict[str, int]:
    if source is host or source.url == host.url:
        return {"runs": 0, "tasks": 0, "commands": 0, "executions": 0}
    models = [AgentRunRecord, AgentTaskRecord, AgentTaskCommandRecord, AgentTaskExecutionRecord]
    tables = [cast(Table, model.__table__) for model in models]
    source_tables = set(inspect(source).get_table_names())
    if "agent_runs" not in source_tables:
        return {"runs": 0, "tasks": 0, "commands": 0, "executions": 0}
    for table in tables:
        table.create(host, checkfirst=True)
    counts = {"runs": 0, "tasks": 0, "commands": 0, "executions": 0}
    with source.connect() as origin, host.begin() as target:
        queue_table = tables[3]
        uncertain = (
            set(
                origin.execute(
                    select(queue_table.c.run_id).where(queue_table.c.state == "claimed")
                ).scalars()
            )
            if queue_table.name in source_tables
            else set()
        )
        blocked_runs = set(uncertain)
        for index, table in enumerate(tables):
            if table.name not in source_tables:
                continue
            for source_row in origin.execute(select(table)).mappings():
                data: dict[str, Any] = dict(source_row)
                if table.name == "agent_tasks":
                    predicate = (
                        table.c.task_id == data["task_id"],
                        table.c.user_id == data["user_id"],
                        table.c.tenant_id == data["tenant_id"],
                    )
                    existing = target.execute(select(table).where(*predicate)).mappings().first()
                    if existing and existing["root_run_id"] != data["root_run_id"]:
                        raise ValueError(f"legacy task identity conflict in Mod {mod_id}")
                else:
                    key = next(iter(table.primary_key.columns)).name
                    existing = (
                        target.execute(select(table).where(table.c[key] == data[key]))
                        .mappings()
                        .first()
                    )
                    if existing and "user_id" in data and existing["user_id"] != data["user_id"]:
                        raise ValueError(f"legacy run owner conflict in Mod {mod_id}")
                if existing:
                    continue  # New host state is authoritative; never resurrect old queue rows.
                if table.name == "agent_runs":
                    payload = json.loads(data["payload_json"])
                    metadata = payload.setdefault("metadata", {})
                    metadata["legacy_mod_scope_required"] = mod_id
                    if data["status"] not in _terminal:
                        unknown = (
                            data["status"] in {"running", "retrying"} or data["run_id"] in uncertain
                        )
                        metadata["legacy_previous_status"] = data["status"]
                        metadata["legacy_execution_snapshot"] = {
                            key: metadata.pop(key)
                            for key in ("dispatch", "execution", "schedule_authorization")
                            if key in metadata
                        }
                        data["status"] = payload["status"] = "blocked" if unknown else "paused"
                        if unknown:
                            blocked_runs.add(data["run_id"])
                            metadata["non_retryable"] = True
                            metadata["legacy_execution_unknown"] = True
                        metadata["control"] = {"state": "paused", "resume_status": "waiting_user"}
                        pending = [
                            step
                            for step in payload.get("steps", [])
                            if step.get("status") not in (_terminal | {"skipped"})
                        ]
                        for step in pending:
                            step["status"] = "pending"
                        if pending and not unknown:
                            pending[0]["status"] = "waiting_user"
                    data["payload_json"] = json.dumps(payload, ensure_ascii=False)
                elif table.name == "agent_tasks":
                    data.pop("id", None)
                    if data["status"] not in _terminal:
                        data["status"] = (
                            "blocked" if data["active_run_id"] in blocked_runs else "paused"
                        )
                        data["attention_state"] = (
                            "approval_required" if data["status"] == "paused" else "error"
                        )
                elif table.name == "agent_task_executions":
                    if data["state"] not in _terminal:
                        data["state"] = "blocked" if data["run_id"] in blocked_runs else "paused"
                    data.update(lease_owner=None, lease_expires_at=None, heartbeat_at=None)
                target.execute(table.insert().values(**data))
                counts[list(counts)[index]] += 1
    return counts


def migrate_current_mod_journal() -> None:
    from app.db import get_host_engine, get_runtime_engine
    from app.request_active_mod_ctx import get_request_active_mod_id

    mod_id = get_request_active_mod_id()
    if not mod_id:
        return
    source, host = get_runtime_engine(), get_host_engine()
    key = (id(source), id(host), mod_id)
    with _lock:
        if key in _copied:
            return
        try:
            copy_legacy_journal(source, host, mod_id)
        except RECOVERABLE_ERRORS as exc:
            raise LegacyJournalMigrationError(
                f"Mod {mod_id} task history migration failed; original database retained"
            ) from exc
        _copied.add(key)
