"""Employee file writes expose a diff and a reversible snapshot."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.mod_sdk.employee_tools import write_preview as preview
from app.mod_sdk.employee_tools.employee_tool_ports import WorkspacePorts
from app.mod_sdk.employee_tools.workspace import patch_file, write_file


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

    result = run(
        write_file(None, {"confirm": True, "path": "notes.md", "content": "第一行\n新内容\n"}, ctx)
    )
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
    created = run(write_file(None, {"confirm": True, "path": "new.txt", "content": "内容"}, ctx))
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


@pytest.mark.parametrize("scope", ["path", "workspace_root", "user_id", "tenant_id", "mod_id"])
def test_snapshot_cannot_restore_another_target_or_identity(tmp_path, scope):
    ctx = {
        "workspace_root": str(tmp_path),
        "user_id": "alice",
        "tenant_id": "acme",
        "mod_id": "writer",
    }
    (tmp_path / "secret.txt").write_text("private before", encoding="utf-8")
    written = run(
        write_file(None, {"confirm": True, "path": "secret.txt", "content": "same after"}, ctx)
    )
    other_ctx, path = dict(ctx), "secret.txt"
    if scope == "path":
        path = "other.txt"
        (tmp_path / path).write_text("same after", encoding="utf-8")
    elif scope == "workspace_root":
        other_root = tmp_path / "other-workspace"
        other_root.mkdir()
        (other_root / path).write_text("same after", encoding="utf-8")
        other_ctx[scope] = str(other_root)
    else:
        other_ctx[scope] = "different"
    restored = run(
        write_file(
            None,
            {"confirm": True, "path": path, "undo_snapshot_id": written["snapshot_id"]},
            other_ctx,
        )
    )
    assert restored["ok"] is False
    assert (Path(other_ctx["workspace_root"]) / path).read_text() == "same after"


def test_snapshot_ids_cannot_escape_the_snapshot_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.with_suffix(".json").write_text('{"existed": true}', encoding="utf-8")
    assert preview.read_snapshot(str(outside), target=tmp_path / "target", context={}) is None
    assert preview.read_snapshot("../outside", target=tmp_path / "target", context={}) is None


def test_undo_preserves_original_bytes_and_rejects_corrupted_backup(tmp_path):
    target = tmp_path / "legacy.txt"
    original = b"windows\r\nbytes\xff\r\n"
    target.write_bytes(original)
    ctx = {"workspace_root": str(tmp_path)}
    written = run(
        write_file(None, {"confirm": True, "path": target.name, "content": "new\r\n"}, ctx)
    )
    undo_params = {"confirm": True, "path": target.name, "undo_snapshot_id": written["snapshot_id"]}
    backup = preview.snapshot_root(target, ctx) / f"{written['snapshot_id']}.bak"
    backup.write_bytes(b"corrupted")
    assert run(write_file(None, undo_params, ctx))["ok"] is False
    assert target.read_bytes() == b"new\r\n"
    backup.write_bytes(original)
    assert run(write_file(None, undo_params, ctx))["ok"] is True
    assert target.read_bytes() == original


@pytest.mark.parametrize("delete", [False, True])
def test_real_git_patch_is_snapshotted_before_write_and_can_be_undone(tmp_path, delete):
    target = tmp_path / "notes.txt"
    target.write_bytes(b"old\n")
    ctx = {"workspace_root": str(tmp_path)}

    async def git_run(args, *, cwd, timeout):
        if "--check" not in args:
            snapshots = list(preview.snapshot_root(target, ctx).glob("*.bak"))
            assert len(snapshots) == 1
            assert snapshots[0].read_bytes() == b"old\n"
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}

    patch = (
        "--- a/notes.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        if delete
        else "--- a/notes.txt\n+++ b/notes.txt\n@@ -1 +1 @@\n-old\n+new\n"
    )
    ports = WorkspacePorts(root=tmp_path, run=git_run)
    written = run(patch_file(ports, {"confirm": True, "path": target.name, "patch": patch}, ctx))
    assert written["ok"] is True
    assert target.exists() is not delete
    restored = run(
        patch_file(
            ports,
            {"confirm": True, "path": target.name, "undo_snapshot_id": written["snapshot_id"]},
            ctx,
        )
    )
    assert restored["ok"] is True
    assert target.read_bytes() == b"old\n"
