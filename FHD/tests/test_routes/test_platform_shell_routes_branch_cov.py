"""platform_shell_routes 异常/空列表分支。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes import platform_shell_routes as ps


@pytest.mark.asyncio
async def test_capabilities_list_mods_failure():
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ),
        patch.object(ps, "RECOVERABLE_ERRORS", (RuntimeError,)),
        patch(
            "app.mod_sdk.platform_shell.build_platform_shell_payload",
            return_value={"ok": True},
        ) as build,
    ):
        out = await ps.platform_shell_capabilities()
    assert out["success"] is True
    build.assert_called_once_with([])


@pytest.mark.asyncio
async def test_decoupling_progress_list_mods_failure():
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ),
        patch.object(ps, "RECOVERABLE_ERRORS", (RuntimeError,)),
        patch(
            "app.mod_sdk.decoupling_progress.build_decoupling_progress_payload",
            return_value={"ok": True},
        ) as build,
    ):
        out = await ps.decoupling_progress()
    assert out["success"] is True
    build.assert_called_once_with([])


@pytest.mark.asyncio
async def test_deliverable_status_uses_request_app():
    req = MagicMock()
    req.app = MagicMock(name="app")
    with patch(
        "app.mod_sdk.deliverable_status.build_deliverable_status",
        return_value={"deliverable": True},
    ) as build:
        out = await ps.platform_shell_deliverable_status(req)
    assert out["data"]["deliverable"] is True
    build.assert_called_once_with(app=req.app)


@pytest.mark.asyncio
async def test_employee_ssot_installed_failure():
    with (
        patch(
            "app.application.ops_closure_status._installed_employee_pack_ids",
            side_effect=RuntimeError("x"),
        ),
        patch.object(ps, "RECOVERABLE_ERRORS", (RuntimeError,)),
        patch(
            "app.mod_sdk.employee_ssot.derive_employee_ssot",
            return_value={"admin": {}},
        ) as derive,
    ):
        out = await ps.platform_shell_employee_ssot()
    assert out["success"] is True
    derive.assert_called_once_with(installed_ids=set())


@pytest.mark.asyncio
async def test_capabilities_with_mods():
    mm = MagicMock()
    mm.list_all_mods.return_value = [{"id": "a"}, {"id": ""}, {"id": "b"}]
    with (
        patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        patch(
            "app.mod_sdk.platform_shell.build_platform_shell_payload",
            return_value={"mods": 2},
        ) as build,
    ):
        out = await ps.platform_shell_capabilities()
    assert out["success"] is True
    build.assert_called_once_with(["a", "b"])


@pytest.mark.asyncio
async def test_office_confirm_knowledge_empty_400():
    from fastapi import HTTPException

    body = ps.OfficeConfirmBody(intent="knowledge_only", knowledge_text="  ")
    with pytest.raises(HTTPException) as exc:
        await ps.platform_shell_office_confirm(body, MagicMock())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_office_confirm_knowledge_ok():
    body = ps.OfficeConfirmBody(
        intent="knowledge_only",
        knowledge_text="hello",
        source_name="t",
    )
    rag = MagicMock()
    rag.ingest_document.return_value = {"id": "doc1"}
    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=rag,
    ):
        out = await ps.platform_shell_office_confirm(body, MagicMock())
    assert out["success"] is True
    rag.ingest_document.assert_called_once()


@pytest.mark.asyncio
async def test_office_confirm_attendance_missing_file():
    from fastapi import HTTPException

    body = ps.OfficeConfirmBody(intent="attendance", file_path="")
    with pytest.raises(HTTPException) as exc:
        await ps.platform_shell_office_confirm(body, MagicMock())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_office_confirm_attendance_ok(tmp_path):
    body = ps.OfficeConfirmBody(
        intent="attendance",
        file_path="uploads/a.xlsx",
        workspace_root=str(tmp_path),
        source_name="a.xlsx",
    )
    with (
        patch(
            "app.mod_sdk.workspace.resolve_safe_workspace_relpath",
            return_value=tmp_path / "uploads" / "a.xlsx",
        ),
        patch(
            "app.application.attendance_import_app_service.import_attendance_workbook",
            return_value={"rows": 1},
        ) as imp,
    ):
        out = await ps.platform_shell_office_confirm(body, MagicMock())
    assert out["success"] is True
    assert out["data"]["rows"] == 1
    imp.assert_called_once()


@pytest.mark.asyncio
async def test_office_confirm_erp_and_bad_intent():
    from fastapi import HTTPException

    erp = await ps.platform_shell_office_confirm(
        ps.OfficeConfirmBody(intent="erp_products", file_path="x.xlsx"),
        MagicMock(),
    )
    assert erp["success"] is True
    assert erp["data"]["intent"] == "erp_products"
    with pytest.raises(HTTPException) as exc:
        await ps.platform_shell_office_confirm(
            ps.OfficeConfirmBody(intent="unknown"),
            MagicMock(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_save_workspace_upload_bad_and_ok(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    bad = UploadFile(filename="x.exe", file=MagicMock())
    bad.file.read = MagicMock(return_value=b"bin")
    with pytest.raises(HTTPException) as exc:
        await ps._save_workspace_upload(bad, subdir="tutorial")
    assert exc.value.status_code == 400

    class _Mem:
        def __init__(self, data: bytes):
            self._data = data

        async def read(self):
            return self._data

    good = UploadFile(filename="sheet.xlsx", file=_Mem(b"xlsx-bytes"))
    # UploadFile.read is async via SpooledTemporaryFile; override
    good.read = _Mem(b"xlsx-bytes").read  # type: ignore[method-assign]
    out = await ps._save_workspace_upload(good, subdir="tutorial")
    assert out["filename"] == "sheet.xlsx"
    assert out["file_path"].startswith("uploads/tutorial/")


@pytest.mark.asyncio
async def test_save_workspace_upload_suffix_and_rel_fallback(tmp_path, monkeypatch):
    """secure_filename drops suffix → re-append; relative_to ValueError → abs path."""
    from starlette.datastructures import UploadFile

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    class _Mem:
        def __init__(self, data: bytes):
            self._data = data

        async def read(self):
            return self._data

    good = UploadFile(filename="sheet.xlsx", file=_Mem(b"xlsx"))
    good.read = _Mem(b"xlsx").read  # type: ignore[method-assign]
    with patch(
        "app.utils.secure_filename.secure_filename",
        return_value="sheet",  # no .xlsx → triggers suffix re-append
    ):
        out = await ps._save_workspace_upload(good, subdir="tutorial")
    assert ".xlsx" in out["file_path"]

    good2 = UploadFile(filename="sheet.xlsx", file=_Mem(b"xlsx"))
    good2.read = _Mem(b"xlsx").read  # type: ignore[method-assign]

    def _rel_fail(self, *a, **k):
        raise ValueError("not relative")

    with patch.object(Path, "relative_to", _rel_fail):
        out2 = await ps._save_workspace_upload(good2, subdir="tutorial")
    assert out2["file_path"]  # absolute fallback


@pytest.mark.asyncio
async def test_workspace_read_files(monkeypatch):
    with patch(
        "app.application.office_parse_app_service.read_workspace_output_files",
        return_value=[{"path": "a.xlsx", "ok": True}],
    ):
        out = await ps.platform_shell_workspace_read_files(
            ps.WorkspaceReadFilesBody(workspace_root="/tmp", file_paths=["a.xlsx"])
        )
    assert out["success"] is True
    assert out["data"]["files"][0]["path"] == "a.xlsx"


@pytest.mark.asyncio
async def test_workspace_root_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    out = await ps.platform_shell_workspace_root()
    assert out["success"] is True
    assert Path(out["data"]["workspace_root"]) == tmp_path.resolve()


@pytest.mark.asyncio
async def test_chat_office_upload_ok_with_session():
    from io import BytesIO

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(ps.router)
    client = TestClient(app, raise_server_exceptions=False)
    user = MagicMock(id=1, is_active=True)
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch(
            "app.fastapi_routes.platform_shell_routes._save_workspace_upload",
            return_value={"file_path": "uploads/chat/x.xlsx"},
        ),
    ):
        resp = client.post(
            "/api/platform-shell/chat-office-file-upload",
            files={"file": ("chat.xlsx", BytesIO(b"x"), "application/octet-stream")},
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_decoupling_progress_skips_empty_mod_id():
    mgr = MagicMock()
    mgr.list_all_mods.return_value = [{"id": ""}, {"id": "  "}, {"id": "mod-a"}]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mgr,
        ),
        patch(
            "app.mod_sdk.decoupling_progress.build_decoupling_progress_payload",
            return_value={"ok": True},
        ) as build,
    ):
        out = await ps.decoupling_progress()
    assert out["success"] is True
    build.assert_called_once_with(["mod-a"])


@pytest.mark.asyncio
async def test_onboarding_seed_auth_and_tenant():
    from fastapi import HTTPException

    req = MagicMock()
    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            await ps.platform_shell_onboarding_seed_demo(ps.OnboardingSeedBody(), req)
    assert exc.value.status_code == 401

    user = MagicMock(tenant_id=None)
    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ),
        patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ),
        patch(
            "app.application.session_account_meta.enrich_session_meta_with_tenant",
            return_value={},
        ),
    ):
        with pytest.raises(HTTPException) as exc2:
            await ps.platform_shell_onboarding_seed_demo(ps.OnboardingSeedBody(), req)
    assert exc2.value.status_code == 400

    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=MagicMock(tenant_id=9),
        ),
        patch(
            "app.application.onboarding_seed_app_service.seed_onboarding_demo_data",
            return_value={"seeded": True},
        ),
    ):
        out = await ps.platform_shell_onboarding_seed_demo(ps.OnboardingSeedBody(), req)
    assert out["data"]["seeded"] is True


@pytest.mark.asyncio
async def test_permission_matrix_401_and_ok():
    from fastapi import HTTPException

    req = MagicMock()
    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            await ps.platform_shell_permission_matrix(req)
    assert exc.value.status_code == 401

    user = MagicMock(tier="personal")
    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ),
        patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ),
        patch(
            "app.application.session_account_meta.enrich_session_meta_with_tenant",
            return_value={"account_kind": "enterprise"},
        ),
        patch(
            "app.application.auth_permission_resolver.resolve_permissions",
            return_value={"can_admin": False},
        ) as rp,
    ):
        out = await ps.platform_shell_permission_matrix(req)
    assert out["success"] is True
    rp.assert_called_once()


@pytest.mark.asyncio
async def test_office_sample_cleanup_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    tutorial = tmp_path / "uploads" / "tutorial"
    tutorial.mkdir(parents=True)
    keep = tutorial / "a.xlsx"
    keep.write_bytes(b"1")
    outside = tmp_path / "uploads" / "other.xlsx"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"2")

    body = ps.OfficeSampleCleanupBody(
        file_paths=[
            "uploads/tutorial/a.xlsx",
            "uploads/other.xlsx",
            "",
            "uploads/tutorial/missing.xlsx",
        ]
    )
    out = await ps.platform_shell_office_sample_cleanup(body)
    assert "uploads/tutorial/a.xlsx" in out["data"]["removed"]
    assert not keep.exists()
    assert outside.exists()

    # unlink OSError still returns 200
    keep2 = tutorial / "b.xlsx"
    keep2.write_bytes(b"3")
    with patch("pathlib.Path.unlink", side_effect=OSError("busy")):
        out2 = await ps.platform_shell_office_sample_cleanup(
            ps.OfficeSampleCleanupBody(file_paths=["uploads/tutorial/b.xlsx"])
        )
    assert out2["success"] is True
