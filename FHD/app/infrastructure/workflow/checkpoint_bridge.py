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

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

from langgraph.checkpoint.base.id import uuid6

_LG_PREFIX = "lg"
_SNAPSHOT_CHANNEL = "__workflow__"

_Saver = Any


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


__all__ = ["LanggraphCheckpointBridge"]
