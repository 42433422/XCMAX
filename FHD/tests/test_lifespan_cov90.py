"""Real-behavior tests for app/fastapi_app/lifespan.py.

These tests mock every external dependency (DB init, NeuroBus, employee
runtime, mobile relay, mod bootstrap) and assert on side effects:
``app.state`` mutations, which helpers got called, and which except branches
ran when a dependency raises a ``RECOVERABLE_ERRORS`` member.

The lifespan module's internal helpers are reached via ``importlib`` because
``app.fastapi_app.__init__`` re-exports the ``lifespan`` *function* and thus
shadows the submodule attribute for plain ``import ... as`` access.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from types import SimpleNamespace

import pytest

# Reach the real module object (not the re-exported ``lifespan`` function).
L = importlib.import_module("app.fastapi_app.lifespan")


def _fake_app(database_url=None):
    """Minimal FastAPI-like stub with ``.state`` and ``.state.config``."""
    state = SimpleNamespace()
    state.config = SimpleNamespace(DATABASE_URL=database_url)
    return SimpleNamespace(state=state)


# ---------------------------------------------------------------------------
# _initialize_databases_async
# ---------------------------------------------------------------------------
async def test_initialize_databases_async_logs_safe_url(monkeypatch, caplog):
    """Valid DATABASE_URL -> password is masked and executor is invoked."""
    captured = {}

    async def fake_run_in_executor(executor, fn, app):
        captured["fn"] = fn
        captured["app"] = app
        return None

    loop = SimpleNamespace(run_in_executor=fake_run_in_executor)
    monkeypatch.setattr(L.asyncio, "get_running_loop", lambda: loop)

    app = _fake_app("postgresql://user:secretpw@host/db")
    with caplog.at_level(logging.INFO):
        await L._initialize_databases_async(app)

    # executor was scheduled with the sync initializer + app
    assert captured["fn"] is L._initialize_databases_sync
    assert captured["app"] is app
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "secretpw" not in joined  # password masked by make_url render
    assert "***" in joined


async def test_initialize_databases_async_make_url_failure(monkeypatch, caplog):
    """make_url raising ValueError -> falls back to raw db_url (line 123-124)."""
    monkeypatch.setattr(L, "make_url", lambda _u: (_ for _ in ()).throw(ValueError("bad url")))

    async def fake_run_in_executor(executor, fn, app):
        return None

    loop = SimpleNamespace(run_in_executor=fake_run_in_executor)
    monkeypatch.setattr(L.asyncio, "get_running_loop", lambda: loop)

    raw = "weird-but-set-url"
    app = _fake_app(raw)
    with caplog.at_level(logging.INFO):
        await L._initialize_databases_async(app)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert raw in joined  # safe fell back to raw db_url


async def test_initialize_databases_async_no_url(monkeypatch, caplog):
    """Empty DATABASE_URL -> default-strategy log branch (line 127)."""

    async def fake_run_in_executor(executor, fn, app):
        return None

    loop = SimpleNamespace(run_in_executor=fake_run_in_executor)
    monkeypatch.setattr(L.asyncio, "get_running_loop", lambda: loop)

    app = _fake_app("")
    with caplog.at_level(logging.INFO):
        await L._initialize_databases_async(app)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "未设置" in joined


# ---------------------------------------------------------------------------
# _run_ensure_ai_action_audit_table
# ---------------------------------------------------------------------------
def test_run_ensure_ai_action_audit_table_loader_none(monkeypatch):
    """spec.loader is None -> RuntimeError (line 138-139)."""
    fake_spec = SimpleNamespace(loader=None)
    monkeypatch.setattr(L.importlib.util, "spec_from_file_location", lambda *a, **k: fake_spec)
    monkeypatch.setattr(L.importlib.util, "module_from_spec", lambda spec: SimpleNamespace())

    with pytest.raises(RuntimeError, match="无法加载 ai_action_audit_service"):
        L._run_ensure_ai_action_audit_table()


def test_run_ensure_ai_action_audit_table_success(monkeypatch):
    """Loader present -> module exec + ensure_ai_action_audit_table called (140-141)."""
    calls = {"exec": 0, "ensure": 0}

    def fake_ensure():
        calls["ensure"] += 1

    fake_mod = SimpleNamespace(ensure_ai_action_audit_table=fake_ensure)

    def fake_exec_module(mod):
        calls["exec"] += 1

    fake_loader = SimpleNamespace(exec_module=fake_exec_module)
    fake_spec = SimpleNamespace(loader=fake_loader)
    monkeypatch.setattr(L.importlib.util, "spec_from_file_location", lambda *a, **k: fake_spec)
    monkeypatch.setattr(L.importlib.util, "module_from_spec", lambda spec: fake_mod)

    L._run_ensure_ai_action_audit_table()
    assert calls["exec"] == 1
    assert calls["ensure"] == 1


# ---------------------------------------------------------------------------
# _initialize_databases_sync
# ---------------------------------------------------------------------------
def _patch_common_sync(monkeypatch):
    """Stub all top-level table helpers used by the sync initializer to no-ops."""
    noop = lambda *a, **k: None
    for name in (
        "init_distillation_tables",
        "init_extract_logs_tables",
        "ensure_product_query_indexes",
        "ensure_sessions_market_access_token_column",
        "ensure_sessions_market_refresh_token_column",
        "ensure_sessions_enterprise_entitlement_columns",
        "ensure_sessions_account_meta_columns",
        "ensure_user_profile_columns",
        "init_approval_tables",
        "init_service_bridge_tables",
        "init_wechat_tasks_table",
        "init_template_tables",
    ):
        monkeypatch.setattr(L, name, noop)

    import app.db.init_db as initdb

    for name in (
        "ensure_runtime_auth_bootstrap",
        "ensure_users_tenant_id_column",
        "ensure_business_tenant_id_columns",
        "init_persona_tables",
        "ensure_sqlite_per_mod_database_copies",
    ):
        monkeypatch.setattr(initdb, name, noop)

    # The audit-table loader does real file IO; stub it out.
    monkeypatch.setattr(L, "_run_ensure_ai_action_audit_table", noop)


def test_initialize_databases_sync_sqlite_with_file(monkeypatch):
    """SQLite URL with a concrete file -> file-arg table init + per-mod copies."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: True)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "sqlite:////tmp/x.db")
    monkeypatch.setattr(L, "sqlite_db_file_from_url", lambda u: "/tmp/x.db")

    init_calls = {}
    monkeypatch.setattr(L, "initialize_databases", lambda: init_calls.setdefault("init", True))
    wechat_args = {}
    monkeypatch.setattr(L, "init_wechat_tasks_table", lambda *a: wechat_args.setdefault("args", a))
    template_args = {}
    monkeypatch.setattr(L, "init_template_tables", lambda *a: template_args.setdefault("args", a))

    # mod manager returns one loaded mod id
    mod = SimpleNamespace(id="m1")
    mm = SimpleNamespace(list_loaded_mods=lambda: [mod], scan_mods=lambda: [mod])
    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", lambda: mm)

    copy_ids = {}
    import app.db.init_db as initdb

    monkeypatch.setattr(
        initdb,
        "ensure_sqlite_per_mod_database_copies",
        lambda ids: copy_ids.setdefault("ids", ids),
    )

    app = _fake_app("sqlite:////tmp/x.db")
    L._initialize_databases_sync(app)

    assert init_calls["init"] is True
    # file path passed through to the *_table helpers
    assert wechat_args["args"] == ("/tmp/x.db",)
    assert template_args["args"] == ("/tmp/x.db",)
    assert copy_ids["ids"] == ["m1"]


def test_initialize_databases_sync_sqlite_no_file_scans_mods(monkeypatch):
    """SQLite URL, no file path, no loaded mods -> scan_mods fallback + no-arg init."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: True)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "sqlite://")
    monkeypatch.setattr(L, "sqlite_db_file_from_url", lambda u: None)
    monkeypatch.setattr(L, "initialize_databases", lambda: None)

    wechat_args = {}
    monkeypatch.setattr(L, "init_wechat_tasks_table", lambda *a: wechat_args.setdefault("args", a))
    monkeypatch.setattr(L, "init_template_tables", lambda *a: None)

    scanned = SimpleNamespace(id="scanned-mod")
    mm = SimpleNamespace(list_loaded_mods=lambda: [], scan_mods=lambda: [scanned])
    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", lambda: mm)

    copy_ids = {}
    import app.db.init_db as initdb

    monkeypatch.setattr(
        initdb,
        "ensure_sqlite_per_mod_database_copies",
        lambda ids: copy_ids.setdefault("ids", ids),
    )

    app = _fake_app("sqlite://")
    L._initialize_databases_sync(app)

    # no file -> no-arg helper calls (line 166-167)
    assert wechat_args["args"] == ()
    # scan_mods fallback used (line 157)
    assert copy_ids["ids"] == ["scanned-mod"]


def test_initialize_databases_sync_sqlite_mod_copy_recoverable(monkeypatch):
    """Per-mod copy raising RuntimeError is swallowed (line 159-160)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: True)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "sqlite://")
    monkeypatch.setattr(L, "sqlite_db_file_from_url", lambda u: None)
    monkeypatch.setattr(L, "initialize_databases", lambda: None)
    monkeypatch.setattr(L, "init_wechat_tasks_table", lambda *a: None)
    monkeypatch.setattr(L, "init_template_tables", lambda *a: None)

    def boom_get_mm():
        raise RuntimeError("no mod manager")

    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", boom_get_mm)

    app = _fake_app("sqlite://")
    # Should NOT raise; the inner try/except absorbs it and continues.
    L._initialize_databases_sync(app)


def test_initialize_databases_sync_tenant_import_errors(monkeypatch, caplog):
    """tenant-id self-check ImportError branches are logged, not raised (185-186/191-192)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: False)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "postgresql://h/db")

    import app.db.init_db as initdb

    def boom_users(*a, **k):
        raise ImportError("no users tenant fn")

    def boom_biz(*a, **k):
        raise AttributeError("no biz tenant fn")

    monkeypatch.setattr(initdb, "ensure_users_tenant_id_column", boom_users)
    monkeypatch.setattr(initdb, "ensure_business_tenant_id_columns", boom_biz)

    # postgres per-mod path: stub mod manager + ensure
    mm = SimpleNamespace(list_loaded_mods=lambda: [], scan_mods=lambda: [])
    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", lambda: mm)
    import app.db.ensure_mod_postgres as empg

    monkeypatch.setattr(empg, "ensure_postgres_per_mod_databases", lambda **k: [])

    app = _fake_app("postgresql://h/db")
    with caplog.at_level(logging.WARNING):
        L._initialize_databases_sync(app)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "users.tenant_id" in joined
    assert "业务表 tenant_id" in joined


def test_initialize_databases_sync_optional_table_recoverable(monkeypatch, caplog):
    """approval/bridge/persona init RuntimeErrors are swallowed (195-196/199-200/206-207)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: True)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "sqlite://")
    monkeypatch.setattr(L, "sqlite_db_file_from_url", lambda u: None)
    monkeypatch.setattr(L, "initialize_databases", lambda: None)
    monkeypatch.setattr(L, "init_wechat_tasks_table", lambda *a: None)
    monkeypatch.setattr(L, "init_template_tables", lambda *a: None)

    mm = SimpleNamespace(list_loaded_mods=lambda: [], scan_mods=lambda: [])
    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", lambda: mm)
    import app.db.init_db as initdb

    monkeypatch.setattr(initdb, "ensure_sqlite_per_mod_database_copies", lambda ids: None)

    monkeypatch.setattr(
        L,
        "init_approval_tables",
        lambda e: (_ for _ in ()).throw(RuntimeError("approval boom")),
    )
    monkeypatch.setattr(
        L,
        "init_service_bridge_tables",
        lambda e: (_ for _ in ()).throw(RuntimeError("bridge boom")),
    )
    monkeypatch.setattr(
        initdb,
        "init_persona_tables",
        lambda e: (_ for _ in ()).throw(RuntimeError("persona boom")),
    )

    app = _fake_app("sqlite://")
    with caplog.at_level(logging.WARNING):
        L._initialize_databases_sync(app)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "approval" in joined
    assert "service_bridge" in joined
    assert "persona" in joined


def test_initialize_databases_sync_postgres_per_mod_created(monkeypatch, caplog):
    """Non-SQLite -> postgres per-mod databases created + logged (210-220)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: False)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "postgresql://h/db")

    mod = SimpleNamespace(id="pgmod")
    mm = SimpleNamespace(list_loaded_mods=lambda: [mod], scan_mods=lambda: [mod])
    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", lambda: mm)

    seen = {}
    import app.db.ensure_mod_postgres as empg

    def fake_ensure(mod_ids, migrate_new):
        seen["mod_ids"] = mod_ids
        seen["migrate_new"] = migrate_new
        return ["created-db-1"]

    monkeypatch.setattr(empg, "ensure_postgres_per_mod_databases", fake_ensure)

    app = _fake_app("postgresql://h/db")
    with caplog.at_level(logging.INFO):
        L._initialize_databases_sync(app)

    assert seen["mod_ids"] == ["pgmod"]
    assert seen["migrate_new"] is True
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "created-db-1" in joined


def test_initialize_databases_sync_audit_recoverable(monkeypatch, caplog):
    """AI audit table init RuntimeError is swallowed (226-227)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: True)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "sqlite://")
    monkeypatch.setattr(L, "sqlite_db_file_from_url", lambda u: None)
    monkeypatch.setattr(L, "initialize_databases", lambda: None)
    monkeypatch.setattr(L, "init_wechat_tasks_table", lambda *a: None)
    monkeypatch.setattr(L, "init_template_tables", lambda *a: None)

    mm = SimpleNamespace(list_loaded_mods=lambda: [], scan_mods=lambda: [])
    import app.infrastructure.mods.mod_manager as mmmod

    monkeypatch.setattr(mmmod, "get_mod_manager", lambda: mm)
    import app.db.init_db as initdb

    monkeypatch.setattr(initdb, "ensure_sqlite_per_mod_database_copies", lambda ids: None)

    monkeypatch.setattr(
        L,
        "_run_ensure_ai_action_audit_table",
        lambda: (_ for _ in ()).throw(RuntimeError("audit boom")),
    )

    app = _fake_app("sqlite://")
    with caplog.at_level(logging.WARNING):
        L._initialize_databases_sync(app)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "AI审计表" in joined


def test_initialize_databases_sync_outer_failure_sqlite(monkeypatch):
    """Outer failure on SQLite -> RuntimeError with SQLite-specific message (236-239)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: True)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "sqlite://")
    # initialize_databases blows up with a recoverable error -> outer except
    monkeypatch.setattr(
        L,
        "initialize_databases",
        lambda: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    app = _fake_app("sqlite://")
    with pytest.raises(RuntimeError, match="本地数据库初始化失败"):
        L._initialize_databases_sync(app)


def test_initialize_databases_sync_outer_failure_postgres(monkeypatch):
    """Outer failure on PostgreSQL -> RuntimeError with PG-specific message (240-242)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: False)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "postgresql://u:pw@h/db")
    # First top-level call after the sqlite block raises -> outer except.
    monkeypatch.setattr(
        L,
        "init_distillation_tables",
        lambda e: (_ for _ in ()).throw(RuntimeError("conn refused")),
    )

    app = _fake_app("postgresql://u:pw@h/db")
    with pytest.raises(RuntimeError, match="数据库初始化失败"):
        L._initialize_databases_sync(app)


def test_initialize_databases_sync_outer_failure_url_render(monkeypatch, caplog):
    """make_url raising in the outer-error path falls back silently (232-235)."""
    _patch_common_sync(monkeypatch)
    monkeypatch.setattr(L, "is_sqlite_url", lambda u: False)
    monkeypatch.setattr(L, "resolve_effective_database_url", lambda u: "postgresql://u:pw@h/db")
    monkeypatch.setattr(
        L,
        "init_distillation_tables",
        lambda e: (_ for _ in ()).throw(RuntimeError("conn refused")),
    )
    # make_url used inside the except handler raises ValueError -> pass branch.
    monkeypatch.setattr(L, "make_url", lambda _u: (_ for _ in ()).throw(ValueError("nope")))

    app = _fake_app("postgresql://u:pw@h/db")
    with pytest.raises(RuntimeError, match="数据库初始化失败"):
        L._initialize_databases_sync(app)


# ---------------------------------------------------------------------------
# _init_neuro_ddd_async
# ---------------------------------------------------------------------------
async def test_init_neuro_ddd_disabled(monkeypatch, caplog):
    """XCAGI_NEURO_INTENT=0 -> early return, no bus set (251-254)."""
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
    app = _fake_app()
    with caplog.at_level(logging.INFO):
        await L._init_neuro_ddd_async(app)
    assert not hasattr(app.state, "neuro_bus")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "神经总线未启用" in joined


async def test_init_neuro_ddd_success(monkeypatch):
    """Enabled path -> bus + manager + health monitor task + cognition stored."""
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")

    bus = SimpleNamespace(registered_domains=["intent"])

    async def fake_register():
        return bus

    import app.domain.neuro.register_cognition_handlers as cog
    import app.neuro_bus.bus_setup as bs
    import app.neuro_bus.health_monitor as hm
    import app.neuro_bus.register_runtime as rr

    monkeypatch.setattr(rr, "register_neuro_runtime", fake_register)
    monkeypatch.setattr(bs, "get_neuro_bus_manager", lambda: "MANAGER")

    async def fake_start_monitoring():
        return None

    monitor = SimpleNamespace(start_monitoring=fake_start_monitoring)
    monkeypatch.setattr(hm, "get_health_monitor", lambda: monitor)
    monkeypatch.setattr(
        cog,
        "register_cognition_handlers",
        lambda: {"enabled": True, "handler_count": 3},
    )

    app = _fake_app()
    await L._init_neuro_ddd_async(app)

    assert app.state.neuro_bus is bus
    assert app.state.neuro_bus_manager == "MANAGER"
    assert app.state.neuro_cognition == {"enabled": True, "handler_count": 3}
    task = app.state.neuro_health_monitor_task
    assert task is not None
    # Clean up the spawned task deterministically.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_init_neuro_ddd_health_monitor_and_cognition_failures(monkeypatch, caplog):
    """Health-monitor + cognition failures are swallowed (269-270 / 283-285)."""
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")

    bus = SimpleNamespace(registered_domains=[])

    async def fake_register():
        return bus

    import app.domain.neuro.register_cognition_handlers as cog
    import app.neuro_bus.bus_setup as bs
    import app.neuro_bus.health_monitor as hm
    import app.neuro_bus.register_runtime as rr

    monkeypatch.setattr(rr, "register_neuro_runtime", fake_register)
    monkeypatch.setattr(bs, "get_neuro_bus_manager", lambda: "MANAGER")
    monkeypatch.setattr(
        hm,
        "get_health_monitor",
        lambda: (_ for _ in ()).throw(RuntimeError("hm down")),
    )
    monkeypatch.setattr(
        cog,
        "register_cognition_handlers",
        lambda: (_ for _ in ()).throw(RuntimeError("cog down")),
    )

    app = _fake_app()
    with caplog.at_level(logging.WARNING):
        await L._init_neuro_ddd_async(app)

    # bus still stored despite both inner failures
    assert app.state.neuro_bus is bus
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "HealthMonitor 启动失败" in joined
    assert "认知层 handler 注册失败" in joined


async def test_init_neuro_ddd_register_failure(monkeypatch, caplog):
    """register_neuro_runtime raising -> outer except, no bus (285-286)."""
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")

    async def boom():
        raise RuntimeError("registry down")

    import app.neuro_bus.register_runtime as rr

    monkeypatch.setattr(rr, "register_neuro_runtime", boom)

    app = _fake_app()
    with caplog.at_level(logging.WARNING):
        await L._init_neuro_ddd_async(app)

    assert not hasattr(app.state, "neuro_bus")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "神经总线初始化失败" in joined


# ---------------------------------------------------------------------------
# _init_employee_runtime_async
# ---------------------------------------------------------------------------
async def test_init_employee_runtime_success(monkeypatch):
    """Triggers + scheduler statuses stored on app.state (295-303)."""
    import app.application.employee_runtime.scheduler as sched
    import app.application.employee_runtime.triggers as trg

    monkeypatch.setattr(trg, "refresh_employee_triggers", lambda: {"registered": ["a", "b"]})
    monkeypatch.setattr(sched, "start_employee_scheduler", lambda: {"running": True})

    app = _fake_app()
    await L._init_employee_runtime_async(app)

    assert app.state.employee_triggers == {"registered": ["a", "b"]}
    assert app.state.employee_scheduler == {"running": True}


async def test_init_employee_runtime_failure(monkeypatch, caplog):
    """Trigger refresh raising -> except branch logs warning (304-305)."""
    import app.application.employee_runtime.triggers as trg

    def boom():
        raise RuntimeError("trigger boom")

    monkeypatch.setattr(trg, "refresh_employee_triggers", boom)

    app = _fake_app()
    with caplog.at_level(logging.WARNING):
        await L._init_employee_runtime_async(app)

    assert not hasattr(app.state, "employee_triggers")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "员工运行时初始化失败" in joined


# ---------------------------------------------------------------------------
# _init_mobile_relay_desktop_async
# ---------------------------------------------------------------------------
async def test_init_mobile_relay_running(monkeypatch, caplog):
    """Poller returns True -> state set + started log (313-316)."""
    import app.services.mobile_relay_desktop_client as mrc

    monkeypatch.setattr(mrc, "start_desktop_relay_poller", lambda: True)

    app = _fake_app()
    with caplog.at_level(logging.INFO):
        await L._init_mobile_relay_desktop_async(app)

    assert app.state.mobile_relay_desktop_running is True
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "移动端云中继轮询已启动" in joined


async def test_init_mobile_relay_not_running(monkeypatch, caplog):
    """Poller returns False -> state set False, no 'started' log."""
    import app.services.mobile_relay_desktop_client as mrc

    monkeypatch.setattr(mrc, "start_desktop_relay_poller", lambda: False)

    app = _fake_app()
    with caplog.at_level(logging.INFO):
        await L._init_mobile_relay_desktop_async(app)

    assert app.state.mobile_relay_desktop_running is False
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "移动端云中继轮询已启动" not in joined


async def test_init_mobile_relay_failure(monkeypatch, caplog):
    """Poller raising -> except branch logs warning (317-318)."""
    import app.services.mobile_relay_desktop_client as mrc

    def boom():
        raise RuntimeError("relay boom")

    monkeypatch.setattr(mrc, "start_desktop_relay_poller", boom)

    app = _fake_app()
    with caplog.at_level(logging.WARNING):
        await L._init_mobile_relay_desktop_async(app)

    assert not hasattr(app.state, "mobile_relay_desktop_running")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "移动端云中继轮询启动失败" in joined


# ---------------------------------------------------------------------------
# _init_mods_async
# ---------------------------------------------------------------------------
async def test_init_mods_full_load_done(caplog):
    """mods_full_load_done -> early skip (323-324)."""
    app = _fake_app()
    app.state.mods_full_load_done = True
    with caplog.at_level(logging.INFO):
        await L._init_mods_async(app)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "fully loaded" in joined


async def test_init_mods_background_scheduled(caplog):
    """mods_background_load_scheduled -> early skip (326-328)."""
    app = _fake_app()
    app.state.mods_full_load_done = False
    app.state.mods_background_load_scheduled = True
    with caplog.at_level(logging.INFO):
        await L._init_mods_async(app)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "background load in progress" in joined


async def test_init_mods_routes_loaded(caplog):
    """mods_routes_loaded -> early skip (329-331)."""
    app = _fake_app()
    app.state.mods_full_load_done = False
    app.state.mods_background_load_scheduled = False
    app.state.mods_routes_loaded = True
    with caplog.at_level(logging.INFO):
        await L._init_mods_async(app)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "routes staged" in joined


async def test_init_mods_bootstrap_success(monkeypatch, caplog):
    """No skip flags -> bootstrap_mod_extensions_sync invoked (332-336)."""
    app = _fake_app()
    app.state.mods_full_load_done = False
    app.state.mods_background_load_scheduled = False
    app.state.mods_routes_loaded = False

    seen = {}
    import app.fastapi_app.mod_startup as ms

    monkeypatch.setattr(ms, "bootstrap_mod_extensions_sync", lambda a: seen.setdefault("app", a))

    with caplog.at_level(logging.INFO):
        await L._init_mods_async(app)

    assert seen["app"] is app
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "lifespan 补偿路径" in joined


async def test_init_mods_bootstrap_failure(monkeypatch, caplog):
    """bootstrap raising -> except branch logs warning (337-338)."""
    app = _fake_app()
    app.state.mods_full_load_done = False
    app.state.mods_background_load_scheduled = False
    app.state.mods_routes_loaded = False

    import app.fastapi_app.mod_startup as ms

    def boom(a):
        raise RuntimeError("bootstrap boom")

    monkeypatch.setattr(ms, "bootstrap_mod_extensions_sync", boom)

    with caplog.at_level(logging.WARNING):
        await L._init_mods_async(app)

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "Mod 扩展初始化失败" in joined
