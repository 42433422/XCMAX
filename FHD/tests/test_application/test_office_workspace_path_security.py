from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.application import attendance_import_app_service as attendance_service
from app.application.office_parse_app_service import (
    read_workspace_output_files,
    run_office_read_employee,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(root))
    return root


def test_attendance_import_reads_nested_input_and_writes_only_fixed_database(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = workspace / "uploads" / "nested" / "attendance.xlsx"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"test workbook placeholder")
    monkeypatch.setattr(
        attendance_service,
        "_parse_workbook",
        lambda _path: ([], [], "mingxi"),
    )

    result = attendance_service.import_attendance_workbook("uploads/nested/attendance.xlsx")

    expected_db = workspace / attendance_service.ATTENDANCE_DB_RELPATH
    assert expected_db.is_file()
    assert result["db_path"] == str(expected_db)
    assert result["workbook_kind"] == "mingxi"


@pytest.mark.parametrize(
    "untrusted",
    [
        "../../outside.xlsx",
        "%252e%252e%252foutside.xlsx",
        "uploads/%252e%252e/%252e%252e/outside.xlsx",
    ],
)
def test_attendance_import_rejects_traversal_and_double_encoding(
    workspace: Path,
    untrusted: str,
) -> None:
    with pytest.raises(HTTPException) as caught:
        attendance_service.import_attendance_workbook(untrusted)
    assert caught.value.status_code == 400
    assert not (workspace / attendance_service.ATTENDANCE_DB_RELPATH).exists()


def test_attendance_import_rejects_symlinked_input(
    workspace: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"outside")
    link = workspace / "attendance.xlsx"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(HTTPException) as caught:
        attendance_service.import_attendance_workbook("attendance.xlsx")
    assert caught.value.status_code == 400


def test_office_output_reader_reads_valid_nested_text_and_json(workspace: Path) -> None:
    nested = workspace / "outputs" / "nested"
    nested.mkdir(parents=True)
    (nested / "result.txt").write_text("done", encoding="utf-8")
    (nested / "result.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    files = read_workspace_output_files(["outputs/nested/result.txt", "outputs/nested/result.json"])

    assert files == [
        {"path": "outputs/nested/result.txt", "kind": "text", "text": "done"},
        {
            "path": "outputs/nested/result.json",
            "kind": "json",
            "json": {"ok": True},
        },
    ]


@pytest.mark.parametrize(
    "untrusted",
    ["../outside.txt", "%252e%252e%252foutside.txt"],
)
def test_office_output_reader_rejects_traversal_and_double_encoding(
    workspace: Path,
    untrusted: str,
) -> None:
    assert read_workspace_output_files([untrusted]) == [
        {"path": untrusted, "kind": "text", "error": "invalid_path"}
    ]


def test_office_output_reader_rejects_symlink_escape(
    workspace: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "output.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert read_workspace_output_files(["output.txt"]) == [
        {"path": "output.txt", "kind": "text", "error": "invalid_path"}
    ]


@pytest.mark.asyncio
async def test_office_employee_receives_only_server_root_and_confined_relative_paths(
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = workspace / "uploads" / "nested" / "source.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"document")
    mod_path = tmp_path / "trusted-mod"
    mod_path.mkdir()
    captured: dict = {}

    async def dispatch(_a, _b, _c, payload):
        captured.update(payload)
        return {"data": {"ok": True}}

    manager = SimpleNamespace(
        get_mod_metadata=lambda _mod_id: SimpleNamespace(mod_path=str(mod_path))
    )
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: manager)
    monkeypatch.setattr(
        "app.mod_sdk.mods_bus.import_mod_backend_py",
        lambda *_args: SimpleNamespace(_dispatch_run=dispatch),
    )

    result = await run_office_read_employee(
        "word-full-read-employee",
        file_path="uploads/nested/source.docx",
        workspace_root=str(tmp_path / "attacker-root"),
        output_relpath="outputs/nested/result.json",
    )

    assert result == {"ok": True}
    assert captured == {
        "file_path": "uploads/nested/source.docx",
        "workspace_root": str(workspace),
        "action": "convert",
        "output_relpath": "outputs/nested/result.json",
    }


@pytest.mark.asyncio
async def test_office_employee_rejects_double_encoded_input_before_mod_dispatch(
    workspace: Path,
    tmp_path: Path,
) -> None:
    with pytest.raises(HTTPException) as caught:
        await run_office_read_employee(
            "word-full-read-employee",
            file_path="%252e%252e%252fsecret.docx",
            workspace_root=str(tmp_path / "attacker-root"),
        )
    assert caught.value.status_code == 400
