"""Employee file writes expose a diff and a reversible snapshot."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.mod_sdk.employee_tools import write_preview as preview
from app.mod_sdk.employee_tools.workspace import write_file


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    yield


def test_write_returns_diff_and_undo_restores_original(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("第一行\n旧内容\n", encoding="utf-8")
    ctx = {"workspace_root": str(tmp_path)}

    result = run(write_file(None, {"confirm": True, "path": "notes.md", "content": "第一行\n新内容\n"}, ctx))
    assert result["ok"] is True
    assert result["snapshot_id"]
    assert any(line.startswith("-旧内容") for line in result["diff"])
    assert any(line.startswith("+新内容") for line in result["diff"])
    assert target.read_text(encoding="utf-8") == "第一行\n新内容\n"

    undo = run(
        write_file(
            None,
            {"confirm": True, "path": "notes.md", "undo_snapshot_id": result["snapshot_id"]},
            ctx,
        )
    )
    assert undo["ok"] is True
    assert target.read_text(encoding="utf-8") == "第一行\n旧内容\n"


def test_undo_removes_file_created_by_write(tmp_path):
    ctx = {"workspace_root": str(tmp_path)}
    created = run(
        write_file(None, {"confirm": True, "path": "new.txt", "content": "内容"}, ctx)
    )
    assert (tmp_path / "new.txt").is_file()

    undo = run(
        write_file(
            None,
            {"confirm": True, "path": "new.txt", "undo_snapshot_id": created["snapshot_id"]},
            ctx,
        )
    )
    assert undo["ok"] is True
    assert not (tmp_path / "new.txt").exists()


def test_undo_refuses_when_file_changed_after_write(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("原始", encoding="utf-8")
    ctx = {"workspace_root": str(tmp_path)}
    result = run(write_file(None, {"confirm": True, "path": "notes.md", "content": "第一次"}, ctx))
    target.write_text("外部修改", encoding="utf-8")

    undo = run(
        write_file(
            None,
            {"confirm": True, "path": "notes.md", "undo_snapshot_id": result["snapshot_id"]},
            ctx,
        )
    )
    assert undo["ok"] is False
    assert "又被修改" in undo["error"]
    assert target.read_text(encoding="utf-8") == "外部修改"


def test_diff_is_truncated_for_large_changes(tmp_path):
    before = "\n".join(f"line-{i}" for i in range(400))
    after = "\n".join(f"changed-{i}" for i in range(400))
    diff, truncated = preview.build_unified_diff("big.txt", before, after, max_lines=20)
    assert truncated is True
    assert len(diff) == 20
