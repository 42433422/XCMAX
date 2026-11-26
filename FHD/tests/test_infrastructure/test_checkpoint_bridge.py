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
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.workflow.ports import CheckpointStore
from app.infrastructure.workflow.checkpoint_bridge import LanggraphCheckpointBridge


def test_vendored_savers_import() -> None:
    """SqliteSaver / PostgresSaver must resolve from the vendored packages."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.sqlite import SqliteSaver

    assert SqliteSaver.__name__ == "SqliteSaver"
    assert PostgresSaver.__name__ == "PostgresSaver"


@pytest.mark.parametrize("outcome", ["success", "setup-error", "lock-timeout", "preinitialized"])
def test_postgres_setup_waits_without_an_open_query_and_releases_resources(monkeypatch, outcome):
    import langgraph.checkpoint.postgres
    import psycopg
    from sqlalchemy.engine import make_url

    from app.infrastructure.workflow import checkpoint_bridge

    class Connection:
        autocommit = False
        locked = False
        probes = 0

        def cursor(self):
            return nullcontext(self)

        def execute(self, query, params):
            assert self.autocommit
            if query == "SELECT pg_try_advisory_lock(%s)":
                self.probes += 1
                self.locked = outcome != "lock-timeout" and self.probes >= 3
            elif query == "SELECT pg_advisory_unlock(%s)":
                assert self.locked
                self.locked = False
            else:
                pytest.fail("A blocking lock query can deadlock concurrent index creation")

        def fetchone(self):
            return (self.locked,)

    connection = Connection()
    closed, setups, waits = [], [], []
    pooled = SimpleNamespace(driver_connection=connection, close=lambda: closed.append(True))
    bind = SimpleNamespace(
        url=make_url("postgresql+psycopg://localhost/checkpoints"), raw_connection=lambda: pooled
    )
    repository = SimpleNamespace(
        transaction=lambda **kwargs: nullcontext(SimpleNamespace(get_bind=lambda: bind))
    )
    if outcome == "preinitialized":
        repository.allows_schema_setup = False

    def setup():
        assert connection.locked
        setups.append(True)
        if outcome == "setup-error":
            raise RuntimeError("migration failed")

    def wait(delay):
        assert connection.autocommit and not connection.locked
        waits.append(delay)

    saver = SimpleNamespace(setup=setup)
    monkeypatch.setattr(psycopg, "Connection", Connection)
    monkeypatch.setattr(langgraph.checkpoint.postgres, "PostgresSaver", lambda conn: saver)
    monkeypatch.setattr(checkpoint_bridge, "sleep", wait)
    if outcome in {"success", "preinitialized"}:
        with checkpoint_bridge.open_run_checkpointer(repository) as opened:
            assert opened is saver
    else:
        expected = TimeoutError if outcome == "lock-timeout" else RuntimeError
        with pytest.raises(expected), checkpoint_bridge.open_run_checkpointer(repository):
            pytest.fail("Unavailable checkpoints must prevent graph execution")
    assert bool(waits) == (outcome != "preinitialized")
    assert all(delay > 0 for delay in waits)
    assert bool(setups) == (outcome not in {"lock-timeout", "preinitialized"})
    assert closed == [True]
    assert not connection.locked and not connection.autocommit


def test_preprovisioned_sqlite_saver_persists_without_schema_statements(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.workflow.checkpoint_bridge import open_run_checkpointer

    path = tmp_path / "native.sqlite"
    with LanggraphCheckpointBridge.from_sqlite_path(path):
        pass
    connect = sqlite3.connect
    with closing(connect(path)) as db:
        # Two tables and their primary-key indexes; an extra row must fail too.
        before = db.execute("SELECT * FROM sqlite_master ORDER BY type,name").fetchmany(5)
        assert len(before) == 4
    statements = []

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    engine = create_engine(f"sqlite:///{path}")
    repository = SQLAlchemyAgentRunRepository(
        session_factory=sessionmaker(bind=engine), auto_create=False
    )
    try:
        assert repository.allows_schema_setup is False
        with open_run_checkpointer(repository) as saver:
            bridge = LanggraphCheckpointBridge(saver, setup=False)
            checkpoint_id = bridge.save("plan", 1, {"receipt": "saved"}, ["node"])
            assert bridge.get("plan", checkpoint_id)["runtime_context"] == {"receipt": "saved"}
        assert not any(
            statement.lstrip().split(None, 1)[0].upper() in {"CREATE", "ALTER", "DROP"}
            for statement in statements
        )
        with closing(connect(path)) as db:
            assert (
                db.execute("SELECT * FROM sqlite_master ORDER BY type,name").fetchmany(5) == before
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("existing_file", [False, True])
def test_preprovisioned_sqlite_saver_does_not_create_or_repair_storage(tmp_path, existing_file):
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.workflow.checkpoint_bridge import open_run_checkpointer

    path = tmp_path / "missing.sqlite"
    if existing_file:
        path.touch()
    engine = create_engine(f"sqlite:///{path}")
    repository = SQLAlchemyAgentRunRepository(
        session_factory=sessionmaker(bind=engine), auto_create=False
    )
    try:
        with pytest.raises((ValueError, sqlite3.OperationalError)):
            with open_run_checkpointer(repository):
                pytest.fail("Unprovisioned storage must not admit graph execution")
        assert path.exists() is existing_file
        if existing_file:
            assert path.read_bytes() == b""
    finally:
        engine.dispose()


@pytest.mark.parametrize("fault", ["missing", "malformed", "extra-index", "temp-shadow"])
def test_native_sqlite_schema_validation_rejects_drift_without_repair(fault):
    import sqlite3
    from contextlib import closing

    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.infrastructure.workflow.checkpoint_bridge import validate_sqlite_checkpoint_schema

    with closing(sqlite3.connect(":memory:")) as db:
        SqliteSaver(db).setup()
        if fault in {"missing", "malformed"}:
            db.execute("DROP TABLE writes")
            if fault == "malformed":
                db.execute("CREATE TABLE writes (wrong_contract TEXT)")
        elif fault == "extra-index":
            db.execute("CREATE UNIQUE INDEX extra_authority ON checkpoints(thread_id)")
        else:
            db.execute("CREATE TEMP VIEW checkpoints AS SELECT 1")
        snapshot_sql = (
            "SELECT type,name,sql FROM main.sqlite_master "
            "UNION ALL SELECT type,name,sql FROM temp.sqlite_master"
        )
        # At most the original four entries plus one injected drift object.
        before = db.execute(snapshot_sql).fetchmany(6)
        assert len(before) < 6
        with pytest.raises(ValueError, match="offline provisioning"):
            validate_sqlite_checkpoint_schema(db)
        assert db.execute(snapshot_sql).fetchmany(6) == before


@pytest.mark.parametrize("prior_storage", ["absent", "existing", "malformed"])
def test_offline_native_revision_preserves_receipts_or_refuses_drift(
    tmp_path, monkeypatch, prior_storage
):
    import sqlite3
    from contextlib import closing

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from langgraph.checkpoint.sqlite import SqliteSaver

    from alembic import command
    from app.infrastructure.workflow.checkpoint_bridge import validate_sqlite_checkpoint_schema

    path = tmp_path / "migrated.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    previous = "2026_11_19_chat_revision"
    command.upgrade(config, previous)

    def save_receipt():
        with closing(sqlite3.connect(path)) as db:
            saver = SqliteSaver(db)
            bridge = LanggraphCheckpointBridge(saver)
            checkpoint_id = bridge.save("plan", 1, {"receipt": "saved"}, ["node"])
            saver.put_writes(
                {
                    "configurable": {
                        "thread_id": "lg:default:default:plan",
                        "checkpoint_ns": "default/default",
                        "checkpoint_id": checkpoint_id,
                    }
                },
                [("receipt", {"pending": "retained"})],
                task_id="task",
            )

    if prior_storage == "malformed":
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE writes (wrong_contract TEXT)")
            db.commit()
        before = path.read_bytes()
        with pytest.raises(ValueError, match="offline provisioning"):
            command.upgrade(config, "head")
        assert path.read_bytes() == before
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (previous,)
        return

    if prior_storage == "existing":
        save_receipt()

    def receipts():
        with closing(sqlite3.connect(path)) as db:
            validate_sqlite_checkpoint_schema(db)
            rows = {
                table: db.execute("SELECT * FROM " + table).fetchmany(2)
                for table in ("checkpoints", "writes")
            }
            assert all(len(items) == 1 for items in rows.values())
            return rows

    before = receipts() if prior_storage == "existing" else None
    command.upgrade(config, "head")
    if prior_storage == "absent":
        with closing(sqlite3.connect(path)) as db:
            validate_sqlite_checkpoint_schema(db)
        save_receipt()
        before = receipts()
    assert receipts() == before
    with pytest.raises(RuntimeError, match="Cannot partially downgrade merged delivery histories"):
        command.downgrade(config, previous)
    assert receipts() == before
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (ScriptDirectory.from_config(config).get_current_head(),)
        ]
    common_ancestor = "2026_11_11_agent_permissions"
    command.downgrade(config, common_ancestor)
    assert receipts() == before
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (common_ancestor,)
        ]
    command.upgrade(config, "head")
    assert receipts() == before
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            ScriptDirectory.from_config(config).get_current_head(),
        )


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
