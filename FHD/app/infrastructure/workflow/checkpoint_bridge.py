"""LangGraph checkpoint adapter for the workflow ``CheckpointStore`` port.

LG-W1-T4: bridge the application-layer ``CheckpointStore`` protocol to a
vendored LangGraph checkpoint saver (``SqliteSaver`` or ``PostgresSaver``).
The legacy two-layer storage (``WorkflowCheckpointer`` /
``DatabaseWorkflowCheckpointer``) is replaced by this single adapter that
persists runtime snapshots as LangGraph checkpoints.

Namespace mapping
-----------------
- ``thread_id``     -> ``f"lg:{tenant_id}:{run_namespace}:{plan_id}"``.
- ``checkpoint_ns`` -> ``f"{tenant_id}/{run_namespace}"`` (XCAGI LangGraph
  checkpoint plane carrying the tenant/run namespace).
- ``checkpoint_id`` -> LangGraph checkpoint ``id`` (time-ordered ``uuid6``,
  so the saver's ``get_tuple`` / ``list`` order by recency, which makes
  ``latest_checkpoint`` return the most advanced step).
- snapshot fields   -> stored whole under the ``__workflow__`` channel value
  (``step_index``, ``runtime_context``, ``executed_nodes``, ``blocked``).

This adapter depends only on the application port and the injected saver; it
never imports ``sqlalchemy`` or ``fastapi``.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Any, Iterator

from langgraph.checkpoint.base.id import uuid6

_LG_PREFIX = "lg"
_SNAPSHOT_CHANNEL = "__workflow__"

_Saver = Any

# Comparison-only declarations for the pinned vendored SqliteSaver. Its setup()
# remains the only DDL owner; guarded serving must use an offline-provisioned DB.
_SQLITE_CHECKPOINT_SCHEMA = {
    "checkpoints": """CREATE TABLE checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint BLOB,
        metadata BLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )""",
    "writes": """CREATE TABLE writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        channel TEXT NOT NULL,
        type TEXT,
        value BLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )""",
}


def validate_sqlite_checkpoint_schema(
    connection: sqlite3.Connection, *, allow_missing: bool = False
) -> None:
    """Inspect existing native storage without DDL, repair, or shadow-table access."""
    compact = lambda sql: re.sub(r"\s+", "", str(sql or "")).lower()
    for table, ddl in _SQLITE_CHECKPOINT_SCHEMA.items():
        actual = {
            (kind, name): compact(sql)
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM main.sqlite_master WHERE tbl_name=?", (table,)
            )
        }
        expected = {
            ("table", table): compact(ddl),
            ("index", f"sqlite_autoindex_{table}_1"): "",
        }
        if (actual != expected and not (allow_missing and not actual)) or connection.execute(
            "SELECT 1 FROM temp.sqlite_master WHERE name=? OR tbl_name=? LIMIT 1",
            (table, table),
        ).fetchone():
            raise ValueError(f"native checkpoint schema requires offline provisioning: {table}")


@contextmanager
def open_run_checkpointer(repository: Any) -> Iterator[Any]:
    """Use the run repository's database, never an unrelated process-local fallback.

    In-memory repositories are explicit development/test adapters. SQL-backed
    runs must open their real saver successfully before any graph node executes.
    ``ClaimedRunRepository`` delegates ``transaction`` and schema setup policy to
    its fenced host store. Existing repository adapters without an explicit policy
    retain automatic setup, including PostgreSQL startup initialization.
    """
    transaction = getattr(repository, "transaction", None)
    if transaction is None:
        yield None
        return
    with transaction(read_only=True) as db:
        bind = db.get_bind()
        url = bind.url
    allow_setup = getattr(repository, "allows_schema_setup", True) is not False
    if url.get_backend_name() == "sqlite":
        if not url.database or url.database == ":memory:":
            raise ValueError("持久任务检查点需要文件 SQLite 或 PostgreSQL")
        from langgraph.checkpoint.sqlite import SqliteSaver

        target = (
            str(url.database) if allow_setup else Path(url.database).resolve().as_uri() + "?mode=rw"
        )
        with closing(
            sqlite3.connect(target, uri=not allow_setup, check_same_thread=False)
        ) as sqlite_connection:
            saver = SqliteSaver(sqlite_connection)
            if allow_setup:
                saver.setup()
            else:
                validate_sqlite_checkpoint_schema(sqlite_connection)
                saver.is_setup = True
            yield saver
    elif url.get_backend_name() == "postgresql":
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection

        # Borrow the configured engine connection so TLS, search_path and all
        # connect_args stay identical to the host store; never reconstruct a DSN.
        pooled = bind.raw_connection()
        connection = pooled.driver_connection
        if not isinstance(connection, Connection):
            pooled.close()
            raise ValueError("PostgreSQL 持久检查点需要 postgresql+psycopg 驱动")
        autocommit = connection.autocommit
        try:
            connection.autocommit = True
            postgres_saver = PostgresSaver(connection)
            if not allow_setup:
                # Explicitly pre-provisioned repositories never migrate at request
                # time. Normal repositories and old adapters keep setup below.
                yield postgres_saver
                return
            # Upstream schema migrations are not concurrent. Serialize only
            # setup across processes, including CREATE INDEX CONCURRENTLY.
            with connection.cursor() as cursor:
                # A blocking advisory-lock query retains a virtual transaction
                # which CREATE INDEX CONCURRENTLY can wait on, deadlocking the
                # initializer against its waiter. Finish every failed probe in
                # autocommit mode before waiting outside PostgreSQL instead.
                for _ in range(600):
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", (7412093581,))
                    acquired = cursor.fetchone()
                    if acquired and acquired[0]:
                        break
                    sleep(0.05)
                else:
                    raise TimeoutError("PostgreSQL 检查点初始化锁等待超时")
                try:
                    postgres_saver.setup()
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (7412093581,))
            yield postgres_saver
        finally:
            try:
                connection.autocommit = autocommit
            finally:
                pooled.close()
    else:
        raise ValueError("任务数据库没有受支持的持久检查点后端")


def run_checkpoint_thread(run: Any, plan: Any, *, parallel: bool) -> str:
    """Version accepted plan revisions within the immutable tenant/user/run identity."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.task_models import tenant_id_of_run
    from app.application.workflow.workflow_types import plan_fingerprint

    previous = run.metadata.get("checkpoint")
    if previous is not None and (
        not isinstance(previous, dict)
        or previous.get("backend") != "langgraph"
        or previous.get("schema_version") != 1
    ):
        raise ValueError("任务检查点版本不受支持，需要显式迁移后恢复")
    identity = {
        "schema_version": 1,
        "tenant_id": tenant_id_of_run(run),
        "user_id": run.user_id,
        "run_id": run.run_id,
        "plan_sha256": plan_fingerprint(plan),
        "parallel": parallel,
    }
    return "agent:" + canonical_hash(identity)


def _snapshot(
    plan_id: str,
    step_index: int,
    runtime_context: dict[str, Any],
    executed_nodes: list[str] | set[str],
    blocked: list[str] | set[str] | None,
) -> dict[str, Any]:
    """Normalize a legacy snapshot into a stable, JSON-safe dict."""
    return {
        "plan_id": plan_id,
        "step_index": int(step_index),
        "runtime_context": dict(runtime_context or {}),
        "executed_nodes": sorted(executed_nodes or []),
        "blocked": sorted(blocked or []),
    }


def _to_legacy(checkpoint: Any) -> dict[str, Any]:
    """Rebuild the legacy ``Checkpoint`` dict from a LangGraph checkpoint."""
    values = checkpoint.get("channel_values", {})
    snapshot = values.get(_SNAPSHOT_CHANNEL) or {}
    return {
        "plan_id": snapshot.get("plan_id"),
        "checkpoint_id": checkpoint.get("id"),
        "step_index": snapshot.get("step_index", 0),
        "runtime_context": snapshot.get("runtime_context", {}),
        "executed_nodes": snapshot.get("executed_nodes", []),
        "blocked": snapshot.get("blocked", []),
        "created_at": checkpoint.get("ts", ""),
    }


class LanggraphCheckpointBridge:
    """A ``CheckpointStore`` adapter backed by a vendored LangGraph saver.

    ``plan_id`` is mapped to a LangGraph ``thread_id`` under a ``checkpoint_ns``
    that both derive from ``tenant_id`` / ``run_namespace``. When ``setup`` is
    true (default) the injected saver's ``setup()`` is called so the checkpoint
    tables are ready. The ``CheckpointStore`` protocol methods
    (``save_checkpoint`` / ``get_checkpoint`` / ``list_checkpoints`` /
    ``latest_checkpoint``) are thin aliases over the saver's ``put`` /
    ``get_tuple`` / ``list``, and share the short-named aliases ``save`` /
    ``get`` / ``list`` / ``latest``.
    """

    def __init__(
        self,
        saver: _Saver,
        *,
        tenant_id: str = "default",
        run_namespace: str = "default",
        setup: bool = True,
    ) -> None:
        self._saver = saver
        self._tenant_id = tenant_id
        self._run_namespace = run_namespace
        if setup:
            self._saver.setup()

    @classmethod
    def _namespace(cls, tenant_id: str, run_namespace: str) -> str:
        return f"{tenant_id}/{run_namespace}"

    @classmethod
    @contextmanager
    def from_sqlite_path(
        cls,
        path: Any,
        *,
        tenant_id: str = "default",
        run_namespace: str = "default",
        setup: bool = True,
    ) -> Iterator[LanggraphCheckpointBridge]:
        """Build a bridge over a vendored ``SqliteSaver`` rooted at ``path``."""
        from langgraph.checkpoint.sqlite import SqliteSaver

        with SqliteSaver.from_conn_string(str(path)) as saver:
            yield cls(
                saver,
                tenant_id=tenant_id,
                run_namespace=run_namespace,
                setup=setup,
            )

    @classmethod
    @contextmanager
    def from_postgres_conn_string(
        cls,
        conn_string: str,
        *,
        tenant_id: str = "default",
        run_namespace: str = "default",
        setup: bool = True,
    ) -> Iterator[LanggraphCheckpointBridge]:
        """Build a bridge over a vendored ``PostgresSaver`` (lazy import)."""
        from langgraph.checkpoint.postgres import PostgresSaver

        with PostgresSaver.from_conn_string(conn_string) as saver:
            yield cls(
                saver,
                tenant_id=tenant_id,
                run_namespace=run_namespace,
                setup=setup,
            )

    def _config(self, plan_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
        configurable: dict[str, Any] = {
            "thread_id": f"{_LG_PREFIX}:{self._tenant_id}:{self._run_namespace}:{plan_id}",
            "checkpoint_ns": self._namespace(self._tenant_id, self._run_namespace),
        }
        if checkpoint_id is not None:
            configurable["checkpoint_id"] = checkpoint_id
        return {"configurable": configurable}

    def save_checkpoint(
        self,
        plan_id: str,
        step_index: int,
        runtime_context: dict[str, Any],
        executed_nodes: list[str] | set[str],
        *,
        blocked: list[str] | set[str] | None = None,
    ) -> str:
        """Record a checkpoint and return its unique ``checkpoint_id``."""
        checkpoint_id = str(uuid6())
        checkpoint: dict[str, Any] = {
            "v": 1,
            "id": checkpoint_id,
            "ts": datetime.now(UTC).isoformat(),
            "channel_values": {
                _SNAPSHOT_CHANNEL: _snapshot(
                    plan_id, step_index, runtime_context, executed_nodes, blocked
                )
            },
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": [],
        }
        metadata: dict[str, Any] = {"source": "update", "step": int(step_index)}
        self._saver.put(self._config(plan_id), checkpoint, metadata, {})
        return checkpoint_id

    def get_checkpoint(self, plan_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """Return the snapshot for ``checkpoint_id`` under ``plan_id`` or ``None``."""
        result = self._saver.get_tuple(self._config(plan_id, checkpoint_id))
        return _to_legacy(result.checkpoint) if result is not None else None

    def list_checkpoints(self, plan_id: str) -> list[dict[str, Any]]:
        """List all checkpoints for ``plan_id`` ordered by ``step_index`` ascending."""
        tuples = list(self._saver.list(self._config(plan_id)))
        items = [_to_legacy(tp.checkpoint) for tp in tuples]
        items.sort(key=lambda cp: int(cp.get("step_index", 0)))
        return items

    def latest_checkpoint(self, plan_id: str) -> dict[str, Any] | None:
        """Return the most advanced checkpoint for ``plan_id`` or ``None``."""
        result = self._saver.get_tuple(self._config(plan_id))
        return _to_legacy(result.checkpoint) if result is not None else None

    # -- short-named thin aliases over the legacy CheckpointStore methods -----

    def save(
        self,
        plan_id: str,
        step_index: int,
        runtime_context: dict[str, Any],
        executed_nodes: list[str] | set[str],
        *,
        blocked: list[str] | set[str] | None = None,
    ) -> str:
        """Thin alias for :meth:`save_checkpoint`."""
        return self.save_checkpoint(
            plan_id, step_index, runtime_context, executed_nodes, blocked=blocked
        )

    def get(self, plan_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """Thin alias for :meth:`get_checkpoint`."""
        return self.get_checkpoint(plan_id, checkpoint_id)

    def list(self, plan_id: str) -> list[dict[str, Any]]:
        """Thin alias for :meth:`list_checkpoints`."""
        return self.list_checkpoints(plan_id)

    def latest(self, plan_id: str) -> dict[str, Any] | None:
        """Thin alias for :meth:`latest_checkpoint`."""
        return self.latest_checkpoint(plan_id)


__all__ = ["LanggraphCheckpointBridge", "open_run_checkpointer", "run_checkpoint_thread"]
