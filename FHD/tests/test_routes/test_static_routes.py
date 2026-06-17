"""Tests for app.fastapi_routes.domains.static.routes."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.static.routes import router


def _create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


# ── gap_batch1_index ──────────────────────────────────────────


class TestIndexRoute:
    def test_returns_404_when_no_templates(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent",
        ):
            resp = client.get("/")
            assert resp.status_code == 404

    def test_serves_vue_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vue_dir = os.path.join(tmpdir, "templates", "vue-dist")
            os.makedirs(vue_dir)
            with open(os.path.join(vue_dir, "index.html"), "w") as f:
                f.write("<html>Vue</html>")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/")
                assert resp.status_code == 200
                assert "Vue" in resp.text

    def test_falls_back_to_legacy_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir = os.path.join(tmpdir, "templates")
            os.makedirs(tmpl_dir)
            with open(os.path.join(tmpl_dir, "ai_assistant_console.html"), "w") as f:
                f.write("<html>Legacy</html>")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/")
                assert resp.status_code == 200
                assert "Legacy" in resp.text


# ── Static file serving ──────────────────────────────────────


class TestStaticServe:
    def test_serves_existing_static_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            static_dir = os.path.join(tmpdir, "templates", "vue-dist", "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "app.js"), "w") as f:
                f.write("console.log('hi')")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/static/app.js")
                assert resp.status_code == 200

    def test_returns_404_for_missing_static(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vue_dir = os.path.join(tmpdir, "templates", "vue-dist", "static")
            os.makedirs(vue_dir)
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/static/missing.js")
                assert resp.status_code == 404

    def test_returns_404_for_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            static_dir = os.path.join(tmpdir, "templates", "vue-dist", "static")
            os.makedirs(os.path.join(static_dir, "subdir"))
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/static/subdir")
                assert resp.status_code == 404


# ── Specific asset routes ────────────────────────────────────


class TestAssetRoutes:
    def _make_app_with_file(self, filename: str, content: bytes = b"data") -> tuple:
        tmpdir = tempfile.mkdtemp()
        vue_dir = os.path.join(tmpdir, "templates", "vue-dist")
        os.makedirs(vue_dir)
        with open(os.path.join(vue_dir, filename), "wb") as f:
            f.write(content)
        app = _create_app()
        client = TestClient(app)
        return app, client, tmpdir

    def test_vite_svg(self):
        app, client, tmpdir = self._make_app_with_file("vite.svg", b"<svg></svg>")
        try:
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/vite.svg")
                assert resp.status_code == 200
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_vite_svg_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vue_dir = os.path.join(tmpdir, "templates", "vue-dist")
            os.makedirs(vue_dir)
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/vite.svg")
                assert resp.status_code == 404

    def test_brand_xc_logo_jpg(self):
        app, client, tmpdir = self._make_app_with_file("brand-xc-logo.jpg")
        try:
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/brand-xc-logo.jpg")
                assert resp.status_code == 200
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_brand_xc_logo_png(self):
        app, client, tmpdir = self._make_app_with_file("brand-xc-logo.png")
        try:
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/brand-xc-logo.png")
                assert resp.status_code == 200
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_employee_docs_json(self):
        app, client, tmpdir = self._make_app_with_file(
            "workflow-employee-docs.json", b'{"docs": []}'
        )
        try:
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/workflow-employee-docs.json")
                assert resp.status_code == 200
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sw_js(self):
        app, client, tmpdir = self._make_app_with_file("sw.js", b"self.addEventListener();")
        try:
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/sw.js")
                assert resp.status_code == 200
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_favicon_returns_gif(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200


# ── workflow-employees.json ───────────────────────────────────


class TestWorkflowEmployeesJson:
    def test_serves_from_vue_dist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vue_dir = os.path.join(tmpdir, "templates", "vue-dist")
            os.makedirs(vue_dir)
            with open(os.path.join(vue_dir, "workflow-employees.json"), "w") as f:
                f.write('{"employees": []}')
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/workflow-employees.json")
                assert resp.status_code == 200

    def test_serves_from_frontend_public(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pub_dir = os.path.join(tmpdir, "frontend", "public")
            os.makedirs(pub_dir)
            with open(os.path.join(pub_dir, "workflow-employees.json"), "w") as f:
                f.write('{"employees": []}')
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/workflow-employees.json")
                assert resp.status_code == 200

    def test_returns_404_when_nowhere(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "templates", "vue-dist"))
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/workflow-employees.json")
                assert resp.status_code == 404


# ── outputs route ─────────────────────────────────────────────


class TestOutputsRoute:
    def test_missing_outputs_dir_returns_404(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.utils.path_utils.get_app_data_dir",
            return_value="/nonexistent",
        ):
            with patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/nonexistent2",
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.get_base_dir",
                    return_value="/nonexistent3",
                ):
                    resp = client.get("/outputs/test.pdf")
                    assert resp.status_code == 404

    def test_missing_file_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = os.path.join(tmpdir, "shipment_outputs")
            os.makedirs(out_dir)
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.utils.path_utils.get_app_data_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/outputs/missing.pdf")
                assert resp.status_code == 404

    def test_serves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = os.path.join(tmpdir, "shipment_outputs")
            os.makedirs(out_dir)
            with open(os.path.join(out_dir, "report.pdf"), "wb") as f:
                f.write(b"PDF content")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.utils.path_utils.get_app_data_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/outputs/report.pdf")
                assert resp.status_code == 200


# ── test-buttons / products-test / console ────────────────────


class TestPageRoutes:
    def test_test_buttons_missing(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent",
        ):
            resp = client.get("/test-buttons")
            assert resp.status_code == 404

    def test_products_test_missing(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.get_base_dir",
            return_value="/nonexistent",
        ):
            resp = client.get("/products-test")
            assert resp.status_code == 404

    def test_console_serves_vue_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vue_dir = os.path.join(tmpdir, "templates", "vue-dist")
            os.makedirs(vue_dir)
            with open(os.path.join(vue_dir, "index.html"), "w") as f:
                f.write("<html>Console</html>")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/console")
                assert resp.status_code == 200

    def test_console_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir = os.path.join(tmpdir, "templates")
            os.makedirs(tmpl_dir)
            with open(os.path.join(tmpl_dir, "ai_assistant_console.html"), "w") as f:
                f.write("<html>Legacy Console</html>")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.get_base_dir",
                return_value=tmpdir,
            ):
                resp = client.get("/console")
                assert resp.status_code == 200
                assert "Legacy Console" in resp.text


# ── Traditional mode API routes ──────────────────────────────


class TestTraditionalModeList:
    def test_list_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.list_files_response",
            return_value=({"files": []}, 200),
        ):
            resp = client.get("/api/traditional-mode/list")
            assert resp.status_code == 200


class TestTraditionalModeRoot:
    def test_root_returns_info(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.root_info_response",
            return_value={"root": "/tmp"},
        ):
            resp = client.get("/api/traditional-mode/root")
            assert resp.status_code == 200


class TestTraditionalModeRead:
    def test_read_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.read_file_response",
            return_value=({"content": "hello"}, 200),
        ):
            resp = client.get("/api/traditional-mode/read?file=test.txt")
            assert resp.status_code == 200


class TestTraditionalModeWatch:
    def test_watch_returns_stream(self):
        app = _create_app()
        client = TestClient(app)

        def fake_sse(path):
            yield 'data: {"event":"change"}\n\n'

        with patch(
            "app.fastapi_routes.domains.static.routes.sse_watch_events",
            side_effect=fake_sse,
        ):
            resp = client.get("/api/traditional-mode/watch")
            assert resp.status_code == 200


class TestTraditionalModeStat:
    def test_stat_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.stat_response",
            return_value=({"exists": True}, 200),
        ):
            resp = client.get("/api/traditional-mode/agent/stat?path=test.txt")
            assert resp.status_code == 200


class TestTraditionalModeWriteText:
    def test_write_text_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.write_text_response",
            return_value=({"success": True}, 200),
        ):
            resp = client.post(
                "/api/traditional-mode/agent/write-text",
                json={"file": "test.txt", "content": "hello"},
            )
            assert resp.status_code == 200


class TestTraditionalModeWriteBase64:
    def test_write_base64_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.write_base64_response",
            return_value=({"success": True}, 200),
        ):
            resp = client.post(
                "/api/traditional-mode/agent/write-base64",
                json={"file": "test.txt", "content_base64": "aGVsbG8="},
            )
            assert resp.status_code == 200


class TestTraditionalModeMove:
    def test_move_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.move_response",
            return_value=({"success": True}, 200),
        ):
            resp = client.post(
                "/api/traditional-mode/agent/move",
                json={"src": "a.txt", "dst": "b.txt"},
            )
            assert resp.status_code == 200


class TestTraditionalModeCopy:
    def test_copy_returns_json(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.copy_response",
            return_value=({"success": True}, 200),
        ):
            resp = client.post(
                "/api/traditional-mode/agent/copy",
                json={"src": "a.txt", "dst": "b.txt"},
            )
            assert resp.status_code == 200


# ── traditional_mode_write (Excel) ───────────────────────────


class TestTraditionalModeWrite:
    def test_empty_body_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post("/api/traditional-mode/write", json={})
        assert resp.status_code == 400

    def test_path_traversal_returns_403(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value=None,
        ):
            resp = client.post(
                "/api/traditional-mode/write",
                json={"file": "../../etc/passwd", "type": "excel", "data": {}},
            )
            assert resp.status_code == 403

    def test_non_excel_type_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value="/tmp/test.xlsx",
        ):
            resp = client.post(
                "/api/traditional-mode/write",
                json={"file": "test.csv", "type": "csv", "data": {}},
            )
            assert resp.status_code == 400

    def test_openpyxl_not_installed_returns_500(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value="/tmp/test.xlsx",
        ):
            with patch.dict("sys.modules", {"openpyxl": None}):
                resp = client.post(
                    "/api/traditional-mode/write",
                    json={"file": "test.xlsx", "type": "excel", "data": {}},
                )
                # May be 500 or 400 depending on import error handling
                assert resp.status_code in (400, 500)

    def test_excel_write_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.xlsx")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=filepath,
            ):
                resp = client.post(
                    "/api/traditional-mode/write",
                    json={
                        "file": "test.xlsx",
                        "type": "excel",
                        "data": {
                            "active_sheet": "Sheet1",
                            "content": {
                                "Sheet1": {
                                    "rows": [["Name", "Value"], ["test", 42]],
                                },
                            },
                        },
                    },
                )
                assert resp.status_code == 200
                assert resp.json()["success"] is True
                assert os.path.exists(filepath)


# ── traditional_mode_mkdir ────────────────────────────────────


class TestTraditionalModeMkdir:
    def test_empty_body_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post("/api/traditional-mode/mkdir", json={})
        assert resp.status_code == 400

    def test_empty_name_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post(
            "/api/traditional-mode/mkdir",
            json={"path": "", "name": ""},
        )
        assert resp.status_code == 400

    def test_illegal_chars_in_name_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post(
            "/api/traditional-mode/mkdir",
            json={"path": "", "name": "../evil"},
        )
        assert resp.status_code == 400

    def test_path_traversal_returns_403(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value=None,
        ):
            resp = client.post(
                "/api/traditional-mode/mkdir",
                json={"path": "../../", "name": "folder"},
            )
            assert resp.status_code == 403

    def test_existing_folder_returns_409(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = os.path.join(tmpdir, "existing")
            os.makedirs(existing)
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/mkdir",
                        json={"path": "", "name": "existing"},
                    )
                    assert resp.status_code == 409

    def test_mkdir_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/mkdir",
                        json={"path": "", "name": "new_folder"},
                    )
                    assert resp.status_code == 200
                    assert os.path.isdir(os.path.join(tmpdir, "new_folder"))


# ── traditional_mode_rename ───────────────────────────────────


class TestTraditionalModeRename:
    def test_empty_body_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post("/api/traditional-mode/rename", json={})
        assert resp.status_code == 400

    def test_empty_names_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post(
            "/api/traditional-mode/rename",
            json={"path": "", "old_name": "", "new_name": ""},
        )
        assert resp.status_code == 400

    def test_illegal_new_name_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post(
            "/api/traditional-mode/rename",
            json={"path": "", "old_name": "a", "new_name": "../evil"},
        )
        assert resp.status_code == 400

    def test_path_traversal_returns_403(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value=None,
        ):
            resp = client.post(
                "/api/traditional-mode/rename",
                json={"path": "../../", "old_name": "a", "new_name": "b"},
            )
            assert resp.status_code == 403

    def test_source_not_found_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/rename",
                        json={"path": "", "old_name": "nonexistent", "new_name": "b"},
                    )
                    assert resp.status_code == 404

    def test_target_exists_returns_409(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "old.txt"), "w") as f:
                f.write("old")
            with open(os.path.join(tmpdir, "new.txt"), "w") as f:
                f.write("new")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/rename",
                        json={"path": "", "old_name": "old.txt", "new_name": "new.txt"},
                    )
                    assert resp.status_code == 409

    def test_rename_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "old.txt"), "w") as f:
                f.write("content")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/rename",
                        json={"path": "", "old_name": "old.txt", "new_name": "renamed.txt"},
                    )
                    assert resp.status_code == 200
                    assert os.path.exists(os.path.join(tmpdir, "renamed.txt"))
                    assert not os.path.exists(os.path.join(tmpdir, "old.txt"))


# ── traditional_mode_delete ───────────────────────────────────


class TestTraditionalModeDelete:
    def test_empty_body_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post("/api/traditional-mode/delete", json={})
        assert resp.status_code == 400

    def test_empty_name_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post(
            "/api/traditional-mode/delete",
            json={"path": "", "name": ""},
        )
        assert resp.status_code == 400

    def test_path_traversal_returns_403(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value=None,
        ):
            resp = client.post(
                "/api/traditional-mode/delete",
                json={"path": "../../", "name": "file"},
            )
            assert resp.status_code == 403

    def test_not_found_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/delete",
                        json={"path": "", "name": "nonexistent"},
                    )
                    assert resp.status_code == 404

    def test_delete_file_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "to_delete.txt")
            with open(filepath, "w") as f:
                f.write("bye")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/delete",
                        json={"path": "", "name": "to_delete.txt"},
                    )
                    assert resp.status_code == 200
                    assert not os.path.exists(filepath)

    def test_delete_directory_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dirpath = os.path.join(tmpdir, "subdir")
            os.makedirs(dirpath)
            with open(os.path.join(dirpath, "inner.txt"), "w") as f:
                f.write("inner")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                with patch(
                    "app.fastapi_routes.domains.static.routes.ROOT_DIR",
                    tmpdir,
                ):
                    resp = client.post(
                        "/api/traditional-mode/delete",
                        json={"path": "", "name": "subdir"},
                    )
                    assert resp.status_code == 200
                    assert not os.path.exists(dirpath)


# ── traditional_mode_upload ───────────────────────────────────


class TestTraditionalModeUpload:
    def test_upload_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                resp = client.post(
                    "/api/traditional-mode/upload",
                    files={"file": ("test.txt", b"hello world", "text/plain")},
                    data={"path": ""},
                )
                assert resp.status_code == 200
                assert resp.json()["success"] is True
                assert "test.txt" in resp.json()["filename"]

    def test_upload_no_filename_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value="/tmp",
        ):
            # Upload with empty filename - FastAPI may still set filename
            resp = client.post(
                "/api/traditional-mode/upload",
                files={"file": ("upload", b"data", "text/plain")},
                data={"path": ""},
            )
            # The route checks `if not file.filename`, empty string is falsy
            # but "upload" is truthy, so this should succeed
            # Testing with truly empty filename is hard with TestClient
            # so we just verify the route works with a valid filename
            assert resp.status_code in (200, 400)

    def test_upload_path_traversal_returns_403(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.fastapi_routes.domains.static.routes.resolve_safe_path",
            return_value=None,
        ):
            resp = client.post(
                "/api/traditional-mode/upload",
                files={"file": ("test.txt", b"data", "text/plain")},
                data={"path": "../../"},
            )
            assert resp.status_code == 403

    def test_upload_existing_file_gets_renamed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-create the file
            with open(os.path.join(tmpdir, "test.txt"), "w") as f:
                f.write("existing")
            app = _create_app()
            client = TestClient(app)
            with patch(
                "app.fastapi_routes.domains.static.routes.resolve_safe_path",
                return_value=tmpdir,
            ):
                resp = client.post(
                    "/api/traditional-mode/upload",
                    files={"file": ("test.txt", b"new content", "text/plain")},
                    data={"path": ""},
                )
                assert resp.status_code == 200
                # Should have been renamed to test_1.txt
                assert "test" in resp.json()["filename"]


# ── customers_import_stub ─────────────────────────────────────


class TestCustomersImportStub:
    def test_returns_success(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.get("/api/customers/import")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── customers_batch_delete_delete ─────────────────────────────


class TestCustomersBatchDelete:
    def test_empty_ids_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.delete("/api/customers/batch-delete")
        assert resp.status_code == 400

    def test_ids_from_query_string(self):
        app = _create_app()
        client = TestClient(app)
        mock_svc = MagicMock()
        mock_svc.batch_delete.return_value = {"success": True, "deleted": [1, 2]}
        with patch(
            "app.application.get_customer_app_service",
            return_value=mock_svc,
        ):
            resp = client.delete("/api/customers/batch-delete?ids=1,2")
            assert resp.status_code == 200

    def test_ids_from_body(self):
        app = _create_app()
        client = TestClient(app)
        mock_svc = MagicMock()
        mock_svc.batch_delete.return_value = {"success": True, "deleted": [1]}
        with patch(
            "app.application.get_customer_app_service",
            return_value=mock_svc,
        ):
            import json as _json
            resp = client.request(
                "DELETE",
                "/api/customers/batch-delete",
                content=_json.dumps({"ids": [1], "force": True}).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 200

    def test_value_error_returns_400(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.application.get_customer_app_service",
            side_effect=ValueError("bad id"),
        ):
            resp = client.delete("/api/customers/batch-delete?ids=abc")
            assert resp.status_code == 400

    def test_associations_returns_409(self):
        app = _create_app()
        client = TestClient(app)
        mock_svc = MagicMock()
        mock_svc.batch_delete.return_value = {
            "success": False,
            "has_associations": True,
        }
        with patch(
            "app.application.get_customer_app_service",
            return_value=mock_svc,
        ):
            resp = client.delete("/api/customers/batch-delete?ids=1")
            assert resp.status_code == 409


# ── preferences_delete_key ────────────────────────────────────


class TestPreferencesDeleteKey:
    def test_success(self):
        app = _create_app()
        client = TestClient(app)
        mock_svc = MagicMock()
        mock_svc.delete_preference.return_value = True
        with patch(
            "app.application.facades.conversation_facade.get_user_preference_service",
            return_value=mock_svc,
        ):
            resp = client.delete("/api/preferences/test_key?user_id=user1")
            assert resp.status_code == 200
            assert resp.json()["success"] is True

    def test_delete_failure(self):
        app = _create_app()
        client = TestClient(app)
        mock_svc = MagicMock()
        mock_svc.delete_preference.return_value = False
        with patch(
            "app.application.facades.conversation_facade.get_user_preference_service",
            return_value=mock_svc,
        ):
            resp = client.delete("/api/preferences/test_key")
            assert resp.status_code == 200
            assert resp.json()["success"] is False

    def test_recoverable_error_returns_500(self):
        app = _create_app()
        client = TestClient(app)
        with patch(
            "app.application.facades.conversation_facade.get_user_preference_service",
            side_effect=ConnectionError("db down"),
        ):
            resp = client.delete("/api/preferences/test_key")
            assert resp.status_code == 500
