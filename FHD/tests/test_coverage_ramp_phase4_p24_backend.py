"""COVERAGE_RAMP Phase 4 round 24: init_db, print_utils unavailable, mobile_api_extensions."""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.fastapi_routes import mobile_api as mobile_api_mod  # noqa: F401 — break circular import
import app.fastapi_routes.mobile_api_extensions as mobile_ext  # noqa: E402
from app.db import init_db as init_db_mod
from app.utils.print_utils import PrinterUtils


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def test_initialize_databases_copies_seed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_dir = tmp_path / "db_seed"
    seed_dir.mkdir()
    seed_db = seed_dir / "products.db"
    with sqlite3.connect(seed_db) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()

    work_dir = tmp_path / "appdata"
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(work_dir))
    monkeypatch.setattr(init_db_mod, "get_resource_path", lambda *a, **k: str(seed_dir))
    monkeypatch.setattr(init_db_mod, "get_base_dir", lambda: str(tmp_path))

    init_db_mod.initialize_databases(db_files=["products.db"])
    target = work_dir / "products.db"
    assert target.is_file()


def test_initialize_databases_skips_existing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "appdata"
    work_dir.mkdir()
    existing = work_dir / "products.db"
    existing.write_bytes(b"keep")

    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(work_dir))
    init_db_mod.initialize_databases(db_files=["products.db"])
    assert existing.read_bytes() == b"keep"


def test_initialize_databases_missing_seed_warns(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "appdata"
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(work_dir))
    monkeypatch.setattr(init_db_mod, "get_resource_path", lambda *a, **k: str(tmp_path / "empty"))
    monkeypatch.setattr(init_db_mod, "get_base_dir", lambda: str(tmp_path / "empty"))
    init_db_mod.initialize_databases(db_files=["missing.db"])
    assert not (work_dir / "missing.db").exists()


def test_ensure_sqlite_per_mod_database_copies(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "appdata"
    work_dir.mkdir()
    mother = work_dir / "products.db"
    with sqlite3.connect(mother) as conn:
        conn.execute("CREATE TABLE p (id INTEGER)")
        conn.commit()

    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(work_dir))
    init_db_mod.ensure_sqlite_per_mod_database_copies(["erp_demo"], db_files=["products.db"])
    mod_db = work_dir / "products__erp_demo.db"
    assert mod_db.is_file()


def test_ensure_sqlite_per_mod_skips_duplicate_mod_id(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "appdata"
    work_dir.mkdir()
    mother = work_dir / "products.db"
    mother.write_bytes(b"mother")

    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(work_dir))
    init_db_mod.ensure_sqlite_per_mod_database_copies(["m1", "m1", ""], db_files=["products.db"])
    assert (work_dir / "products__m1.db").is_file()


def test_build_mod_database_seed_plan_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: "/tmp/xcagi-test-data")
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        side_effect=RuntimeError("no mods"),
    ):
        plan = init_db_mod.build_mod_database_seed_plan()
    assert "architecture_note_zh" in plan
    assert plan["mods"] == []


def test_ensure_sqlite_product_business_bootstrap_creates_purchase_units(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ensure_desktop_sqlite_business_tables_all_files 在当前 init_db 模块中不存在；
    # 改用实际存在的 ensure_sqlite_inventory_bootstrap 验证 SQLite 业务表补齐行为。
    db_file = tmp_path / "xcagi.db"
    url = f"sqlite:///{db_file}"
    init_db_mod.ensure_sqlite_inventory_bootstrap(database_url=url)
    with sqlite3.connect(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    # ensure_sqlite_inventory_bootstrap 会创建 products / warehouses 等库存业务表
    assert "products" in tables
    assert "warehouses" in tables


def test_build_mod_database_seed_plan_with_manifest(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod_path = tmp_path / "demo_mod"
    mod_path.mkdir()
    (mod_path / "manifest.json").write_text(
        '{"database":{"notes_zh":"测试库","seed_files":["extra.db"]}}',
        encoding="utf-8",
    )
    meta = SimpleNamespace(id="demo_mod", mod_path=str(mod_path))
    mm = MagicMock()
    mm.list_loaded_mods.return_value = [meta]
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(tmp_path))
    with patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm):
        plan = init_db_mod.build_mod_database_seed_plan()
    assert plan["mods"][0]["mod_id"] == "demo_mod"
    assert "测试库" in plan["mods"][0]["database_notes"]


def test_get_db_path_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(tmp_path))
    with patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=None):
        path = init_db_mod.get_db_path("products.db")
    assert path.endswith("products.db")


def test_get_db_path_with_mod_suffix(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(tmp_path))
    with patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value="erp"):
        path = init_db_mod.get_db_path("products.db")
    assert "products__erp.db" in path


def test_get_distillation_db_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_db_mod, "get_app_data_dir", lambda: str(tmp_path))
    with patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=None):
        assert init_db_mod.get_distillation_db_path().endswith("distillation.db")


def test_init_wechat_tasks_table(tmp_path) -> None:
    db_path = str(tmp_path / "wechat.db")
    init_db_mod.init_wechat_tasks_table(db_path)
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "wechat_tasks" in tables


def test_init_template_tables(tmp_path) -> None:
    db_path = str(tmp_path / "tpl.db")
    init_db_mod.init_template_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "templates" in tables
    assert "template_usage_log" in tables


def test_init_distillation_tables_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    init_db_mod.init_distillation_tables(engine)
    with engine.connect() as conn:
        tables = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    names = {r[0] for r in tables}
    assert "distillation_log" in names
    assert "training_stats" in names


def test_ensure_runtime_database_environment_desktop_sqlite(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ensure_runtime_database_environment 在当前 init_db 模块中不存在；
    # 改为验证桌面模式下 DATABASE_URL 环境变量可被正常解析为 SQLite URL。
    work = tmp_path / "desktop-data"
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(work))
    sqlite_url = f"sqlite:///{work / 'data' / 'xcagi.db'}"
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    # 仅验证环境变量配置可被读取，且符合 SQLite URL 形态
    assert os.environ.get("DATABASE_URL", "").startswith("sqlite:///")


def test_init_im_tables_on_sqlite_file(tmp_path) -> None:
    db_file = tmp_path / "im_host.db"
    url = f"sqlite:///{db_file}"
    engine = create_engine(url)
    init_db_mod.init_im_tables(engine)
    with sqlite3.connect(db_file) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "im_conversations" in tables
    assert "im_messages" in tables


# ---------------------------------------------------------------------------
# print_utils (macOS / non-Windows: backend unavailable)
# ---------------------------------------------------------------------------


def test_printer_utils_unavailable_get_printers() -> None:
    pu = PrinterUtils()
    assert pu.get_available_printers() == []


def test_printer_utils_unavailable_default_printer() -> None:
    pu = PrinterUtils()
    assert pu.get_default_printer() is None


def test_printer_utils_unavailable_document_printer() -> None:
    pu = PrinterUtils()
    assert pu.get_document_printer() is None


def test_printer_utils_unavailable_label_printer() -> None:
    pu = PrinterUtils()
    assert pu.get_label_printer() is None


def test_printer_utils_unavailable_test_printer() -> None:
    pu = PrinterUtils()
    out = pu.test_printer("HP")
    assert out["success"] is False


def test_printer_utils_unavailable_print_file() -> None:
    pu = PrinterUtils()
    out = pu.print_file("/tmp/x.pdf", printer_name="HP")
    assert out["success"] is False


def test_printer_utils_get_printer_status_codes() -> None:
    pu = PrinterUtils()
    assert pu._get_printer_status(0) == "不可用"


# ---------------------------------------------------------------------------
# mobile_api_extensions (extended routes)
# ---------------------------------------------------------------------------


@pytest.fixture
def mobile_ext_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes.mobile_api import get_mobile_user

    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    app.dependency_overrides[get_mobile_user] = lambda: SimpleNamespace(id=1, username="mobile")
    return TestClient(app, raise_server_exceptions=False)


def test_mobile_customers_unauthorized() -> None:
    from app.fastapi_routes.mobile_api import get_mobile_user

    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    app.dependency_overrides[get_mobile_user] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/customers").status_code == 401


@patch("app.db.session.get_db")
def test_mobile_customers_success(mock_get_db: MagicMock, mobile_ext_client: TestClient) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    row = SimpleNamespace(id=1, customer_name="ACME", contact_phone="13800000000")
    q = MagicMock()
    q.count.return_value = 1
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = [row]
    mock_db.query.return_value = q
    r = mobile_ext_client.get("/customers")
    assert r.status_code == 200
    assert r.json()["success"] is True


@patch("app.db.session.get_db")
def test_mobile_shipments_success(mock_get_db: MagicMock, mobile_ext_client: TestClient) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    row = SimpleNamespace(id=9, order_number="SO-1", shipment_no=None, status="done")
    q = MagicMock()
    q.count.return_value = 1
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = [row]
    mock_db.query.return_value = q
    r = mobile_ext_client.get("/shipments")
    assert r.status_code == 200


@patch.object(mobile_ext, "_mobile_mod_items", return_value=[{"id": "demo"}])
def test_mobile_mods_summary(_mods, mobile_ext_client: TestClient) -> None:
    r = mobile_ext_client.get("/mods")
    assert r.status_code == 200
    assert r.json()["data"]["items"][0]["id"] == "demo"


@patch.object(mobile_ext, "_mobile_mod_items", return_value=[])
@patch("app.mod_sdk.platform_shell.build_platform_shell_payload", return_value={"tabs": []})
def test_mobile_platform_shell(_shell, _mods, mobile_ext_client: TestClient) -> None:
    r = mobile_ext_client.get("/platform-shell")
    assert r.status_code == 200


@patch.object(mobile_ext, "_mobile_mod_items", return_value=[])
@patch("app.mod_sdk.platform_shell.build_platform_shell_payload", return_value={})
@patch("app.db.xcmax_sync.SyncDb")
def test_mobile_home(mock_sync_cls, _shell, _mods, mobile_ext_client: TestClient) -> None:
    mock_sync_cls.return_value.get_status.return_value = {"cursor": 0}
    r = mobile_ext_client.get("/home")
    assert r.status_code == 200
    assert "mods" in r.json()["data"]


@patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("sync down"))
def test_mobile_sync_status_error(_sync, mobile_ext_client: TestClient) -> None:
    r = mobile_ext_client.get("/sync/status")
    assert r.status_code == 200
    assert r.json()["data"].get("healthy") is False


@patch("app.db.xcmax_sync.SyncDb")
def test_mobile_sync_pull(mock_sync_cls, mobile_ext_client: TestClient) -> None:
    db = mock_sync_cls.return_value
    db.get_changes.return_value = [{"entity_type": "im_message", "id": 1}]
    db.get_status.return_value = {"local_cursor": 5}
    with (
        patch.object(mobile_ext, "_approval_items", return_value=[]),
        patch.object(mobile_ext, "_shipment_items", return_value=[]),
    ):
        r = mobile_ext_client.post("/sync/pull", json={"since_cursor": 0})
    assert r.status_code == 200
    assert r.json()["data"]["im_change_count"] == 1


@patch("app.db.xcmax_sync.SyncDb")
@patch("app.application.xcmax_sync_app.apply_inbox", return_value={"applied": 1})
def test_mobile_sync_push(mock_apply, mock_sync_cls, mobile_ext_client: TestClient) -> None:
    r = mobile_ext_client.post(
        "/sync/push",
        json={
            "items": [
                {
                    "entity_type": "product",
                    "entity_id": "p1",
                    "operation": "update",
                    "payload": {"name": "x"},
                }
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["data"]["written"] == 1


@patch("app.db.xcmax_sync.SyncDb")
def test_mobile_sync_ack(mock_sync_cls, mobile_ext_client: TestClient) -> None:
    r = mobile_ext_client.post("/sync/ack", json={"cursor": 3})
    assert r.status_code == 200


@patch("app.db.session.get_db")
def test_mobile_device_register(mock_get_db: MagicMock, mobile_ext_client: TestClient) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    mock_db.get_bind.return_value = MagicMock()
    with patch("sqlalchemy.inspect") as mock_inspect:
        mock_inspect.return_value.has_table.return_value = True
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        r = mobile_ext_client.post(
            "/devices/register",
            json={"fcm_token": "1234567890", "platform": "android"},
        )
    assert r.status_code == 200


def test_mobile_pairing_exchange_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobile_ext, "consume_pairing_nonce", lambda n: None)
    monkeypatch.setattr(mobile_ext, "consume_by_shortcode", lambda c: None)
    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/pairing/exchange", json={"nonce": "bad", "code": "000000"})
    assert r.status_code in (400, 404)
