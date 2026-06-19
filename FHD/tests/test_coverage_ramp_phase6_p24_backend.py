"""COVERAGE_RAMP Phase 6 round 24: backend medium-coverage modules.

Substitutions for modules whose literal path does not exist:
- ``app/application/session_context_service.py`` → ``app/services/session_service.py``
- ``app/services/task_queue.py`` → ``app/desktop_runtime/queue.py``
- ``app/infrastructure/skills/skill_registry.py`` → ``app.infrastructure.skills``
- ``app/neuro_bus/routing/router.py`` → ``app/neuro_bus/routing/policy_router.py``
- ``app/services/sync_service.py`` → ``app/services/xcmax_sync_service.py``
- ``app/application/mod_manager_service.py`` → ``app/infrastructure/mods/mod_manager.py``
- ``app/mod_sdk/seed_helpers.py`` → ``app/mod_sdk/industry_seed.py``

Targets already have partial coverage in earlier phase files / dedicated tests;
this file focuses on uncovered branches and exception paths.
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import sqlite3
import tempfile
import time
import uuid
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop_runtime import queue as desktop_queue
from app.fastapi_routes import print_routes
from app.fastapi_routes.print_routes import router as print_router
from app.infrastructure.mods import mod_manager as mod_manager_mod
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _backend_path_for_mod,
    _default_mods_root,
    _invoke_mod_init_hook,
    _register_mod_hooks,
    _repo_layout_mods_candidates,
    _short_exc_message,
    import_mod_backend_py,
    is_mods_disabled,
)
from app.infrastructure.skills import (
    SkillRegistry,
    execute_skill,
    get_skill_registry,
)
from app.mod_sdk import industry_seed as industry_seed_mod
from app.mod_sdk.industry_seed import (
    bundled_industry_seeds_dir,
    deactivate_other_open_industry_mods,
    industry_mod_id_for,
    install_industry_seed_with_fallback,
    open_industry_seed_mod_ids,
    other_open_industry_mod_ids,
    resolve_industry_or_mod_id,
    seed_industry_mod,
)
from app.neuro_bus.routing.policy_router import (
    _ACTION_ORDER,
    decide_processor_with_policy,
)
from app.services import session_service as session_service_mod
from app.services.session_service import SessionService
from app.services.xcmax_sync_service import (
    _ENTITY_APPLIERS,
    apply_inbox,
    push_outbox,
    record_change,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_db_ctx(mock_db: MagicMock):
    """Return a context manager that yields *mock_db*."""

    @classmethod
    def _cm(_cls):
        yield mock_db

    return _cm()


def _mock_get_db(mock_db: MagicMock):
    """Return a context manager yielding *mock_db* for patching app.db.get_db."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        yield mock_db

    return _cm


@pytest.fixture
def print_client() -> TestClient:
    app = FastAPI()
    app.include_router(print_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def tmp_mods_root(tmp_path: Path) -> Path:
    root = tmp_path / "mods"
    root.mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# 1. app/services/session_service.py
# ---------------------------------------------------------------------------


class TestSessionServiceCreateSession:
    def test_create_session_returns_success(self):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = 7
        mock_db.add.return_value = None
        mock_db.commit.return_value = None

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().create_session(user_id=42)

        assert result["success"] is True
        assert result["user_id"] == 42
        assert "session_id" in result
        assert "expires_at" in result

    def test_create_session_db_error_raises(self):
        mock_db = MagicMock()
        mock_db.add.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"), patch(
            "app.services.session_service.get_db", _mock_get_db(mock_db)
        ):
            SessionService().create_session(user_id=42)


class TestSessionServiceValidateSession:
    def test_validate_session_delegates_to_manager(self):
        mock_mgr = MagicMock()
        mock_mgr.validate_session.return_value = {"user_id": 42}

        with patch(
            "app.infrastructure.session.session_manager.get_session_manager",
            return_value=mock_mgr,
        ):
            result = SessionService().validate_session("sess-1")

        assert result == {"user_id": 42}
        mock_mgr.validate_session.assert_called_once_with("sess-1")


class TestSessionServiceGetSessionInfo:
    def test_get_session_info_found_and_valid(self):
        from app.utils.time import utc_now_naive

        mock_db = MagicMock()
        user_session = MagicMock()
        user_session.expires_at = utc_now_naive() + timedelta(hours=1)
        user_session.session_id = "sess-1"
        user_session.user_id = 42
        user_session.user.username = "alice"
        user_session.created_at = utc_now_naive()
        mock_db.query.return_value.filter.return_value.first.return_value = user_session

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().get_session_info("sess-1")

        assert result is not None
        assert result["session_id"] == "sess-1"
        assert result["username"] == "alice"

    def test_get_session_info_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().get_session_info("missing")

        assert result is None

    def test_get_session_info_expired(self):
        from app.utils.time import utc_now_naive

        mock_db = MagicMock()
        user_session = MagicMock()
        user_session.expires_at = utc_now_naive() - timedelta(hours=1)
        user_session.session_id = "expired"
        user_session.user_id = 42
        user_session.user.username = "alice"
        user_session.created_at = utc_now_naive()
        mock_db.query.return_value.filter.return_value.first.return_value = user_session

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().get_session_info("expired")

        assert result is None


class TestSessionServiceDeleteSession:
    def test_delete_session_found(self):
        mock_db = MagicMock()
        user_session = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = user_session

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().delete_session("sess-1")

        assert result is True
        mock_db.delete.assert_called_once_with(user_session)
        mock_db.commit.assert_called_once()

    def test_delete_session_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().delete_session("missing")

        assert result is False
        mock_db.delete.assert_not_called()


class TestSessionServiceCleanupSessions:
    def test_delete_user_sessions(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 3

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().delete_user_sessions(user_id=42)

        assert result == 3

    def test_cleanup_expired_sessions(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 5

        with patch("app.services.session_service.get_db", _mock_get_db(mock_db)):
            result = SessionService().cleanup_expired_sessions()

        assert result == 5


class TestSessionServiceSingleton:
    def test_get_session_service(self):
        mock_registry = MagicMock()
        mock_registry.session_service = MagicMock()

        with patch(
            "app.services.session_service.get_service_registry", return_value=mock_registry
        ):
            result = session_service_mod.get_session_service()

        assert result is mock_registry.session_service


# ---------------------------------------------------------------------------
# 2. app/fastapi_routes/print_routes.py
# ---------------------------------------------------------------------------


class TestPrintRoutesPrinters:
    def test_get_printers_success(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.return_value = {
                "success": True,
                "printers": [{"name": "P1"}],
            }
            r = print_client.get("/api/print/printers")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_get_printers_exception_returns_500(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.side_effect = RuntimeError("boom")
            r = print_client.get("/api/print/printers")
        assert r.status_code == 500
        assert "boom" in r.json()["message"]

    def test_get_printer_selection_success(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printer_selection.return_value = {"document": "D1"}
            r = print_client.get("/api/print/printer-selection")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_get_printer_selection_exception(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printer_selection.side_effect = OSError("fail")
            r = print_client.get("/api/print/printer-selection")
        assert r.status_code == 500


class TestPrintRoutesSaveSelection:
    def test_save_selection_invalid_document_printer(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.return_value = {"printers": [{"name": "P1"}]}
            r = print_client.put(
                "/api/print/printer-selection", json={"document_printer": "P2"}
            )
        assert r.status_code == 400
        assert "发货单打印机" in r.json()["message"]

    def test_save_selection_invalid_label_printer(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.return_value = {"printers": [{"name": "P1"}]}
            r = print_client.put(
                "/api/print/printer-selection", json={"label_printer": "P2"}
            )
        assert r.status_code == 400
        assert "标签打印机" in r.json()["message"]

    def test_save_selection_success(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.return_value = {"printers": [{"name": "P1"}]}
            svc.return_value.save_printer_selection.return_value = {"success": True}
            svc.return_value.classify_printers.return_value = {"doc": "P1"}
            r = print_client.put(
                "/api/print/printer-selection",
                json={"document_printer": "P1", "label_printer": "P1"},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["doc"] == "P1"

    def test_save_selection_exception(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.side_effect = RuntimeError("boom")
            r = print_client.put("/api/print/printer-selection", json={})
        assert r.status_code == 500


class TestPrintRoutesDocument:
    def test_print_document_empty_path(self, print_client: TestClient):
        r = print_client.post("/api/print/document", json={})
        assert r.status_code == 400
        assert "文件路径" in r.json()["message"]

    def test_print_document_missing_file(self, print_client: TestClient):
        with patch("os.path.exists", return_value=False):
            r = print_client.post("/api/print/document", json={"file_path": "/no/such.pdf"})
        assert r.status_code == 400
        assert "文件不存在" in r.json()["message"]

    def test_print_document_success(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.print_document.return_value = {"success": True}
            r = print_client.post(
                "/api/print/document",
                json={"file_path": "/tmp/x.pdf", "printer_name": "P1"},
            )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_print_document_failed_result_returns_400(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.print_document.return_value = {
                "success": False,
                "message": "printer busy",
            }
            r = print_client.post("/api/print/document", json={"file_path": "/tmp/x.pdf"})
        assert r.status_code == 400

    def test_print_document_exception(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.print_document.side_effect = RuntimeError("boom")
            r = print_client.post("/api/print/document", json={"file_path": "/tmp/x.pdf"})
        assert r.status_code == 500


class TestPrintRoutesLabel:
    def test_print_label_copies_not_int(self, print_client: TestClient):
        with patch("os.path.exists", return_value=True):
            r = print_client.post(
                "/api/print/label",
                json={"file_path": "/tmp/x.pdf", "copies": "abc", "require_confirm": False},
            )
        assert r.status_code == 400
        assert "1-100" in r.json()["message"]

    def test_print_label_copies_out_of_range(self, print_client: TestClient):
        with patch("os.path.exists", return_value=True):
            r = print_client.post(
                "/api/print/label",
                json={"file_path": "/tmp/x.pdf", "copies": 101, "require_confirm": False},
            )
        assert r.status_code == 400
        assert "1-100" in r.json()["message"]

    def test_print_label_require_confirm_cancel(self, print_client: TestClient):
        print_routes._print_confirm_cache.clear()
        token = print_routes._create_print_confirm_token({"job": "j1"})
        with patch("os.path.exists", return_value=True):
            r = print_client.post(
                "/api/print/label",
                json={
                    "file_path": "/tmp/x.pdf",
                    "require_confirm": True,
                    "confirm_action": "cancel",
                    "confirm_token": token,
                },
            )
        assert r.status_code == 200
        assert r.json()["status"] == "print_cancelled"
        assert token not in print_routes._print_confirm_cache

    def test_print_label_require_confirm_no_token(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.get_label_printer.return_value = "LabelPrinter"
            r = print_client.post(
                "/api/print/label",
                json={"file_path": "/tmp/x.pdf", "require_confirm": True},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "print_confirm_required"
        assert "confirm_token" in data

    def test_print_label_require_confirm_expired_token(self, print_client: TestClient):
        with patch("os.path.exists", return_value=True):
            r = print_client.post(
                "/api/print/label",
                json={
                    "file_path": "/tmp/x.pdf",
                    "require_confirm": True,
                    "confirm_token": "dead-token",
                },
            )
        assert r.status_code == 400
        assert "过期或无效" in r.json()["message"]

    def test_print_label_require_confirm_valid_token(self, print_client: TestClient):
        print_routes._print_confirm_cache.clear()
        token = print_routes._create_print_confirm_token(
            {"file_path": "/tmp/x.pdf", "copies": 2, "printer_name": "P1"}
        )
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.print_label.return_value = {"success": True}
            r = print_client.post(
                "/api/print/label",
                json={"file_path": "/tmp/x.pdf", "require_confirm": True, "confirm_token": token},
            )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_print_label_no_confirm_failed(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.print_label.return_value = {"success": False}
            r = print_client.post(
                "/api/print/label",
                json={"file_path": "/tmp/x.pdf", "require_confirm": False},
            )
        assert r.status_code == 400

    def test_print_label_exception(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc, patch(
            "os.path.exists", return_value=True
        ):
            svc.return_value.print_label.side_effect = RuntimeError("boom")
            r = print_client.post(
                "/api/print/label",
                json={"file_path": "/tmp/x.pdf", "require_confirm": False},
            )
        assert r.status_code == 500


class TestPrintRoutesOtherEndpoints:
    def test_test_printer_post_empty_name(self, print_client: TestClient):
        r = print_client.post("/api/print/test", json={})
        assert r.status_code == 400

    def test_test_printer_post_success(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.test_printer.return_value = {"success": True}
            r = print_client.post("/api/print/test", json={"printer_name": "P1"})
        assert r.status_code == 200

    def test_validate_printer_separation(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.validate_printer_separation.return_value = {"valid": True}
            r = print_client.get("/api/print/validate")
        assert r.status_code == 200
        assert r.json()["valid"] is True

    def test_get_document_printer_found(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_document_printer.return_value = {"name": "D1"}
            r = print_client.get("/api/print/document-printer")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_get_document_printer_not_found(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_document_printer.return_value = None
            r = print_client.get("/api/print/document-printer")
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_get_label_printer_exception(self, print_client: TestClient):
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_label_printer.side_effect = RuntimeError("boom")
            r = print_client.get("/api/print/label-printer")
        assert r.status_code == 500

    def test_test_print_service_get(self, print_client: TestClient):
        r = print_client.get("/api/print/test")
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestPrintRoutesWorkflowLabel:
    def test_dispatch_missing_model_number(self, print_client: TestClient):
        r = print_client.post("/api/print/workflow/label-print/dispatch", json={})
        assert r.status_code == 400
        assert "model_number" in r.json()["message"]

    def test_dispatch_idempotency_skips_duplicate(self, print_client: TestClient):
        print_routes._print_confirm_cache["wf_lp:key1"] = {
            "expires_at": time.time() + 100,
            "model_number": "M1",
        }
        r = print_client.post(
            "/api/print/workflow/label-print/dispatch",
            json={"idempotency_key": "key1", "model_number": "M1"},
        )
        assert r.status_code == 200
        assert r.json()["skipped"] is True

    def test_dispatch_lookup_error_still_prints(self, print_client: TestClient):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as get_svc, patch(
            "app.application.get_product_app_service"
        ) as get_prod:
            get_prod.return_value.search_products.side_effect = RuntimeError("lookup fail")
            get_svc.return_value.print_single_label.return_value = {"success": True}
            r = print_client.post(
                "/api/print/workflow/label-print/dispatch",
                json={"idempotency_key": "key2", "model_number": "M1"},
            )
        assert r.status_code == 200

    def test_dispatch_print_failed(self, print_client: TestClient):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as get_svc, patch(
            "app.application.get_product_app_service"
        ) as get_prod:
            get_prod.return_value.search_products.return_value = []
            get_svc.return_value.print_single_label.return_value = {
                "success": False,
                "message": "no label",
            }
            r = print_client.post(
                "/api/print/workflow/label-print/dispatch",
                json={"idempotency_key": "key3", "model_number": "M1"},
            )
        assert r.status_code == 400

    def test_dispatch_exception(self, print_client: TestClient):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as get_svc:
            get_svc.return_value.print_single_label.side_effect = RuntimeError("boom")
            r = print_client.post(
                "/api/print/workflow/label-print/dispatch",
                json={"idempotency_key": "key4", "model_number": "M1"},
            )
        assert r.status_code == 500


class TestPrintRoutesListLabels:
    def test_list_labels_dir_missing(self, print_client: TestClient):
        with patch(
            "app.utils.path_utils.get_resource_path", return_value="/no/such/dir"
        ):
            r = print_client.get("/api/print/list_labels")
        assert r.status_code == 200
        assert r.json()["labels"] == []

    def test_list_labels_filters_extensions(self, tmp_path: Path, print_client: TestClient):
        labels_dir = tmp_path / "商标导出"
        labels_dir.mkdir()
        (labels_dir / "order1_第1项.png").write_text("png")
        (labels_dir / "order2.txt").write_text("txt")
        with patch(
            "app.utils.path_utils.get_resource_path", return_value=str(labels_dir)
        ):
            r = print_client.get("/api/print/list_labels")
        data = r.json()
        assert len(data["labels"]) == 1
        assert data["labels"][0]["filename"] == "order1_第1项.png"

    def test_list_labels_limit(self, tmp_path: Path, print_client: TestClient):
        labels_dir = tmp_path / "商标导出"
        labels_dir.mkdir()
        for i in range(5):
            (labels_dir / f"order{i}.png").write_text("png")
        with patch(
            "app.utils.path_utils.get_resource_path", return_value=str(labels_dir)
        ):
            r = print_client.get("/api/print/list_labels?limit=2")
        assert len(r.json()["labels"]) == 2

    def test_serve_label_image_not_found(self, print_client: TestClient):
        with patch(
            "app.utils.path_utils.get_resource_path", return_value="/no/such/dir"
        ), patch("os.path.exists", return_value=False):
            r = print_client.get("/api/print/label/missing.png")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. app/desktop_runtime/queue.py
# ---------------------------------------------------------------------------


class TestDesktopQueue:
    def test_submit_background_runs_func(self):
        done = {"ok": False}

        def job():
            done["ok"] = True

        fut = desktop_queue.submit_background(job)
        fut.result(timeout=5)
        assert done["ok"] is True

    def test_submit_background_with_args(self):
        def add(a, b):
            return a + b

        fut = desktop_queue.submit_background(add, 2, 3)
        assert fut.result(timeout=5) == 5

    def test_submit_background_with_kwargs(self):
        def greet(name, suffix="!"):
            return f"hi {name}{suffix}"

        fut = desktop_queue.submit_background(greet, "world", suffix="?")
        assert fut.result(timeout=5) == "hi world?"

    def test_submit_background_returns_future(self):
        fut = desktop_queue.submit_background(lambda: 42)
        assert isinstance(fut, Future)
        assert fut.result(timeout=5) == 42

    def test_submit_background_exception_surfaces(self):
        def boom():
            raise ValueError("bad")

        fut = desktop_queue.submit_background(boom)
        with pytest.raises(ValueError, match="bad"):
            fut.result(timeout=5)

    def test_shutdown_background_tasks_wait(self):
        mock_executor = MagicMock()
        with patch.object(desktop_queue, "_executor", mock_executor):
            desktop_queue.shutdown_background_tasks(wait=True)
        mock_executor.shutdown.assert_called_once_with(wait=True, cancel_futures=False)

    def test_shutdown_background_tasks_no_wait(self):
        mock_executor = MagicMock()
        with patch.object(desktop_queue, "_executor", mock_executor):
            desktop_queue.shutdown_background_tasks(wait=False)
        mock_executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# 4. app/infrastructure/skills/__init__.py
# ---------------------------------------------------------------------------


class TestSkillRegistryRegister:
    def test_register_without_name_logs_empty(self, caplog):
        reg = SkillRegistry()
        reg.register("s1", {})
        assert reg.get("s1") == {}

    def test_list_all_with_category(self):
        reg = SkillRegistry()
        reg.register("s1", {"name": "S1", "category": "math"})
        result = reg.list_all()
        assert result[0]["category"] == "math"


class TestSkillRegistryFindByKeyword:
    def test_find_by_keyword_empty_matches_all(self):
        reg = SkillRegistry()
        reg.register("s1", {"name": "S1", "keywords": ["excel"]})
        # Empty keyword is contained by every keyword string via substring check.
        assert reg.find_by_keyword("") == ["s1"]

    def test_find_by_keyword_skill_has_no_keywords(self):
        reg = SkillRegistry()
        reg.register("s1", {"name": "S1"})
        assert reg.find_by_keyword("excel") == []

    def test_find_by_keyword_case_insensitive_match(self):
        reg = SkillRegistry()
        reg.register("s1", {"name": "S1", "keywords": ["Excel"]})
        assert reg.find_by_keyword("excel") == ["s1"]

    def test_find_by_keyword_partial_match(self):
        reg = SkillRegistry()
        reg.register("s1", {"name": "S1", "keywords": ["spreadsheet"]})
        assert reg.find_by_keyword("sheet") == ["s1"]


def _fake_skills_path(skills_dir: Path):
    """Return a fake Path class whose instances delegate to *skills_dir*."""

    class _FakePath:
        def __init__(self, *args):
            self._skills_dir = skills_dir

        @property
        def parent(self):
            return _FakePath(self._skills_dir)

        def exists(self):
            return self._skills_dir.exists()

        def is_dir(self):
            return self._skills_dir.is_dir()

        def iterdir(self):
            return iter(self._skills_dir.iterdir())

        def __truediv__(self, other):
            return self._skills_dir / other

        def __str__(self):
            return str(self._skills_dir)

    return _FakePath


class TestSkillRegistryInitialize:
    def test_initialize_skips_when_already_initialized(self):
        reg = SkillRegistry()
        reg._initialized = True
        reg.initialize()
        assert reg._initialized is True

    def test_initialize_skills_dir_missing(self, tmp_path: Path, monkeypatch):
        reg = SkillRegistry()
        missing = tmp_path / "missing"
        monkeypatch.setattr(
            "app.infrastructure.skills.Path",
            _fake_skills_path(missing),
        )
        reg.initialize()
        assert reg._initialized is True

    def test_initialize_file_not_dir(self, tmp_path: Path, monkeypatch):
        reg = SkillRegistry()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "not_a_dir").write_text("x")
        monkeypatch.setattr(
            "app.infrastructure.skills.Path",
            _fake_skills_path(skills_dir),
        )
        reg.initialize()
        assert "not_a_dir" not in reg._skills

    def test_initialize_skill_md_missing(self, tmp_path: Path, monkeypatch):
        reg = SkillRegistry()
        skills_dir = tmp_path / "skills"
        (skills_dir / "s1").mkdir(parents=True)
        monkeypatch.setattr(
            "app.infrastructure.skills.Path",
            _fake_skills_path(skills_dir),
        )
        reg.initialize()
        assert "s1" not in reg._skills

    def test_initialize_parse_returns_none(self, tmp_path: Path, monkeypatch):
        reg = SkillRegistry()
        skills_dir = tmp_path / "skills"
        sdir = skills_dir / "s1"
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text("no frontmatter")
        monkeypatch.setattr(
            "app.infrastructure.skills.Path",
            _fake_skills_path(skills_dir),
        )
        reg.initialize()
        assert "s1" not in reg._skills

    def test_initialize_load_exception(self, tmp_path: Path, monkeypatch):
        reg = SkillRegistry()
        skills_dir = tmp_path / "skills"
        sdir = skills_dir / "s1"
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text("---\nname: S1\n---\n")

        def bad_open(*args, **kwargs):
            raise OSError("read fail")

        monkeypatch.setattr(
            "app.infrastructure.skills.Path",
            _fake_skills_path(skills_dir),
        )
        with patch("builtins.open", side_effect=bad_open):
            reg.initialize()
        assert "s1" not in reg._skills
        assert reg._initialized is True


class TestSkillRegistryParseSkillMd:
    def test_parse_with_quoted_values(self):
        reg = SkillRegistry()
        content = '---\nname: "My Skill"\ndescription: "A desc"\n---\nBody'
        result = reg._parse_skill_md(content)
        assert result["name"] == "My Skill"
        assert result["description"] == "A desc"

    def test_parse_no_when_to_use(self):
        reg = SkillRegistry()
        content = "---\nname: S1\n---\n# S1\nSome body"
        result = reg._parse_skill_md(content)
        assert result["keywords"] == []

    def test_parse_keywords_split_by_hash(self):
        reg = SkillRegistry()
        content = (
            "---\nname: S1\n---\n"
            "## When to Use This Skill\n\n"
            "- one\n- two\n# Next section\n"
        )
        result = reg._parse_skill_md(content)
        assert result["keywords"] == ["one", "two"]

    def test_parse_empty_content_returns_none(self):
        reg = SkillRegistry()
        assert reg._parse_skill_md("") is None


class TestExecuteSkill:
    def test_unknown_skill(self):
        with patch("app.infrastructure.skills.get_skill_registry", return_value=SkillRegistry()):
            result = execute_skill("missing")
        assert result["success"] is False
        assert "未找到技能" in result["message"]

    def test_execute_skill_excel_analyzer_exception(self):
        reg = SkillRegistry()
        reg.register("excel_analyzer", {"name": "Excel"})
        with patch("app.infrastructure.skills.get_skill_registry", return_value=reg), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill"
        ) as get_skill:
            get_skill.side_effect = ImportError("no module")
            result = execute_skill("excel_analyzer")
        assert result["success"] is False

    def test_execute_skill_excel_toolkit(self):
        reg = SkillRegistry()
        reg.register("excel_toolkit", {"name": "Toolkit"})
        mock_skill = MagicMock()
        mock_skill.execute.return_value = {"success": True}
        with patch("app.infrastructure.skills.get_skill_registry", return_value=reg), patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_skill,
        ):
            result = execute_skill("excel_toolkit")
        assert result["success"] is True

    def test_execute_skill_label_template_generator(self):
        reg = SkillRegistry()
        reg.register("label_template_generator", {"name": "Label"})
        mock_skill = MagicMock()
        mock_skill.execute.return_value = {"success": True}
        with patch("app.infrastructure.skills.get_skill_registry", return_value=reg), patch(
            "app.infrastructure.skills.label_template_generator.label_template_generator.get_label_template_generator_skill",
            return_value=mock_skill,
        ):
            result = execute_skill("label_template_generator")
        assert result["success"] is True

    def test_execute_skill_unknown_type(self):
        reg = SkillRegistry()
        reg.register("other_skill", {"name": "Other"})
        with patch("app.infrastructure.skills.get_skill_registry", return_value=reg):
            result = execute_skill("other_skill")
        assert result["success"] is False
        assert "未知技能类型" in result["message"]


class TestGetSkillRegistry:
    def test_singleton(self):
        import app.infrastructure.skills as skills_mod

        old = skills_mod._skill_registry
        skills_mod._skill_registry = None
        try:
            with patch.object(SkillRegistry, "initialize"):
                r1 = get_skill_registry()
                r2 = get_skill_registry()
            assert r1 is r2
        finally:
            skills_mod._skill_registry = old


# ---------------------------------------------------------------------------
# 5. app/neuro_bus/routing/policy_router.py
# ---------------------------------------------------------------------------


class TestDecideProcessorWithPolicy:
    """policy_router 的 _load_canary_state() 有模块级缓存 _canary_cache（30s TTL）。
    全量套件中前序测试调用后缓存了旧值，patch.dict(os.environ) 无法影响缓存读取，
    导致期望 result is not None 的测试失败。此 fixture 在每个测试前重置缓存。

    注意：--import-mode=importlib 下，decide_processor_with_policy.__globals__
    可能与 sys.modules 中的模块 __dict__ 不是同一对象，需同时重置两者。
    """

    @pytest.fixture(autouse=True)
    def _reset_canary_cache(self):
        from app.neuro_bus.routing import policy_router as _pr
        # 重置 sys.modules 中模块的缓存
        _pr._canary_cache = None
        _pr._canary_cache_ts = 0.0
        # 重置 decide_processor_with_policy 实际引用的模块字典中的缓存
        # （--import-mode=importlib 可能导致两者不一致）
        _g = decide_processor_with_policy.__globals__
        _g["_canary_cache"] = None
        _g["_canary_cache_ts"] = 0.0
        yield
        _pr._canary_cache = None
        _pr._canary_cache_ts = 0.0
        _g["_canary_cache"] = None
        _g["_canary_cache_ts"] = 0.0

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            result = decide_processor_with_policy("hello")
        assert result is None

    def test_disabled_with_zero(self):
        with patch.dict(os.environ, {"XCAGI_ROUTING_POLICY_ENABLED": "0"}):
            result = decide_processor_with_policy("hello")
        assert result is None

    @pytest.mark.parametrize("enabled", ["1", "true", "yes", "on"])
    def test_enabled_variants(self, enabled: str):
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": enabled, "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(0, 0.9)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ):
            result = decide_processor_with_policy("hello")
        assert result is not None
        assert result.processor_type == _ACTION_ORDER[0]

    def test_negative_index_returns_none(self):
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(-1, 0.0)
        ):
            result = decide_processor_with_policy("hello")
        assert result is None

    def test_index_out_of_range_returns_none(self):
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(99, 0.9)
        ):
            result = decide_processor_with_policy("hello")
        assert result is None

    def test_trace_id_from_argument(self):
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(1, 0.9)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ) as log_mock:
            result = decide_processor_with_policy("hello", trace_id="tid-1")
        assert result is not None
        log_mock.assert_called_once()
        assert log_mock.call_args.kwargs["trace_id"] == "tid-1"

    def test_trace_id_from_event(self):
        event = MagicMock()
        event.metadata.trace_id = "evt-tid"
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(2, 0.9)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ) as log_mock:
            result = decide_processor_with_policy("hello", event=event)
        assert result is not None
        assert log_mock.call_args.kwargs["trace_id"] == "evt-tid"

    def test_extra_passed_to_features(self):
        extra = {"lang": "zh"}
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features",
            return_value={"lang": "zh"},
        ) as feat_mock, patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(0, 0.9)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ):
            decide_processor_with_policy("hello", extra=extra)
        feat_mock.assert_called_once_with("hello", None, extra)

    def test_shadow_mode_returns_none_but_logs(self):
        """影子模式：返回 None 但记录 NN 决策。"""
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "shadow", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(0, 0.85)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ) as log_mock:
            result = decide_processor_with_policy("hello", trace_id="shadow-1")
        assert result is None
        log_mock.assert_called_once()
        kwargs = log_mock.call_args.kwargs
        assert kwargs["trace_id"] == "shadow-1"
        assert kwargs["outcome"] == "policy_shadow"
        assert kwargs["sla_hit"] is None
        assert kwargs["success"] is None
        assert kwargs["extra"]["shadow"] is True
        assert kwargs["extra"]["confidence"] == 0.85

    def test_canary_fallback_returns_none_but_logs(self):
        """灰度回退：random > canary_ratio 时返回 None 但记录 fallback。"""
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "0.1"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(1, 0.7)
        ), patch(
            "app.neuro_bus.routing.policy_router.random.random", return_value=0.5
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ) as log_mock:
            result = decide_processor_with_policy("hello", trace_id="canary-1")
        assert result is None
        log_mock.assert_called_once()
        kwargs = log_mock.call_args.kwargs
        assert kwargs["outcome"] == "policy_canary_fallback"
        assert kwargs["extra"]["canary_fallback"] is True
        assert kwargs["extra"]["canary_ratio"] == 0.1
        assert kwargs["extra"]["confidence"] == 0.7
        assert kwargs["extra"]["shadow"] is False

    def test_canary_pass_through_returns_decision(self):
        """灰度放行：random <= canary_ratio 时正常路由。"""
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "0.5"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(2, 0.95)
        ), patch(
            "app.neuro_bus.routing.policy_router.random.random", return_value=0.3
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ):
            result = decide_processor_with_policy("hello")
        assert result is not None
        assert result.processor_type == _ACTION_ORDER[2]
        assert result.confidence == 0.95

    def test_confidence_passed_to_routing_decision(self):
        """confidence 来自 predict_with_confidence，不再硬编码 0.72。"""
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "1.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(0, 0.42)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ) as log_mock:
            result = decide_processor_with_policy("hello")
        assert result is not None
        assert result.confidence == 0.42
        assert log_mock.call_args.kwargs["extra"]["confidence"] == 0.42

    def test_canary_ratio_invalid_defaults_to_zero(self):
        """非法 canary_ratio 视为 0.0（全部回退）。"""
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "abc"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(0, 0.9)
        ), patch(
            "app.neuro_bus.routing.policy_router.random.random", return_value=0.001
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ):
            result = decide_processor_with_policy("hello")
        # canary_ratio=0.0 → random.random() > 0.0 → True → fallback
        assert result is None

    def test_canary_ratio_clamped_to_one(self):
        """canary_ratio > 1.0 被 clamp 到 1.0（全部放行）。"""
        with patch.dict(
            os.environ,
            {"XCAGI_ROUTING_POLICY_ENABLED": "1", "XCAGI_ROUTING_POLICY_CANARY_RATIO": "5.0"},
        ), patch(
            "app.neuro_bus.routing.policy_router.build_routing_features", return_value={}
        ), patch(
            "app.neuro_bus.routing.policy_router.predict_with_confidence", return_value=(0, 0.9)
        ), patch(
            "app.neuro_bus.routing.policy_router.append_routing_decision"
        ):
            result = decide_processor_with_policy("hello")
        assert result is not None


# ---------------------------------------------------------------------------
# 6. app/services/xcmax_sync_service.py
# ---------------------------------------------------------------------------


class TestXcmaxSyncRecordChange:
    def test_record_change_success(self, tmp_path: Path):
        db_path = tmp_path / "sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), patch(
            "app.db.xcmax_sync._db_path", None
        ):
            result = record_change("personnel", "1", "insert", {"name": "张三"})
        assert isinstance(result, int)
        assert result > 0

    def test_record_change_failure_returns_negative(self):
        with patch("app.db.xcmax_sync.SyncDb", side_effect=OSError("disk full")):
            result = record_change("personnel", "1", "insert", {})
        assert result == -1


class TestXcmaxSyncPushOutbox:
    def test_push_outbox_http_4xx_no_retry(self):
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "p", "entity_id": "1", "operation": "i", "payload": {}}
        ]
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db), patch(
            "app.services.xcmax_sync_service.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("url", 404, "Not Found", {}, None),
        ):
            result = push_outbox(remote_host="127.0.0.1", remote_port=9999)
        assert result["failed"] == 1
        mock_db.mark_outbox_failed.assert_called_once_with(1, "HTTP 404: Not Found", retry=False)

    def test_push_outbox_http_5xx_retries(self):
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 2, "entity_type": "p", "entity_id": "2", "operation": "i", "payload": {}}
        ]
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db), patch(
            "app.services.xcmax_sync_service.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("url", 503, "Busy", {}, None),
        ):
            result = push_outbox()
        assert result["failed"] == 1
        mock_db.mark_outbox_failed.assert_called_once_with(2, "HTTP 503: Busy", retry=True)


class TestXcmaxSyncApplyInbox:
    def test_apply_inbox_conflict(self, tmp_path: Path):
        db_path = tmp_path / "sync.db"
        from app.db.xcmax_sync import _ensure_schema

        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO sync_inbox (remote_cursor, entity_type, entity_id, operation, payload_json, origin_node, received_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "personnel", "1", "insert", "{}", "remote", datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        def bad_applier(item):
            raise RuntimeError("applier fail")

        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), patch(
            "app.db.xcmax_sync._db_path", None
        ):
            with patch.dict(_ENTITY_APPLIERS, {"personnel": bad_applier}, clear=False):
                result = apply_inbox()
        assert result["conflicts"] == 1
        assert result["errors"] == 1


class TestXcmaxSyncEntityAppliers:
    def test_apply_attendance_update_existing(self):
        applier = _ENTITY_APPLIERS.get("attendance")
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "id": 1,
                        "purchase_unit": "u",
                        "product_name": "p",
                        "status": "done",
                    },
                    "operation": "sync",
                }
            )
        assert obj.status == "done"

    def test_apply_attendance_insert_new(self):
        applier = _ENTITY_APPLIERS.get("attendance")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "purchase_unit": "u",
                        "product_name": "p",
                        "model_number": "m1",
                    },
                    "operation": "sync",
                }
            )
        mock_db.add.assert_called_once()

    def test_apply_attendance_missing_required_fields(self):
        applier = _ENTITY_APPLIERS.get("attendance")
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"purchase_unit": "u"}, "operation": "sync"})
        mock_db.add.assert_not_called()

    def test_apply_approval_delete(self):
        applier = _ENTITY_APPLIERS.get("approval")
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 5}, "operation": "delete"})
        mock_db.delete.assert_called_once_with(obj)

    def test_apply_model_config_no_user_id(self):
        applier = _ENTITY_APPLIERS.get("model_config")
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"llm_config": {}}, "operation": "sync"})
        mock_db.query.assert_not_called()

    def test_apply_model_config_db_error(self):
        applier = _ENTITY_APPLIERS.get("model_config")
        mock_db = MagicMock()
        mock_db.query.side_effect = OSError("db down")
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"user_id": 1, "llm_config": {}}, "operation": "sync"})

    def test_apply_im_message_update_existing(self):
        applier = _ENTITY_APPLIERS.get("im_message")
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        conv = MagicMock()
        mock_db.get.return_value = conv
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "id": 1,
                        "conversation_id": 2,
                        "body": "updated",
                        "sender_user_id": 3,
                    },
                    "operation": "insert",
                    "entity_id": "1",
                }
            )
        assert obj.body == "updated"

    def test_apply_im_message_insert_new(self):
        applier = _ENTITY_APPLIERS.get("im_message")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        conv = MagicMock()
        mock_db.get.return_value = conv
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "conversation_id": 2,
                        "body": "new",
                        "sender_user_id": 3,
                    },
                    "operation": "insert",
                }
            )
        mock_db.add.assert_called_once()

    def test_apply_im_read_state_equal_ms_lower_read_keeps_stored(self, tmp_path: Path):
        db_path = tmp_path / "sync.db"
        from app.db.xcmax_sync import _ensure_schema

        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        conn.close()
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), patch(
            "app.db.xcmax_sync._db_path", None
        ):
            from app.services.xcmax_sync_service import _write_sync_meta

            _write_sync_meta(
                "im_read_state:1:1",
                {"updated_at_ms": 1000, "last_read_message_id": 50},
            )

        applier = _ENTITY_APPLIERS.get("im_read_state")
        mock_db = MagicMock()
        member = MagicMock()
        member.last_read_message_id = 50
        mock_db.execute.return_value.scalar_one_or_none.return_value = member
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "conversation_id": 1,
                        "user_id": 1,
                        "last_read_message_id": 30,
                        "meta": {"updated_at_ms": 1000},
                    },
                    "entity_id": "1:1",
                }
            )
        # Equal timestamps and lower incoming read: keep existing stored value.
        assert member.last_read_message_id == 50

    def test_apply_ecosystem_db_error(self):
        applier = _ENTITY_APPLIERS.get("ecosystem")
        with patch(
            "app.db.xcmax_sync._resolve_db_path", side_effect=OSError("db down")
        ):
            applier({"payload": {"enabled": True}, "entity_id": "eco1", "operation": "sync"})

    def test_apply_print_job_success(self):
        applier = _ENTITY_APPLIERS.get("print_job")
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"template": "tpl1", "status": "done"},
                    "entity_id": "e1",
                    "operation": "sync",
                }
            )
        mock_db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 7. app/infrastructure/mods/mod_manager.py
# ---------------------------------------------------------------------------


class TestModManagerPureHelpers:
    def test_is_mods_disabled_boundary(self):
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "TRUE"}):
            assert is_mods_disabled() is True
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "false"}):
            assert is_mods_disabled() is False
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": ""}, clear=False):
            assert is_mods_disabled() is False

    def test_short_exc_message_with_class_name(self):
        assert _short_exc_message(ValueError()) == "ValueError"

    def test_short_exc_message_long_truncated(self):
        msg = "x" * 600
        result = _short_exc_message(RuntimeError(msg))
        assert len(result) == 480
        assert result.endswith("...")

    def test_backend_path_for_mod(self):
        assert _backend_path_for_mod("/mods/m1") == "/mods/m1/backend"

    def test_default_mods_root_from_env(self, tmp_path: Path):
        mods = tmp_path / "mods"
        mods.mkdir()
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": str(mods)}):
            assert _default_mods_root() == str(mods)

    def test_default_mods_root_env_missing_falls_back(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
        monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
        result = _default_mods_root()
        assert isinstance(result, str)

    def test_all_mods_roots_includes_env(self, tmp_path: Path):
        primary = tmp_path / "primary"
        primary.mkdir()
        env = tmp_path / "env"
        env.mkdir()
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": str(env)}):
            roots = _all_mods_roots(str(primary))
        assert str(primary) in roots
        assert str(env) in roots

    def test_all_mods_roots_empty_primary(self, tmp_path: Path):
        env = tmp_path / "env"
        env.mkdir()
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": str(env)}):
            roots = _all_mods_roots("")
        assert str(env) in roots


class TestModManagerInvokeInitHook:
    def test_no_params(self):
        calls = []

        def fn():
            calls.append("called")

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert calls == ["called"]

    def test_app_param_only(self):
        calls = []

        def fn(app):
            calls.append(app)

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert calls == [None]

    def test_mod_id_param_only(self):
        calls = []

        def fn(mod_id):
            calls.append(mod_id)

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert calls == ["m1"]

    def test_required_param_missing(self):
        calls = []

        def fn(required_arg):
            calls.append(required_arg)

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert calls == []

    def test_bind_failure_falls_back(self):
        calls = []

        def fn(app, extra):
            calls.append((app, extra))

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert calls == []

    def test_inspect_signature_error_falls_back_to_call(self):
        calls = []

        class BadCallable:
            def __call__(self):
                calls.append("x")

            def __signature__(self):
                raise TypeError("no signature")

        _invoke_mod_init_hook(BadCallable(), mod_id="m1")
        assert calls == ["x"]


class TestModManagerImportBackend:
    def test_import_backend_py_missing_file(self):
        with pytest.raises(FileNotFoundError):
            import_mod_backend_py("/no/such/mod", "m1", "blueprints")

    def test_import_backend_py_returns_existing_module(self, tmp_path: Path):
        mod_dir = tmp_path / "m1"
        backend = mod_dir / "backend"
        backend.mkdir(parents=True)
        (backend / "svc.py").write_text("x = 42\n")
        mod1 = import_mod_backend_py(str(mod_dir), "m1", "svc")
        mod2 = import_mod_backend_py(str(mod_dir), "m1", "svc")
        assert mod1 is mod2
        assert mod1.x == 42


class TestModManagerRegisterHooks:
    def test_register_hooks_no_hooks(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="m1", name="M", version="1", mod_path="/mods/m1")
        # Should not raise
        _register_mod_hooks("m1", meta)

    def test_register_hooks_invalid_spec(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="m1",
            name="M",
            version="1",
            mod_path="/mods/m1",
            hooks={"evt": "invalid_spec"},
        )
        with patch("app.infrastructure.mods.hooks.subscribe") as sub:
            _register_mod_hooks("m1", meta)
        sub.assert_not_called()


class TestModManagerInstanceMethods:
    def test_record_load_failure_truncates_message(self):
        mm = ModManager(mods_root="/tmp/test_mods")
        long_msg = "x" * 600
        mm._record_load_failure("m1", "backend", long_msg)
        assert len(mm._recent_load_failures[0]["message"]) <= 500

    def test_get_recent_load_failures_returns_copy(self):
        mm = ModManager(mods_root="/tmp/test_mods")
        mm._record_load_failure("m1", "s", "e")
        failures = mm.get_recent_load_failures()
        failures.append({"mod_id": "extra"})
        assert len(mm._recent_load_failures) == 1

    def test_resolve_mod_directory_empty(self):
        mm = ModManager(mods_root="/tmp/test_mods")
        assert mm.resolve_mod_directory("") is None

    def test_invalidate_scan_cache(self):
        mm = ModManager(mods_root="/tmp/test_mods")
        mm._scan_cache_fp = "fp"
        mm._scan_cache_mods = ["m1"]
        mm.invalidate_scan_cache()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []


# ---------------------------------------------------------------------------
# 8. app/mod_sdk/industry_seed.py
# ---------------------------------------------------------------------------


class TestIndustrySeedDedupe:
    def test_dedupe_removes_empty_and_duplicates(self):
        result = industry_seed_mod._dedupe(["a", "", "a", "b", "  "])
        assert result == ["a", "b"]

    def test_dedupe_empty_list(self):
        assert industry_seed_mod._dedupe([]) == []


class TestIndustryModIdFor:
    def test_empty_returns_none(self):
        assert industry_mod_id_for("") is None
        assert industry_mod_id_for(None) is None  # type: ignore[arg-type]

    def test_unknown_returns_none(self):
        assert industry_mod_id_for("not-an-industry") is None


class TestResolveIndustryOrModId:
    def test_empty_returns_none_none(self):
        assert resolve_industry_or_mod_id("") == (None, None)

    def test_known_industry(self):
        iid, mid = resolve_industry_or_mod_id("涂料")
        assert iid == "涂料"
        assert mid == "coating-industry"

    def test_known_mod_id(self):
        iid, mid = resolve_industry_or_mod_id("coating-industry")
        assert mid == "coating-industry"

    def test_unknown_returns_none_none(self):
        assert resolve_industry_or_mod_id("unknown") == (None, None)


class TestBundledIndustrySeedsDir:
    def test_env_dir(self, tmp_path: Path, monkeypatch):
        seeds = tmp_path / "seeds"
        seeds.mkdir()
        monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(seeds))
        assert bundled_industry_seeds_dir() == seeds

    def test_frozen_path(self, tmp_path: Path, monkeypatch):
        seeds = tmp_path / "industry-seeds"
        seeds.mkdir()
        monkeypatch.setattr(sys := __import__("sys"), "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        try:
            result = bundled_industry_seeds_dir()
        finally:
            monkeypatch.undo()
        assert result == seeds

    def test_cwd_path(self, tmp_path: Path, monkeypatch):
        seeds = tmp_path / "industry-seeds"
        seeds.mkdir()
        monkeypatch.chdir(tmp_path)
        assert bundled_industry_seeds_dir() == seeds


class TestDeactivateOtherOpenIndustryMods:
    def test_remove_files_false(self, tmp_path: Path, monkeypatch):
        keep = "coating-industry"
        other = "attendance-industry"
        mods_root_path = tmp_path / "mods"
        (mods_root_path / other).mkdir(parents=True)
        (mods_root_path / other / "manifest.json").write_text("{}")

        unloaded: list[str] = []

        class FakeMM:
            mods_root = str(mods_root_path)

            def unload_mod(self, mod_id: str) -> bool:
                unloaded.append(mod_id)
                return True

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        rows = deactivate_other_open_industry_mods(keep, remove_files=False)
        assert other in unloaded
        assert (mods_root_path / other).exists()
        assert any(r.get("removed_files") is False for r in rows)

    def test_unload_exception_continues(self, tmp_path: Path, monkeypatch):
        keep = "coating-industry"
        other = "attendance-industry"

        class FakeMM:
            mods_root = str(tmp_path)

            def unload_mod(self, mod_id: str) -> bool:
                raise RuntimeError("unload fail")

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        rows = deactivate_other_open_industry_mods(keep, remove_files=False)
        assert any(r.get("mod_id") == other for r in rows)


class TestSeedIndustryMod:
    def test_invalid_industry(self):
        result = seed_industry_mod("not-an-industry")
        assert result["success"] is False
        assert result["status"] == "invalid"

    def test_already_present_load_exception(self, tmp_path: Path, monkeypatch):
        mods_root_path = tmp_path / "mods"
        dst = mods_root_path / "coating-industry"
        dst.mkdir(parents=True)
        (dst / "manifest.json").write_text('{"id":"coating-industry"}')

        class FakeMM:
            mods_root = str(mods_root_path)

            def load_mod(self, mod_id: str) -> bool:
                raise RuntimeError("load fail")

            def unload_mod(self, mod_id: str) -> bool:
                return True

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        result = seed_industry_mod("涂料")
        assert result["success"] is True
        assert result["status"] == "already_present"
        assert result["loaded"] is False

    def test_pool_missing(self, tmp_path: Path, monkeypatch):
        mods_root_path = tmp_path / "mods"
        mods_root_path.mkdir()

        class FakeMM:
            mods_root = str(mods_root_path)

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        monkeypatch.setattr(industry_seed_mod, "bundled_industry_seeds_dir", lambda: None)
        result = seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "pool_missing"

    def test_not_in_pool(self, tmp_path: Path, monkeypatch):
        mods_root_path = tmp_path / "mods"
        mods_root_path.mkdir()
        pool = tmp_path / "industry-seeds"
        pool.mkdir()

        class FakeMM:
            mods_root = str(mods_root_path)

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
        result = seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "not_in_pool"

    def test_copy_error(self, tmp_path: Path, monkeypatch):
        mods_root_path = tmp_path / "mods"
        mods_root_path.mkdir()
        pool = tmp_path / "industry-seeds"
        src = pool / "coating-industry"
        src.mkdir(parents=True)
        (src / "manifest.json").write_text('{"id":"coating-industry"}')

        class FakeMM:
            mods_root = str(mods_root_path)

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))

        with patch("shutil.copytree", side_effect=OSError("copy fail")):
            result = seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "copy_error"

    def test_seeded_load_failed(self, tmp_path: Path, monkeypatch):
        mods_root_path = tmp_path / "mods"
        mods_root_path.mkdir()
        pool = tmp_path / "industry-seeds"
        src = pool / "coating-industry"
        src.mkdir(parents=True)
        (src / "manifest.json").write_text('{"id":"coating-industry"}')

        class FakeMM:
            mods_root = str(mods_root_path)

            def invalidate_scan_cache(self) -> None:
                pass

            def load_mod(self, mod_id: str) -> bool:
                return False

        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager", lambda: FakeMM()
        )
        monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
        result = seed_industry_mod("涂料")
        assert result["success"] is False
        assert result["status"] == "seeded_load_failed"


class TestInstallIndustrySeedWithFallback:
    @pytest.mark.asyncio
    async def test_success_from_seed(self, monkeypatch):
        monkeypatch.setattr(
            industry_seed_mod,
            "seed_industry_mod",
            lambda iid: {"success": True, "mod_id": "coating-industry"},
        )
        result = await install_industry_seed_with_fallback("涂料")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_catalog_install_success(self, monkeypatch):
        monkeypatch.setattr(
            industry_seed_mod,
            "seed_industry_mod",
            lambda iid: {
                "success": False,
                "mod_id": "coating-industry",
                "status": "not_in_pool",
            },
        )

        class FakeResult:
            success = True
            message = "installed"

        monkeypatch.setattr(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            AsyncMock(return_value=FakeResult()),
        )
        result = await install_industry_seed_with_fallback("涂料")
        assert result["success"] is True
        assert result["status"] == "catalog"

    @pytest.mark.asyncio
    async def test_catalog_install_failed(self, monkeypatch):
        monkeypatch.setattr(
            industry_seed_mod,
            "seed_industry_mod",
            lambda iid: {
                "success": False,
                "mod_id": "coating-industry",
                "status": "not_in_pool",
                "message": "pool miss",
            },
        )

        class FakeResult:
            success = False
            message = "catalog miss"

        monkeypatch.setattr(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            AsyncMock(return_value=FakeResult()),
        )
        result = await install_industry_seed_with_fallback("涂料")
        assert result["success"] is False
        assert result["status"] == "catalog_failed"

    @pytest.mark.asyncio
    async def test_catalog_exception(self, monkeypatch):
        monkeypatch.setattr(
            industry_seed_mod,
            "seed_industry_mod",
            lambda iid: {
                "success": False,
                "mod_id": "coating-industry",
                "status": "pool_missing",
            },
        )
        monkeypatch.setattr(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            AsyncMock(side_effect=RuntimeError("net down")),
        )
        result = await install_industry_seed_with_fallback("涂料")
        assert result["success"] is False
        assert result["status"] == "catalog_failed"
