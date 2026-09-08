# mypy: disable-error-code="attr-defined"
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.legacy.routes import taiyangniao_attendance_compat as tac
from app.legacy.routes.taiyangniao_attendance_compat import (
    DEFAULT_TEMPLATE_RELPATH,
    router,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_app() -> FastAPI:
    app = FastAPI()
    # 本文件测试授权后的转换行为；拒绝路径由 test_customer_features 单独覆盖。
    app.dependency_overrides[tac.require_attendance_conversion] = lambda: None
    app.include_router(router)
    return app


def _setup_workspace(tmp_path: Path, monkeypatch, *, with_template: bool = True) -> Path:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    if with_template:
        tpl = tmp_path / DEFAULT_TEMPLATE_RELPATH
        tpl.parent.mkdir(parents=True, exist_ok=True)
        tpl.write_bytes(b"PK\x03\x04-template")
    return tmp_path


def _xlsx_upload(name: str = "attendance.xlsx", payload: bytes = b"PK\x03\x04-data"):
    return {"file": (name, BytesIO(payload), XLSX_MIME)}


def _fake_convert(result: dict, captured: list | None = None):
    def _convert(src, out, **kwargs):
        if captured is not None:
            captured.append({"src": src, "out": out, **kwargs})
        return result

    return _convert


def _ok_result(**overrides):
    result = {
        "success": True,
        "rows_in": 12,
        "rows_stats": 10,
        "rows_used_for_template": 10,
        "personnel_roster_count": 2,
        "month": "2026-03",
        "employees_total": 5,
        "employees_matched": 4,
        "unmatched_names": ["张三"],
        "header_info": {"row": 0},
        "used_llm": False,
        "output_sheet_names": ["明细"],
        "input": "in.xlsx",
        "output": "out.xlsx",
    }
    result.update(overrides)
    return result


def test_attendance_rules_host_route() -> None:
    app = _make_app()

    with TestClient(app) as client:
        response = client.get("/api/mod/taiyangniao-pro/attendance/rules")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["config"]["default_template_relpath"] == DEFAULT_TEMPLATE_RELPATH
    assert body["data"]["schedule_groups"]


def test_attendance_download_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "424").mkdir()
    app = _make_app()

    with TestClient(app) as client:
        response = client.get(
            "/api/mod/taiyangniao-pro/attendance/download",
            params={"relpath": "424/does-not-exist.xlsx"},
        )

    assert response.status_code == 404
    assert response.json()["success"] is False


def test_attendance_convert_upload_rejects_bad_extension() -> None:
    app = _make_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/mod/taiyangniao-pro/attendance/convert-upload",
            files={"file": ("notes.txt", BytesIO(b"hello"), "text/plain")},
        )

    assert response.status_code == 400
    assert "unsupported" in response.json()["error"]


def test_attendance_convert_upload_rejects_wrong_template(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    app = _make_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/mod/taiyangniao-pro/attendance/convert-upload",
            data={"template_relpath": "wrong/template.xlsx"},
            files={
                "file": (
                    "attendance.xlsx",
                    BytesIO(b"PK\x03\x04"),
                    XLSX_MIME,
                )
            },
        )

    assert response.status_code == 400
    assert "固定模板" in response.json()["error"]


# ---------------------------------------------------------------------------
# convert-upload: happy path
# ---------------------------------------------------------------------------


class TestConvertUploadHappyPath:
    def test_success_without_roster(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        captured: list = []
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result(), captured),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["rows_in"] == 12
        assert data["rows_stats"] == 10
        assert data["month"] == "2026-03"
        assert data["template_relpath"] == DEFAULT_TEMPLATE_RELPATH
        assert data["output_relpath"].startswith("424/attendance-output-")
        assert data["unmatched_names"] == ["张三"]
        assert data["output_sheet_names"] == ["明细"]
        assert data["used_llm"] is False
        # convert 被真实调用，上传文件确实落盘
        assert len(captured) == 1
        assert captured[0]["personnel_roster"] is None
        assert Path(captured[0]["src"]).exists()

    def test_success_with_personnel_roster(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        roster = [("生产部", "全职", "张三"), ("质检部", "兼职", "李四")]
        monkeypatch.setattr(tac, "_load_products_personnel_roster_from_host", lambda: roster)
        captured: list = []
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result(), captured),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "1"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert captured[0]["personnel_roster"] == roster

    def test_month_header_row_llm_passthrough(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        captured: list = []
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result(used_llm=True), captured),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={
                    "use_personnel_roster": "0",
                    "month": "2026-05",
                    "header_row": "-3",
                    "use_llm": "true",
                },
                files=_xlsx_upload(),
            )

        assert response.status_code == 200
        data = response.json()["data"]
        # header_row 负数被钳制为 0；month 优先取 result 中的值
        assert data["header_row"] == 0
        assert data["used_llm"] is True
        kwargs = captured[0]
        assert kwargs["header_row"] == 0
        assert kwargs["month"] == "2026-05"
        assert kwargs["use_llm"] is True

    def test_month_falls_back_to_form_value(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result(month=None)),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0", "month": "2026-06"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 200
        assert response.json()["data"]["month"] == "2026-06"

    @pytest.mark.parametrize("suffix", [".xlsm", ".xls"])
    def test_legacy_excel_extensions_accepted(self, tmp_path, monkeypatch, suffix) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result()),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(name=f"attendance{suffix}"),
            )

        assert response.status_code == 200
        assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# convert-upload: failure branches
# ---------------------------------------------------------------------------


class TestConvertUploadFailures:
    def test_roster_requested_but_empty_returns_400(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(tac, "_load_products_personnel_roster_from_host", lambda: [])
        monkeypatch.setattr(tac, "_load_products_personnel_roster", lambda _p: [])
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "1"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert "人员管理" in response.json()["error"]

    def test_convert_raises_recoverable_returns_500(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)

        def _boom(*_a, **_k):
            raise RuntimeError("engine exploded")

        monkeypatch.setattr(tac, "_load_convert_attendance_file", lambda: _boom)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 500
        assert response.json()["error"] == "convert failed"

    def test_convert_returns_failure_returns_400(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert({"success": False, "error": "表头识别失败"}),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert "表头识别失败" in response.json()["error"]

    def test_zero_rows_returns_422_with_header_info(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(
                _ok_result(rows_in=0, rows_stats=0, header_info={"candidates": [1, 2]})
            ),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 422
        body = response.json()
        assert body["success"] is False
        assert "每日统计" in body["error"]
        assert body["data"]["rows_in"] == 0
        assert body["data"]["header_info"] == {"candidates": [1, 2]}

    def test_missing_template_returns_400(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch, with_template=False)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert "模板" in response.json()["error"]

    def test_template_resolved_but_not_exists_returns_400(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        ghost = tmp_path / "ghost.xlsx"
        monkeypatch.setattr(tac, "resolve_existing_workspace_file", lambda _rel: ghost)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert "模板文件不存在" in response.json()["error"]

    def test_template_resolved_but_directory_returns_400(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(tac, "resolve_existing_workspace_file", lambda _rel: tmp_path)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert "模板路径不是文件" in response.json()["error"]

    def test_bad_header_row_rejected_by_validation(self, tmp_path, monkeypatch) -> None:
        """header_row 声明为 int Form 参数，非数字在 FastAPI 校验层即 422。"""
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result()),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0", "header_row": "abc"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# download endpoint
# ---------------------------------------------------------------------------


class TestAttendanceDownload:
    def test_download_success(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "424" / "out.xlsx"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"PK\x03\x04-result")
        app = _make_app()

        with TestClient(app) as client:
            response = client.get(
                "/api/mod/taiyangniao-pro/attendance/download",
                params={"relpath": "424/out.xlsx"},
            )

        assert response.status_code == 200
        assert response.content == b"PK\x03\x04-result"

    def test_download_empty_relpath_returns_400(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        app = _make_app()

        with TestClient(app) as client:
            response = client.get(
                "/api/mod/taiyangniao-pro/attendance/download",
                params={"relpath": ""},
            )

        assert response.status_code == 400
        assert "missing relpath" in response.json()["error"]

    def test_download_traversal_returns_400(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        app = _make_app()

        with TestClient(app) as client:
            response = client.get(
                "/api/mod/taiyangniao-pro/attendance/download",
                params={"relpath": "../secret.txt"},
            )

        assert response.status_code == 400

    def test_download_directory_returns_404(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "424").mkdir()
        app = _make_app()

        with TestClient(app) as client:
            response = client.get(
                "/api/mod/taiyangniao-pro/attendance/download",
                params={"relpath": "424"},
            )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# helper unit tests
# ---------------------------------------------------------------------------


class TestNormalizeRelpath:
    def test_empty_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing relpath"):
            tac._normalize_relpath("", field_name="relpath")

    def test_whitespace_only_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing tpl"):
            tac._normalize_relpath("   ", field_name="tpl")

    def test_backslashes_and_leading_slash_normalized(self) -> None:
        assert tac._normalize_relpath("\\424\\a.xlsx", field_name="r") == "424/a.xlsx"
        assert tac._normalize_relpath("/424/a.xlsx", field_name="r") == "424/a.xlsx"

    def test_percent_encoding_decoded(self) -> None:
        assert tac._normalize_relpath("424/my%20file.xlsx", field_name="r") == "424/my file.xlsx"


class TestLoadProductsPersonnelRoster:
    def _make_db(self, path: Path, rows: list[tuple]) -> None:
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT, specification TEXT, name TEXT)"
        )
        conn.executemany("INSERT INTO products (unit, specification, name) VALUES (?,?,?)", rows)
        conn.commit()
        conn.close()

    def test_missing_db_returns_empty(self, tmp_path) -> None:
        assert tac._load_products_personnel_roster(tmp_path / "nope.db") == []

    def test_dedupes_and_skips_empty_names(self, tmp_path) -> None:
        db = tmp_path / "mod.db"
        self._make_db(
            db,
            [
                ("生产部", "全职", "张三"),
                ("生产部", "全职", "张三"),
                ("x", "y", "   "),
                (None, None, "李四"),
            ],
        )
        roster = tac._load_products_personnel_roster(db)
        assert roster == [("生产部", "全职", "张三"), ("", "", "李四")]

    def test_sqlite_error_returns_empty(self, tmp_path) -> None:
        db = tmp_path / "broken.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other (id INTEGER)")
        conn.commit()
        conn.close()
        assert tac._load_products_personnel_roster(db) == []


class TestResolvePersonnelRoster:
    def test_host_roster_preferred(self, monkeypatch) -> None:
        host = [("a", "b", "c")]
        monkeypatch.setattr(tac, "_load_products_personnel_roster_from_host", lambda: host)

        def _should_not_call(_p):
            raise AssertionError("sqlite fallback must not be called")

        monkeypatch.setattr(tac, "_load_products_personnel_roster", _should_not_call)
        assert tac._resolve_personnel_roster() == host

    def test_falls_back_to_mod_sqlite(self, monkeypatch, tmp_path) -> None:
        fallback = [("d", "e", "f")]
        monkeypatch.setattr(tac, "_load_products_personnel_roster_from_host", lambda: [])
        monkeypatch.setattr(tac, "_load_products_personnel_roster", lambda _p: fallback)
        assert tac._resolve_personnel_roster() == fallback


class TestCandidateModRoots:
    def test_env_roots_included(self, tmp_path, monkeypatch) -> None:
        mods = tmp_path / "m1"
        data = tmp_path / "data"
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(mods))
        monkeypatch.setenv("XCAGI_DATA_DIR", str(data))
        roots = tac._candidate_mod_roots()
        assert mods.resolve() in roots
        assert (data / "mods").resolve() in roots

    def test_empty_env_skipped(self, monkeypatch) -> None:
        monkeypatch.setenv("XCAGI_MODS_ROOT", "")
        monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
        monkeypatch.delenv("XCAGI_BUNDLED_MODS_DIR", raising=False)
        roots = tac._candidate_mod_roots()
        assert all(str(r).strip() for r in roots)


class TestEnsureSunbirdBackendOnPath:
    def test_found_inserts_sys_path(self, tmp_path, monkeypatch) -> None:
        backend = tmp_path / "taiyangniao-pro" / "backend"
        pkg = backend / "attendance_engine"
        pkg.mkdir(parents=True)
        (pkg / "convert.py").write_text("# stub", encoding="utf-8")
        monkeypatch.setattr(tac, "_candidate_mod_roots", lambda: [tmp_path])
        try:
            found = tac._ensure_sunbird_backend_on_path()
            assert found == backend
            assert str(backend) in sys.path
        finally:
            if str(backend) in sys.path:
                sys.path.remove(str(backend))

    def test_not_found_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(tac, "_candidate_mod_roots", lambda: [tmp_path])
        assert tac._ensure_sunbird_backend_on_path() is None


class TestLoadConvertAttendanceFile:
    def test_loads_callable_from_fake_backend(self, tmp_path, monkeypatch) -> None:
        backend = tmp_path / "taiyangniao-pro" / "backend"
        pkg = backend / "attendance_engine"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "convert.py").write_text(
            "def convert_attendance_file(*a, **k):\n    return {'success': True}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(tac, "_candidate_mod_roots", lambda: [tmp_path])
        monkeypatch.delitem(sys.modules, "attendance_engine.convert", raising=False)
        monkeypatch.delitem(sys.modules, "attendance_engine", raising=False)
        try:
            fn = tac._load_convert_attendance_file()
            assert callable(fn)
            assert fn() == {"success": True}
        finally:
            if str(backend) in sys.path:
                sys.path.remove(str(backend))

    def test_non_callable_raises_runtime_error(self, tmp_path, monkeypatch) -> None:
        backend = tmp_path / "taiyangniao-pro" / "backend"
        pkg = backend / "attendance_engine"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "convert.py").write_text("convert_attendance_file = 123\n", encoding="utf-8")
        monkeypatch.setattr(tac, "_candidate_mod_roots", lambda: [tmp_path])
        monkeypatch.delitem(sys.modules, "attendance_engine.convert", raising=False)
        monkeypatch.delitem(sys.modules, "attendance_engine", raising=False)
        try:
            with pytest.raises(RuntimeError, match="不可用"):
                tac._load_convert_attendance_file()
        finally:
            if str(backend) in sys.path:
                sys.path.remove(str(backend))


# ---------------------------------------------------------------------------
# round 2: remaining branch gaps
# ---------------------------------------------------------------------------


class TestConvertUploadEdgeBranches:
    def test_empty_template_relpath_skips_fixed_check(self, tmp_path, monkeypatch) -> None:
        """template_relpath 全空白 → 跳过固定模板校验，直接用默认模板。"""
        _setup_workspace(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tac,
            "_load_convert_attendance_file",
            lambda: _fake_convert(_ok_result()),
        )
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0", "template_relpath": "   "},
                files=_xlsx_upload(),
            )

        assert response.status_code == 200
        assert response.json()["data"]["template_relpath"] == DEFAULT_TEMPLATE_RELPATH

    def test_root_only_template_relpath_returns_400(self, tmp_path, monkeypatch) -> None:
        """template_relpath="/" → normalize 后为空 → 400 missing template_relpath。"""
        _setup_workspace(tmp_path, monkeypatch)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0", "template_relpath": "/"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert "missing template_relpath" in response.json()["error"]

    def test_save_upload_failure_returns_500(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)

        def _boom(_kind):
            raise OSError("disk full")

        monkeypatch.setattr(tac, "allocate_generated_workspace_file", _boom)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 500
        assert response.json()["error"] == "save upload failed"

    def test_output_allocation_failure_returns_400(self, tmp_path, monkeypatch) -> None:
        _setup_workspace(tmp_path, monkeypatch)
        real_allocate = tac.allocate_generated_workspace_file
        calls = {"n": 0}

        def _allocate(kind):
            calls["n"] += 1
            if calls["n"] == 1:
                return real_allocate(kind)
            raise OSError("no space")

        monkeypatch.setattr(tac, "allocate_generated_workspace_file", _allocate)
        app = _make_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files=_xlsx_upload(),
            )

        assert response.status_code == 400
        assert response.json()["error"] == "输出路径无效"

    def test_missing_filename_returns_400(self, tmp_path, monkeypatch) -> None:
        """filename="" 需原始 multipart 才能送达（httpx files= 会丢弃空文件名）。"""
        _setup_workspace(tmp_path, monkeypatch)
        app = _make_app()
        boundary = "XCBOUNDARY"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename=""\r\n'
            f"Content-Type: {XLSX_MIME}\r\n\r\n"
            "PK\x03\x04\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        with TestClient(app) as client:
            response = client.post(
                "/api/mod/taiyangniao-pro/attendance/convert-upload",
                content=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        assert response.status_code == 400
        assert "missing file name" in response.json()["error"]


class TestDownloadEdgeBranches:
    def test_resolve_raises_unexpected_recoverable_returns_400(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

        def _boom(_rel):
            raise OSError("io boom")

        monkeypatch.setattr(tac, "resolve_existing_workspace_file", _boom)
        app = _make_app()

        with TestClient(app) as client:
            response = client.get(
                "/api/mod/taiyangniao-pro/attendance/download",
                params={"relpath": "424/out.xlsx"},
            )

        assert response.status_code == 400
        assert response.json()["error"] == "下载路径无效"

    def test_resolved_but_vanished_returns_404(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        ghost = tmp_path / "424" / "gone.xlsx"
        monkeypatch.setattr(tac, "resolve_existing_workspace_file", lambda _rel: ghost)
        app = _make_app()

        with TestClient(app) as client:
            response = client.get(
                "/api/mod/taiyangniao-pro/attendance/download",
                params={"relpath": "424/gone.xlsx"},
            )

        assert response.status_code == 404


class TestLoadProductsPersonnelRosterFromHost:
    def _fake_get_db(self, products):
        @contextmanager
        def _ctx():
            query = SimpleNamespace(
                filter=lambda *_a, **_k: query,
                order_by=lambda *_a, **_k: products,
            )
            db = SimpleNamespace(query=lambda _model: query)
            yield db

        return _ctx

    def test_import_failure_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "app.db.models.product", None)
        assert tac._load_products_personnel_roster_from_host() == []

    def test_loads_and_dedupes(self, monkeypatch) -> None:
        import app.db.session as db_session

        products = [
            SimpleNamespace(name="张三", unit="生产部", specification="全职"),
            SimpleNamespace(name="张三", unit="生产部", specification="全职"),
            SimpleNamespace(name="  ", unit="x", specification="y"),
            SimpleNamespace(name="李四", unit=None, specification=None),
        ]
        monkeypatch.setattr(db_session, "get_db", self._fake_get_db(products))
        roster = tac._load_products_personnel_roster_from_host()
        assert roster == [("生产部", "全职", "张三"), ("", "", "李四")]

    def test_db_error_returns_empty(self, monkeypatch) -> None:
        import app.db.session as db_session

        @contextmanager
        def _ctx():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(db_session, "get_db", _ctx)
        assert tac._load_products_personnel_roster_from_host() == []


class TestCandidateModRootsExtra:
    def test_registry_and_manager_roots(self, tmp_path, monkeypatch) -> None:
        import app.infrastructure.mods.mod_manager as mm
        import app.infrastructure.mods.registry as reg

        meta_path = tmp_path / "reg-root" / "taiyangniao-pro"
        resolved = tmp_path / "mgr-root" / "taiyangniao-pro"
        monkeypatch.setattr(
            reg,
            "get_mod_registry",
            lambda: SimpleNamespace(
                get_mod_metadata=lambda _mid: SimpleNamespace(mod_path=str(meta_path))
            ),
        )
        monkeypatch.setattr(
            mm,
            "get_mod_manager",
            lambda: SimpleNamespace(resolve_mod_directory=lambda _mid: str(resolved)),
        )
        roots = tac._candidate_mod_roots()
        assert (tmp_path / "reg-root").resolve() in roots
        assert (tmp_path / "mgr-root").resolve() in roots

    def test_registry_failure_swallowed(self, monkeypatch) -> None:
        import app.infrastructure.mods.registry as reg

        def _boom():
            raise RuntimeError("registry broken")

        monkeypatch.setattr(reg, "get_mod_registry", _boom)
        # 不抛异常即通过
        assert isinstance(tac._candidate_mod_roots(), list)

    def test_desktop_data_dir_failure_swallowed(self, monkeypatch) -> None:
        import app.desktop_runtime.paths as desktop_paths

        def _boom():
            raise OSError("no desktop dir")

        monkeypatch.setattr(desktop_paths, "get_desktop_data_dir", _boom)
        assert isinstance(tac._candidate_mod_roots(), list)

    def test_manager_resolve_none_skipped(self, tmp_path, monkeypatch) -> None:
        """registry 有 mod_path 但 manager resolve 返回 None → 只加 registry 根。"""
        import app.infrastructure.mods.mod_manager as mm
        import app.infrastructure.mods.registry as reg

        meta_path = tmp_path / "reg-root" / "taiyangniao-pro"
        monkeypatch.setattr(
            reg,
            "get_mod_registry",
            lambda: SimpleNamespace(
                get_mod_metadata=lambda _mid: SimpleNamespace(mod_path=str(meta_path))
            ),
        )
        monkeypatch.setattr(
            mm,
            "get_mod_manager",
            lambda: SimpleNamespace(resolve_mod_directory=lambda _mid: None),
        )
        roots = tac._candidate_mod_roots()
        assert (tmp_path / "reg-root").resolve() in roots

    def test_unresolvable_env_path_swallowed(self, monkeypatch) -> None:
        """add() 内 Path 解析抛 OSError → 静默跳过（防御分支）。"""
        real_path = tac.Path

        def _path(raw, *args, **kwargs):
            if raw == "BOOM":
                raise OSError("bad path")
            return real_path(raw, *args, **kwargs)

        _path.cwd = real_path.cwd
        monkeypatch.setattr(tac, "Path", _path)
        monkeypatch.setenv("XCAGI_MODS_ROOT", "BOOM")
        assert isinstance(tac._candidate_mod_roots(), list)


class TestEnsureSunbirdBackendOnPathExtra:
    def test_second_call_does_not_duplicate_sys_path(self, tmp_path, monkeypatch) -> None:
        backend = tmp_path / "taiyangniao-pro" / "backend"
        pkg = backend / "attendance_engine"
        pkg.mkdir(parents=True)
        (pkg / "convert.py").write_text("# stub", encoding="utf-8")
        monkeypatch.setattr(tac, "_candidate_mod_roots", lambda: [tmp_path])
        try:
            tac._ensure_sunbird_backend_on_path()
            tac._ensure_sunbird_backend_on_path()
            assert sys.path.count(str(backend)) == 1
        finally:
            while str(backend) in sys.path:
                sys.path.remove(str(backend))
