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
                "workflow_ai_employees": {"a": True, "b": True}
            }

        # A corrupt persisted value must not be silently replaced.
        service.set_preference(owner, "workspace_prefs", "not-json")
        import pytest

        with pytest.raises(ValueError):
            patch_workspace_prefs(owner, {"host_pack_acknowledged": True})
        assert service.get_preference(owner, "workspace_prefs") == "not-json"
    finally:
        engine.dispose()
