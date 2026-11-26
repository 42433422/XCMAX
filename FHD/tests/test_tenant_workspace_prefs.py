from __future__ import annotations

import json

from app.application.tenant_workspace_prefs import (
    bind_selected_industry_for_user,
    get_workspace_prefs,
    patch_workspace_prefs,
)


def test_patch_workspace_prefs_merges_workflow_employees(monkeypatch):
    store: dict[str, dict[str, str]] = {}

    class FakePrefService:
        def get_preference(self, user_id: str, preference_key: str) -> str | None:
            return store.get(user_id, {}).get(preference_key)

        def set_preference(self, user_id: str, preference_key: str, preference_value: str) -> bool:
            store.setdefault(user_id, {})[preference_key] = preference_value
            return True

        def mutate_preference(self, user_id, preference_key, transform):
            value = transform(self.get_preference(user_id, preference_key))
            self.set_preference(user_id, preference_key, value)
            return value

    monkeypatch.setattr(
        "app.domain.shared_services.user_preference_service.get_user_preference_service",
        lambda: FakePrefService(),
    )

    owner = "tenant:42"
    patch_workspace_prefs(
        owner, {"selected_industry_id": "涂料", "industry_mod_id": "coating-industry"}
    )
    patch_workspace_prefs(owner, {"workflow_ai_employees": {"emp-a": True}})
    patch_workspace_prefs(owner, {"workflow_ai_employees": {"emp-b": False}})

    prefs = get_workspace_prefs(owner)
    assert prefs["selected_industry_id"] == "涂料"
    assert prefs["workflow_ai_employees"] == {"emp-a": True, "emp-b": False}

    raw = store[owner]["workspace_prefs"]
    assert json.loads(raw)["industry_mod_id"] == "coating-industry"


def test_bind_selected_industry_updates_user_and_tenant_prefs(monkeypatch):
    store: dict[str, dict[str, str]] = {}

    class FakePrefService:
        def get_preference(self, user_id: str, preference_key: str) -> str | None:
            return store.get(user_id, {}).get(preference_key)

        def set_preference(self, user_id: str, preference_key: str, preference_value: str) -> bool:
            store.setdefault(user_id, {})[preference_key] = preference_value
            return True

        def mutate_preference(self, user_id, preference_key, transform):
            value = transform(self.get_preference(user_id, preference_key))
            self.set_preference(user_id, preference_key, value)
            return value

    class FakeDbUser:
        id = 7
        tenant_id = 42
        tier = "enterprise"
        industry_id = "通用"
        entitled_industries = []

    db_user = FakeDbUser()

    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return db_user

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def commit(self):
            return None

    class FakeDbContext:
        def __enter__(self):
            return FakeDb()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        "app.domain.shared_services.user_preference_service.get_user_preference_service",
        lambda: FakePrefService(),
    )
    monkeypatch.setattr("app.db.session.get_db", lambda: FakeDbContext())
    monkeypatch.setattr(
        "app.mod_sdk.industry_seed.industry_mod_id_for",
        lambda industry_id: "coating-industry" if industry_id == "涂料" else None,
    )

    prefs = bind_selected_industry_for_user(db_user, "涂料")

    assert db_user.industry_id == "涂料"
    assert "涂料" in db_user.entitled_industries
    assert prefs["selected_industry_id"] == "涂料"
    assert prefs["industry_mod_id"] == "coating-industry"
    assert json.loads(store["tenant:42"]["workspace_prefs"])["selected_industry_id"] == "涂料"


def test_workspace_prefs_atomic_sqlite_writers(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Barrier

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import UserPreference
    from app.domain.shared_services import user_preference_service as service_module

    engine = create_engine(
        f"sqlite:///{tmp_path / 'prefs.db'}",
        connect_args={"timeout": 10, "check_same_thread": False},
    )
    UserPreference.__table__.create(engine)
    sessions = sessionmaker(bind=engine)

    @contextmanager
    def db_scope():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(service_module, "get_db", db_scope)
    service = service_module.UserPreferenceService()
    monkeypatch.setattr(service_module, "get_user_preference_service", lambda: service)
    barrier = Barrier(2)
    owner = "tenant:42"

    def writer(employee):
        barrier.wait(timeout=5)
        return patch_workspace_prefs(owner, {"workflow_ai_employees": {employee: True}})

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(writer, "a")
            second = executor.submit(writer, "b")
            first.result(timeout=20)
            second.result(timeout=20)
        with sessions() as session:
            rows = session.scalars(select(UserPreference)).all()
            assert len(rows) == 1
            assert json.loads(rows[0].preference_value) == {
                "workflow_ai_employees": {"a": True, "b": True},
                "_revision": 2,
            }

        # A corrupt persisted value must not be silently replaced.
        service.set_preference(owner, "workspace_prefs", "not-json")
        import pytest

        with pytest.raises(ValueError):
            patch_workspace_prefs(owner, {"host_pack_acknowledged": True})
        assert service.get_preference(owner, "workspace_prefs") == "not-json"
    finally:
        engine.dispose()


def test_workspace_revision_rejects_stale_cross_device_write(monkeypatch):
    import pytest

    from app.application.tenant_workspace_prefs import (
        WorkspacePrefsVersionConflict,
        workspace_prefs_revision,
    )

    store = {}

    class Prefs:
        def get_preference(self, owner, key):
            return store.get((owner, key))

        def mutate_preference(self, owner, key, transform):
            value = transform(store.get((owner, key)))
            store[(owner, key)] = value
            return value

    monkeypatch.setattr(
        "app.domain.shared_services.user_preference_service.get_user_preference_service",
        lambda: Prefs(),
    )
    owner = "tenant:42"
    assert workspace_prefs_revision({}) == 0
    first = patch_workspace_prefs(owner, {"host_pack_acknowledged": True}, expected_revision=0)
    assert first["_revision"] == 1
    second = patch_workspace_prefs(owner, {"onboarding_seed_done": True}, expected_revision=1)
    assert second["_revision"] == 2
    with pytest.raises(WorkspacePrefsVersionConflict, match="expected=1 actual=2"):
        patch_workspace_prefs(owner, {"host_pack_acknowledged": False}, expected_revision=1)
    assert get_workspace_prefs(owner) == second
    with pytest.raises(ValueError, match="Invalid expected"):
        patch_workspace_prefs(owner, {}, expected_revision=True)
    with pytest.raises(ValueError, match="Invalid persisted"):
        store[(owner, "workspace_prefs")] = '{"_revision": "bad"}'
        patch_workspace_prefs(owner, {"host_pack_acknowledged": False})


def _process_workspace_writer(db_url, employee, barrier, results, expected_revision=None):
    """Independent interpreter with its own SQLAlchemy engine and connection."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.tenant_workspace_prefs import (
        WorkspacePrefsVersionConflict,
        patch_workspace_prefs,
    )
    from app.domain.shared_services import user_preference_service as services

    kwargs = {"connect_args": {"timeout": 20}} if db_url.startswith("sqlite:") else {}
    engine = create_engine(db_url, **kwargs)
    sessions = sessionmaker(bind=engine)

    @contextmanager
    def db_scope():
        with sessions.begin() as db:
            yield db

    services.get_db = db_scope
    instance = services.UserPreferenceService()
    services.get_user_preference_service = lambda: instance
    try:
        barrier.wait(timeout=15)
        saved = patch_workspace_prefs(
            "tenant:42",
            {"workflow_ai_employees": {employee: True}},
            expected_revision=expected_revision,
        )
        results.put((employee, saved["_revision"], None))
    except WorkspacePrefsVersionConflict as exc:
        results.put((employee, None, repr(exc)))
        raise
    finally:
        engine.dispose()


def test_workspace_prefs_independent_process_writers_and_readback(tmp_path):
    from multiprocessing import get_context

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import UserPreference

    db_url = f"sqlite:///{tmp_path / 'prefs-multiprocess.db'}"
    engine = create_engine(db_url)
    UserPreference.__table__.create(engine)
    engine.dispose()

    ctx = get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_workspace_writer,
            args=(db_url, employee, barrier, results),
        )
        for employee in ("desktop", "mobile")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert [process.exitcode for process in processes] == [0, 0]
    observations = [results.get(timeout=5) for _ in processes]
    assert all(error is None for _, _, error in observations)
    assert {rev for _, rev, _ in observations} == {1, 2}

    reader_engine = create_engine(db_url)
    sessions = sessionmaker(bind=reader_engine)
    try:
        with sessions() as first_device, sessions() as second_device:
            first = first_device.scalars(select(UserPreference)).all()
            second = second_device.scalars(select(UserPreference)).all()
            assert len(first) == len(second) == 1
            current = json.loads(first[0].preference_value)
            assert current == json.loads(second[0].preference_value)
            assert current["_revision"] == 2
            assert current["workflow_ai_employees"] == {
                "desktop": True,
                "mobile": True,
            }
    finally:
        reader_engine.dispose()


def _run_preference_uniqueness_migration(connection):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/2026_11_25_workspace_prefs_unique.py"
    )
    spec = importlib.util.spec_from_file_location("workspace_prefs_unique_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def test_legacy_preference_duplicates_migrate_without_discarding_conflicts(tmp_path):
    import pytest
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-prefs.db'}")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE user_preferences "
                "(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
                "preference_key TEXT NOT NULL, preference_value TEXT)"
            )
        )
        db.execute(
            text(
                "INSERT INTO user_preferences "
                "(id, user_id, preference_key, preference_value) VALUES "
                "(1, 'tenant:42', 'workspace_prefs', :value), "
                "(2, 'tenant:42', 'workspace_prefs', :value), "
                "(3, 'tenant:42', 'other', 'safe')"
            ),
            {"value": '{"ok":true}'},
        )
        _run_preference_uniqueness_migration(db)
        rows = db.execute(
            text("SELECT id, preference_value FROM user_preferences ORDER BY id")
        ).all()
        assert rows == [(1, '{"ok":true}'), (3, "safe")]
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(
                    text(
                        "INSERT INTO user_preferences "
                        "(user_id, preference_key, preference_value) "
                        "VALUES ('tenant:42', 'workspace_prefs', 'overwritten')"
                    )
                )
    engine.dispose()

    engine = create_engine(f"sqlite:///{tmp_path / 'conflicting-prefs.db'}")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE user_preferences "
                "(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
                "preference_key TEXT NOT NULL, preference_value TEXT)"
            )
        )
        db.execute(
            text(
                "INSERT INTO user_preferences "
                "(id, user_id, preference_key, preference_value) VALUES "
                "(1, 'tenant:42', 'workspace_prefs', 'A'), "
                "(2, 'tenant:42', 'workspace_prefs', 'B')"
            )
        )
        with pytest.raises(RuntimeError, match="requires_reconciliation"):
            _run_preference_uniqueness_migration(db)
        assert db.execute(text("SELECT COUNT(*) FROM user_preferences")).scalar() == 2
    engine.dispose()


def _race_expected_revision(db_url):
    from multiprocessing import get_context

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import UserPreference

    ctx = get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    workers = [
        ctx.Process(
            target=_process_workspace_writer,
            args=(db_url, employee, barrier, queue, 0),
        )
        for employee in ("desktop", "mobile")
    ]
    for process in workers:
        process.start()
    for process in workers:
        process.join(timeout=30)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    outcomes = [queue.get(timeout=5) for _ in workers]
    completed = [outcome for outcome in outcomes if outcome[2] is None]
    conflicts = [
        outcome
        for outcome in outcomes
        if outcome[2] is not None and "workspace_prefs_version_conflict" in outcome[2]
    ]
    assert len(completed) == 1
    assert completed[0][1] == 1
    assert len(conflicts) == 1
    assert sorted(p.exitcode for p in workers) == [0, 1]

    engine = create_engine(db_url)
    try:
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            rows = session.scalars(select(UserPreference)).all()
            assert len(rows) == 1
            value = json.loads(rows[0].preference_value)
            assert value["_revision"] == 1
            assert len(value["workflow_ai_employees"]) == 1
    finally:
        engine.dispose()


def test_workspace_revision_competing_processes_accept_exactly_one(tmp_path):
    from sqlalchemy import create_engine

    from app.db.models import UserPreference

    url = f"sqlite:///{tmp_path / 'competing-revision.sqlite'}"
    engine = create_engine(url)
    try:
        UserPreference.__table__.create(engine)
    finally:
        engine.dispose()
    _race_expected_revision(url)


def test_workspace_revision_competing_postgresql_processes():
    """Executes only with the explicit disposable PostgreSQL CI service."""
    import os

    import pytest
    from sqlalchemy import create_engine, engine

    from app.db.models import UserPreference

    url = os.environ.get("XCMAX_PREF_TEST_PG_URL")
    if not url:
        pytest.skip("real PostgreSQL preference test database not configured")
    parsed = engine.make_url(url)
    if (
        os.environ.get("XCMAX_PREF_GUARD_ONLY") != "1"
        or parsed.get_backend_name() != "postgresql"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or parsed.database != "xcagi_prefs_guard"
    ):
        raise RuntimeError("refusing_non_disposable_preference_test_database")
    database = create_engine(url)
    try:
        UserPreference.__table__.create(database)
        _race_expected_revision(url)
    finally:
        UserPreference.__table__.drop(database, checkfirst=True)
        database.dispose()


def test_workspace_preferences_use_host_db_even_with_an_active_mod(monkeypatch):
    import pytest

    from app.application.tenant_workspace_prefs import WorkspacePrefsVersionConflict
    from app.request_active_mod_ctx import (
        get_request_active_mod_id,
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    store = {}

    class FakeService:
        def get_preference(self, owner, key):
            assert get_request_active_mod_id() == ""
            return store.get((owner, key))

        def mutate_preference(self, owner, key, transform):
            assert get_request_active_mod_id() == ""
            value = transform(store.get((owner, key)))
            store[(owner, key)] = value
            return value

    monkeypatch.setattr(
        "app.domain.shared_services.user_preference_service.get_user_preference_service",
        lambda: FakeService(),
    )
    token = set_request_active_mod_id("customer-mod-a")
    try:
        first = patch_workspace_prefs(
            "tenant:42", {"host_pack_acknowledged": True}, expected_revision=0
        )
        assert first["_revision"] == 1
        assert get_request_active_mod_id() == "customer-mod-a"
        assert get_workspace_prefs("tenant:42") == first
        assert get_request_active_mod_id() == "customer-mod-a"
        with pytest.raises(WorkspacePrefsVersionConflict):
            patch_workspace_prefs(
                "tenant:42", {"host_pack_acknowledged": False}, expected_revision=0
            )
        # Exception paths must also restore the original business Mod.
        assert get_request_active_mod_id() == "customer-mod-a"
    finally:
        reset_request_active_mod_id(token)
