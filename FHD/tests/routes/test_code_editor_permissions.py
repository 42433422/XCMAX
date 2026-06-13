"""Tests for app.fastapi_routes.code_editor — coverage ramp C3.3-a.

Covers the workspace code-editor endpoints:
* ``_safe_rel_path`` rejects traversal and escape.
* ``_unified_diff`` produces diff.
* ``/status`` returns phase.
* ``/analyze`` noop / text preview.
* ``/edit`` existing file / new file / directory / not found.
* ``/diff/<id>`` unknown id.
* ``/apply/<id>`` requires p2.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import code_editor
from app.fastapi_routes.code_editor import router


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestSafePath:
    def test_traversal_rejected(self) -> None:
        with (
            patch.object(
                code_editor, "_workspace_root", return_value=Path("/tmp/workspace").resolve()
            ),
            pytest.raises(Exception) as ei,
        ):
            code_editor._safe_rel_path("../etc/passwd")
        assert "400" in str(ei.value) or "invalid" in str(ei.value).lower()

    def test_escape_rejected(self) -> None:
        # Use an absolute target that is outside the workspace root.
        with (
            patch.object(code_editor, "_workspace_root", return_value=Path("/tmp/ws_a").resolve()),
            patch("pathlib.Path.resolve", return_value=Path("/tmp/ws_b/file.py")),
        ):
            with pytest.raises(Exception):
                code_editor._safe_rel_path("file.py")

    def test_empty_path_rejected(self) -> None:
        with (
            patch.object(
                code_editor, "_workspace_root", return_value=Path("/tmp/workspace").resolve()
            ),
            pytest.raises(Exception),
        ):
            code_editor._safe_rel_path("   ")


class TestUnifiedDiff:
    def test_produces_diff(self) -> None:
        out = code_editor._unified_diff("a\nb\n", "a\nc\n", "x.txt")
        assert "x.txt" in out
        assert "-b" in out or "b" in out
        assert "+c" in out or "c" in out


class TestStatus:
    def test_returns_phase(self, client: TestClient) -> None:
        r = client.get("/api/code-editor/status")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["phase"] == "edit_diff_apply"


class TestAnalyze:
    def test_no_path_returns_noop(self, client: TestClient) -> None:
        r = client.post("/api/code-editor/analyze", json={"path": None})
        assert r.status_code == 200
        assert r.json()["kind"] == "noop"

    def test_missing_file_returns_noop(self, client: TestClient, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post("/api/code-editor/analyze", json={"path": "nope.py"})
        assert r.status_code == 200
        assert r.json()["kind"] == "noop"

    def test_existing_file_returns_preview(self, client: TestClient, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("print('hi')")
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post("/api/code-editor/analyze", json={"path": "x.py"})
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "text_preview"
        assert "print" in data["preview"]


class TestEdit:
    def test_edit_existing_file(self, client: TestClient, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("a")
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post("/api/code-editor/edit", json={"path": "x.py", "new_content": "b"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "edit_" in data["edit_id"]
        assert data["is_new_file"] is False

    def test_edit_path_is_directory(self, client: TestClient, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post("/api/code-editor/edit", json={"path": "sub", "new_content": "x"})
        assert r.status_code == 404
        assert "directory" in r.json()["detail"].lower()

    def test_edit_create_with_bad_ext(self, client: TestClient, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post(
                "/api/code-editor/edit",
                json={"path": "x.exe", "new_content": "x", "create_if_missing": True},
            )
        assert r.status_code == 400
        assert "extension" in r.json()["detail"].lower()

    def test_edit_create_new_file(self, client: TestClient, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post(
                "/api/code-editor/edit",
                json={"path": "x.py", "new_content": "y", "create_if_missing": True},
            )
        assert r.status_code == 200
        assert r.json()["is_new_file"] is True

    def test_edit_not_found_no_create(self, client: TestClient, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r = client.post(
                "/api/code-editor/edit", json={"path": "missing.py", "new_content": "x"}
            )
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()


class TestDiff:
    def test_unknown_edit_id(self, client: TestClient) -> None:
        r = client.get("/api/code-editor/diff/does-not-exist")
        assert r.status_code == 404

    def test_known_edit_id(self, client: TestClient, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("a")
        with patch.dict("os.environ", {"WORKSPACE_ROOT": str(tmp_path)}):
            r1 = client.post("/api/code-editor/edit", json={"path": "x.py", "new_content": "b"})
            edit_id = r1.json()["edit_id"]
            r2 = client.get(f"/api/code-editor/diff/{edit_id}")
        assert r2.status_code == 200
        assert "x.py" in r2.json()["unified_diff"]


class TestApply:
    def test_unknown_edit_id_404(self, client: TestClient) -> None:
        # apply 需 p2 授权才能进入 edit_id 校验；授权后未知 edit_id 应 404
        with (
            patch("app.fastapi_routes.code_editor.resolve_ai_tier", return_value="p2"),
            patch(
                "app.fastapi_routes.code_editor.assert_p2_elevated_claim_or_raise",
                return_value=None,
            ),
        ):
            r = client.post("/api/code-editor/apply/nonexistent")
        assert r.status_code == 404
