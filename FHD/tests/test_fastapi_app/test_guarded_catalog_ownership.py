"""App ownership contracts; real database/HTTP startup is tested separately."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_app import guarded_catalog as g


@pytest.fixture
def admission(monkeypatch, tmp_path):
    from app.application.agent_orchestrator import run_repository as runs
    from app.application.agent_orchestrator import task_dispatcher as workers
    from app.application.agent_orchestrator import task_execution_repository as queue
    from app.desktop_runtime import database_generation_registry as registry

    monkeypatch.setattr(g, "_owner", None)
    monkeypatch.setattr(registry, "_owned_profile", None)
    monkeypatch.setattr(runs, "_agent_run_repository", None)
    monkeypatch.setattr(runs, "_agent_run_repository_status", {})
    monkeypatch.setattr(queue, "_task_execution_repository", None)
    monkeypatch.setattr(workers, "_dispatcher", None)
    monkeypatch.setenv("XCAGI_AGENT_RUN_REQUIRE_DURABLE", "1")
    monkeypatch.setenv("XCAGI_OWNED_SOURCE_PROFILE", "guarded-host-v1")
    monkeypatch.setenv("SECRET_KEY", "synthetic-startup-secret")
    profile = (tmp_path, (str(tmp_path / "host.sqlite"), 1, 2))
    monkeypatch.setattr(registry, "validate_existing_owned_profile", lambda config: profile)
    monkeypatch.setattr(registry, "require_owned_source_profile", lambda: None)
    config = SimpleNamespace(
        OWNED_SOURCE_PROFILE="guarded-host-v1", SECRET_KEY="synthetic-startup-secret"
    )
    yield SimpleNamespace(config=config, registry=registry, runs=runs, queue=queue, workers=workers)
    if g._owner is not None:
        g._owner.dispatcher = None
        g.release(g._owner)


def test_default_admission_has_no_profile_or_repository_effect(admission, monkeypatch):
    monkeypatch.setenv("XCAGI_OWNED_SOURCE_PROFILE", "")
    assert g.admit(SimpleNamespace(OWNED_SOURCE_PROFILE="")) is None
    assert admission.registry._owned_profile is None
    assert admission.runs._agent_run_repository is None
    assert admission.queue._task_execution_repository is None


def test_stale_disabled_config_never_falls_back_to_ordinary_bootstrap(admission):
    with pytest.raises(RuntimeError, match="configuration differs"):
        g.admit(SimpleNamespace(OWNED_SOURCE_PROFILE=""))
    assert g._owner is None and admission.registry._owned_profile is None


def test_owner_blocks_second_default_and_guarded_app(admission):
    owner = g.admit(admission.config)
    assert all(repo._auto_create is False for repo in owner.repositories)
    for config in (admission.config, SimpleNamespace(OWNED_SOURCE_PROFILE="")):
        with pytest.raises(RuntimeError, match="another application"):
            g.admit(config)
        assert g._owner is owner
        assert admission.registry._owned_profile == owner.profile
    unrelated = g.CatalogAdmission(owner.profile, owner.config, owner.environment)
    g.release(unrelated)
    assert g._owner is owner


def test_release_only_owned_repository_instances(admission):
    owner = g.admit(admission.config)
    foreign = object()
    admission.runs._agent_run_repository = foreign
    g.release(owner)
    assert admission.runs._agent_run_repository is foreign
    assert admission.queue._task_execution_repository is None
    assert admission.registry._owned_profile is None


def test_readiness_rejects_environment_change_and_pre_lifespan(admission, monkeypatch):
    owner = g.admit(admission.config)
    with pytest.raises(RuntimeError, match="readiness"):
        g.require_admission(owner)
    owner.ready = True
    g.require_admission(owner)
    monkeypatch.setenv("WORKSPACE_ROOT", "/different-synthetic-root")
    with pytest.raises(RuntimeError, match="readiness"):
        g.require_admission(owner)


@pytest.mark.parametrize("running,active", [(True, 0), (False, 1)])
def test_teardown_retains_authority_until_workers_drained(admission, running, active):
    owner = g.admit(admission.config)
    owner.ready = True
    owner.dispatcher = SimpleNamespace(
        snapshot=lambda: {"running": running, "active_count": active}
    )
    with pytest.raises(RuntimeError, match="not drained"):
        g.release(owner)
    assert g._owner is owner and not owner.ready
    assert admission.registry._owned_profile == owner.profile
    owner.dispatcher = None


def test_factory_admission_fails_before_cache_mod_or_database_side_effects(admission, monkeypatch):
    from app.fastapi_app import factory

    monkeypatch.setattr(factory, "_app_singleton", None)
    calls = []
    monkeypatch.setattr("app.infrastructure.cache.wiring.wire_cache_port", lambda: calls.append(1))

    def unavailable(config):
        raise ValueError("synthetic existing readiness refused")

    monkeypatch.setattr(admission.registry, "validate_existing_owned_profile", unavailable)
    with pytest.raises(ValueError, match="readiness refused"):
        factory.create_fastapi_app(admission.config)
    assert calls == []
    assert g._owner is None and admission.registry._owned_profile is None
    assert admission.runs._agent_run_repository is None


def test_unconfigured_app_does_not_borrow_global_readiness(admission):
    app = FastAPI()
    app.add_middleware(g.CatalogAdmissionMiddleware, admission=None)

    @app.get("/api/etl/owned-mixed-v1/products")
    def ordinary():
        return {"ordinary": True}

    with TestClient(app) as client:
        assert client.get("/api/etl/owned-mixed-v1/products").json() == {"ordinary": True}
        owner = g.admit(admission.config)
        owner.ready = True
        response = client.get("/api/etl/owned-mixed-v1/products")
        assert response.status_code == 503 and response.json()["retryable"] is False


def test_existing_db_opener_does_not_create_missing_file(admission, tmp_path):
    from app.db import _create_engine_for_url

    path = tmp_path / "missing.sqlite"
    engine = _create_engine_for_url(f"sqlite:///{path}")
    try:
        with pytest.raises(Exception, match="unable to open database"):
            with engine.connect():
                pass
    finally:
        engine.dispose()
    assert not path.exists()


@pytest.mark.parametrize("state", ["not_ready", "environment_changed", "released"])
def test_auth_admission_runs_before_session_readers(admission, monkeypatch, state):
    owner = g.admit(admission.config)
    owner.ready = state != "not_ready"
    if state == "environment_changed":
        monkeypatch.setenv("WORKSPACE_ROOT", "/different-synthetic-root")
    elif state == "released":
        g.release(owner)
    calls = []
    app = FastAPI()

    class SessionReader:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                calls.append(scope["path"])
            await self.app(scope, receive, send)

    app.add_middleware(SessionReader)
    app.add_middleware(g.CatalogAdmissionMiddleware, admission=owner)
    with TestClient(app) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 503
    assert calls == []


def test_cached_creating_engine_and_session_are_not_reused(admission, monkeypatch, tmp_path):
    import app.db as db

    path = tmp_path / "preexisting.sqlite"
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE")
    ordinary = db._get_engine_for_url(url)
    ordinary_sessions = db._get_host_session_local()
    with ordinary.connect():
        pass
    assert path.exists()
    assert db._get_engine_for_url(url) is ordinary
    monkeypatch.setenv("XCAGI_OWNED_SOURCE_PROFILE", "guarded-host-v1")
    guarded = db._get_engine_for_url(url)
    guarded_sessions = db._get_host_session_local()
    assert guarded is not ordinary
    assert guarded_sessions is not ordinary_sessions
    path.unlink()
    try:
        with pytest.raises(Exception, match="unable to open database"):
            with guarded_sessions() as session:
                session.connection()
        assert not path.exists()
    finally:
        ordinary.dispose()
        guarded.dispose()


@pytest.mark.parametrize("mod_id", ["industry.food", "employee.synthetic", "client.synthetic"])
def test_guarded_request_never_seeds_missing_mod(admission, mod_id):
    from app.infrastructure.mods.management.activation import ModActivation

    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("missing guarded artifact must not be seeded/loaded/mounted")

    manager = SimpleNamespace(resolve_mod_directory=lambda mid: None, load_mod=forbidden)
    ports = SimpleNamespace(
        disabled=lambda: False,
        restore=lambda sid: None,
        allowed=lambda mid, sid: True,
        manager=lambda: manager,
        employee_ready=forbidden,
        register_employee=forbidden,
        register_mod=forbidden,
        mark_missing=calls.append,
    )
    assert ModActivation(ports).ensure(mod_id, "synthetic-session") is False
    assert calls == [mod_id]


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt, type(None)])
def test_factory_releases_admission_only_when_construction_fails(monkeypatch, error_type):
    from app.fastapi_app import factory

    owner, app, config = object(), object(), object()
    released = []
    monkeypatch.setattr(g, "admit", lambda *args: owner)
    monkeypatch.setattr(g, "release", released.append)

    def construct(*args):
        assert args[-1] is owner
        if error_type is not type(None):
            raise error_type("construction interrupted")
        return app

    monkeypatch.setattr(factory, "_create_fastapi_app", construct)
    if error_type is type(None):
        assert factory.create_fastapi_app(config) is app
        assert released == []
    else:
        with pytest.raises(error_type, match="construction interrupted"):
            factory.create_fastapi_app(config)
        assert released == [owner]
