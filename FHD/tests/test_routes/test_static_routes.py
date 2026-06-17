"""static/routes 路由测试 — 覆盖 SPA 首页、静态资源、传统模式文件操作、mkdir/rename/delete 等。"""

from __future__ import annotations

import base64
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.static import routes as static_routes


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(static_routes.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# SPA 首页 / 静态资源 — 使用 mock get_base_dir 使模板目录不存在
# ---------------------------------------------------------------------------


class TestIndex:
    def test_no_templates(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/")
            assert r.status_code == 404


class TestFavicon:
    def test_returns_gif(self, client: TestClient):
        r = client.get("/favicon.ico")
        assert r.status_code == 200
        expected = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
        assert r.content == expected


class TestServeStatic:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/static/css/app.css")
            assert r.status_code == 404


class TestViteSvg:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/vite.svg")
            assert r.status_code == 404


class TestBrandXcLogoJpg:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/brand-xc-logo.jpg")
            assert r.status_code == 404


class TestBrandXcLogoPng:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/brand-xc-logo.png")
            assert r.status_code == 404


class TestWorkflowEmployeeDocsJson:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/workflow-employee-docs.json")
            assert r.status_code == 404


class TestSwJs:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/sw.js")
            assert r.status_code == 404


class TestWorkflowEmployeesJson:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/workflow-employees.json")
            assert r.status_code == 404


class TestTestButtons:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/test-buttons")
            assert r.status_code == 404


class TestProductsTest:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/products-test")
            assert r.status_code == 404


class TestConsole:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/console")
            assert r.status_code == 404


class TestOutputs:
    def test_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent_xcmax_test",
        ):
            r = client.get("/outputs/test.txt")
            assert r.status_code in (404, 500)


# ---------------------------------------------------------------------------
# 传统模式文件操作
# ---------------------------------------------------------------------------


class TestTraditionalModeWrite:
    def test_empty_body(self, client: TestClient):
        r = client.post("/api/traditional-mode/write", json={})
        assert r.status_code in (400, 403)

    def test_unsupported_type(self, client: TestClient, tmp_path):
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value=str(tmp_path / "test.txt"),
        ):
            r = client.post(
                "/api/traditional-mode/write",
                json={"file": "test.txt", "type": "text", "data": {}},
            )
            assert r.status_code == 400

    def test_path_traversal_rejected(self, client: TestClient):
        with patch("app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=None):
            r = client.post(
                "/api/traditional-mode/write",
                json={"file": "../../etc/passwd", "type": "excel", "data": {}},
            )
            assert r.status_code == 403


class TestTraditionalModeMkdir:
    def test_empty_body(self, client: TestClient):
        r = client.post("/api/traditional-mode/mkdir", json={})
        assert r.status_code == 400

    def test_empty_name(self, client: TestClient, tmp_path):
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=str(tmp_path)
        ):
            r = client.post("/api/traditional-mode/mkdir", json={"path": "", "name": ""})
            assert r.status_code == 400

    def test_illegal_chars_in_name(self, client: TestClient, tmp_path):
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=str(tmp_path)
        ):
            r = client.post("/api/traditional-mode/mkdir", json={"path": "", "name": "a/b"})
            assert r.status_code == 400

    def test_path_traversal_rejected(self, client: TestClient):
        with patch("app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=None):
            r = client.post("/api/traditional-mode/mkdir", json={"path": "", "name": "folder"})
            assert r.status_code == 403


class TestTraditionalModeRename:
    def test_empty_body(self, client: TestClient):
        r = client.post("/api/traditional-mode/rename", json={})
        assert r.status_code == 400

    def test_empty_names(self, client: TestClient, tmp_path):
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=str(tmp_path)
        ):
            r = client.post(
                "/api/traditional-mode/rename", json={"path": "", "old_name": "", "new_name": ""}
            )
            assert r.status_code == 400

    def test_illegal_new_name(self, client: TestClient, tmp_path):
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=str(tmp_path)
        ):
            r = client.post(
                "/api/traditional-mode/rename",
                json={"path": "", "old_name": "a", "new_name": "b/c"},
            )
            assert r.status_code == 400


class TestTraditionalModeDelete:
    def test_empty_body(self, client: TestClient):
        r = client.post("/api/traditional-mode/delete", json={})
        assert r.status_code == 400

    def test_empty_name(self, client: TestClient, tmp_path):
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path", return_value=str(tmp_path)
        ):
            r = client.post("/api/traditional-mode/delete", json={"path": "", "name": ""})
            assert r.status_code == 400


class TestCustomersImportStub:
    def test_returns_message(self, client: TestClient):
        r = client.get("/api/customers/import")
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestCustomersBatchDelete:
    def test_empty_ids(self, client: TestClient):
        r = client.delete("/api/customers/batch-delete")
        assert r.status_code == 400

    def test_with_ids_query(self, client: TestClient):
        with patch("app.application.get_customer_app_service") as mock_svc:
            mock_svc.return_value.batch_delete.return_value = {"success": True, "deleted": [1, 2]}
            r = client.delete("/api/customers/batch-delete?ids=1,2")
            assert r.status_code == 200

    def test_with_body_ids(self, client: TestClient):
        with patch("app.application.get_customer_app_service") as mock_svc:
            mock_svc.return_value.batch_delete.return_value = {"success": True, "deleted": [1]}
            r = client.request(
                "DELETE", "/api/customers/batch-delete", json={"ids": [1], "force": False}
            )
            assert r.status_code == 200

    def test_invalid_id_format(self, client: TestClient):
        r = client.delete("/api/customers/batch-delete?ids=abc")
        assert r.status_code == 400


class TestPreferencesDeleteKey:
    def test_success(self, client: TestClient):
        with patch(
            "app.application.facades.conversation_facade.get_user_preference_service"
        ) as mock_svc:
            mock_svc.return_value.delete_preference.return_value = True
            r = client.delete("/api/preferences/test_key")
            assert r.json()["success"] is True

    def test_failure(self, client: TestClient):
        with patch(
            "app.application.facades.conversation_facade.get_user_preference_service"
        ) as mock_svc:
            mock_svc.return_value.delete_preference.return_value = False
            r = client.delete("/api/preferences/test_key")
            assert r.json()["success"] is False

    def test_exception(self, client: TestClient):
        with patch(
            "app.application.facades.conversation_facade.get_user_preference_service"
        ) as mock_svc:
            mock_svc.return_value.delete_preference.side_effect = Exception("DB error")
            r = client.delete("/api/preferences/test_key")
            assert r.status_code == 500
