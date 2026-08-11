"""LG-W1-T4 — LangGraph checkpoint bridge verification (round 2).

Verifies the ``LanggraphCheckpointBridge`` adapter:
- ``from_sqlite_path`` factory over a real vendored ``SqliteSaver`` on a temp
  sqlite file, exercising the thin save/get/list/latest aliases.
- tenant/run/plan namespace isolation (cross namespace returns None/empty).
- ``from_postgres_conn_string`` factory with a lazy import, driven through a
  monkeypatched context manager (no real Postgres needed).
- the ``CheckpointStore`` runtime-checkable protocol.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.application.workflow.ports.checkpoint import CheckpointStore
from app.infrastructure.workflow.checkpoint_bridge import LanggraphCheckpointBridge


def test_vendored_savers_import() -> None:
    """SqliteSaver / PostgresSaver must resolve from the vendored packages."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.sqlite import SqliteSaver

    assert SqliteSaver.__name__ == "SqliteSaver"
    assert PostgresSaver.__name__ == "PostgresSaver"


def test_bridge_implements_checkpointstore_protocol() -> None:
    """The bridge must satisfy the runtime-checkable ``CheckpointStore``."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        bridge = LanggraphCheckpointBridge(SqliteSaver(conn))
        assert isinstance(bridge, CheckpointStore)
    finally:
        conn.close()


def test_from_sqlite_path_aliases_save_get_list_latest() -> None:
    """1 save, then get/list/latest via the thin aliases on a temp sqlite file."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "checkpoints.sqlite"
        with LanggraphCheckpointBridge.from_sqlite_path(
            db_path, tenant_id="tenA", run_namespace="run1"
        ) as bridge:
            cid = bridge.save_checkpoint("p1", 0, {"ctx": "a"}, ["n1"])

            # get
            cp = bridge.get_checkpoint("p1", cid)
            assert cp is not None
            assert cp["plan_id"] == "p1"
            assert cp["checkpoint_id"] == cid
            assert cp["step_index"] == 0
            assert cp["runtime_context"] == {"ctx": "a"}
            assert cp["executed_nodes"] == ["n1"]
            assert cp["blocked"] == []

            # list (ascending by step_index)
            assert [c["checkpoint_id"] for c in bridge.list_checkpoints("p1")] == [cid]

            # latest
            assert bridge.latest_checkpoint("p1")["checkpoint_id"] == cid


def test_tenant_run_plan_namespace_isolation() -> None:
    """Different tenant/run/plan must not leak checkpoints across namespaces."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "checkpoints.sqlite"
        with LanggraphCheckpointBridge.from_sqlite_path(
            db_path, tenant_id="tenA", run_namespace="run1"
        ) as bridge:
            cid = bridge.save_checkpoint("p1", 0, {"ctx": "a"}, ["n1"])

            # plan isolation within the same tenant/run
            assert bridge.get_checkpoint("p2", cid) is None
            assert bridge.list_checkpoints("p2") == []
            assert bridge.latest_checkpoint("p2") is None

            # different run namespace on the same instance namespace
            with LanggraphCheckpointBridge.from_sqlite_path(
                db_path, tenant_id="tenA", run_namespace="run2"
            ) as other_run:
                assert other_run.latest_checkpoint("p1") is None
                assert other_run.list_checkpoints("p1") == []

            # different tenant on the same run namespace
            with LanggraphCheckpointBridge.from_sqlite_path(
                db_path, tenant_id="tenB", run_namespace="run1"
            ) as other_tenant:
                assert other_tenant.latest_checkpoint("p1") is None
                assert other_tenant.list_checkpoints("p1") == []


def test_short_aliases_exist_and_delegate_to_legacy() -> None:
    """``save``/``get``/``list``/``latest`` exist and delegate to the protocol."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "checkpoints.sqlite"
        with LanggraphCheckpointBridge.from_sqlite_path(
            db_path, tenant_id="tenA", run_namespace="run1"
        ) as bridge:
            for name in ("save", "get", "list", "latest"):
                assert hasattr(bridge, name), name

            cid = bridge.save("p1", 0, {"ctx": "a"}, ["n1"])  # -> save_checkpoint
            assert bridge.get("p1", cid)["checkpoint_id"] == cid  # -> get_checkpoint
            assert [c["checkpoint_id"] for c in bridge.list("p1")] == [cid]  # -> list
            assert bridge.latest("p1")["checkpoint_id"] == cid  # -> latest_checkpoint


def test_from_postgres_conn_string_lazy_context(monkeypatch) -> None:
    """Postgres factory imports lazily and drives a context manager."""
    from langgraph.checkpoint.postgres import PostgresSaver

    entered: list[str] = []

    class FakeCtx:
        def __enter__(self):
            entered.append("__enter__")
            return object()

        def __exit__(self, *args):
            entered.append("__exit__")
            return False

    def fake_from_conn_string(conn_string: str, **kwargs):
        return FakeCtx()

    monkeypatch.setattr(PostgresSaver, "from_conn_string", staticmethod(fake_from_conn_string))

    with LanggraphCheckpointBridge.from_postgres_conn_string(
        "postgresql://localhost/xcagi", setup=False
    ) as bridge:
        assert isinstance(bridge, LanggraphCheckpointBridge)
        assert entered == ["__enter__"]

    assert entered == ["__enter__", "__exit__"]
