"""用户数据与租户工作区的路径护栏。"""

from __future__ import annotations

import os

import pytest

import modstore_server.models as models
from modstore_server.integrations import ops_action_handlers as ops
from modstore_server.integrations.vibe_adapter import (
    VibePathError,
    ensure_within_workspace,
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "pathguard.sqlite"))
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def test_git_add_all_rejects_catalog_data_cwd(fresh_db, monkeypatch):
    root = fresh_db
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(root))
    monkeypatch.setattr(ops, "_write_audit", lambda **kw: 1)

    bad_cwd = str(root / "MODstore_deploy" / "modstore_server" / "catalog_data")
    out = ops.dispatch_ops_handler(
        "shell_exec",
        {"shell_exec": {"command_id": "git-add-all", "args": {"cwd": bad_cwd}}},
        {},
        "t",
        "daily-orchestrator",
        0,
    )
    assert out["ok"] is False
    assert (
        "refused" in (out.get("error") or "").lower()
        or "user-data" in (out.get("error") or "").lower()
    )


@pytest.mark.parametrize("relative", ["../99", "../42-prefix", "../../outside"])
def test_workspace_rejects_outside_paths_before_filesystem_resolution(
    tmp_path, monkeypatch, relative
):
    workspace = tmp_path / "workspaces" / "42"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace))
    requested = str(workspace) + os.sep + relative
    outside = os.path.abspath(requested)
    probes = []
    original_lstat = os.lstat

    def record_lstat(path, *args, **kwargs):
        probes.append(os.fspath(path))
        return original_lstat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "lstat", record_lstat)
        with pytest.raises(VibePathError):
            ensure_within_workspace(requested, user_id=42)
    assert outside not in probes, "tenant rejection must precede probing the outside path"


def test_workspace_keeps_legal_paths_and_internal_symlinks(tmp_path, monkeypatch):
    workspace = tmp_path / "workspaces" / "42"
    project = workspace / "project"
    project.mkdir(parents=True)
    source = workspace / "input.csv"
    source.write_text("id\n1\n", encoding="utf-8")
    internal_link = workspace / "linked"
    internal_link.symlink_to(project, target_is_directory=True)
    configured = tmp_path / "configured"
    configured.symlink_to(workspace, target_is_directory=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(configured))
    for selected in (
        workspace,
        configured,
        project,
        configured / "project",
        internal_link,
        source,
        project / ".." / "input.csv",
    ):
        assert ensure_within_workspace(selected, user_id=42) == selected.resolve()
    monkeypatch.chdir(workspace)
    assert ensure_within_workspace("project", user_id=42) == project
    assert ensure_within_workspace(".", user_id=42) == workspace


def test_workspace_rejects_escaping_symlink_and_missing_target(tmp_path, monkeypatch):
    workspace = tmp_path / "workspaces" / "42"
    workspace.mkdir(parents=True)
    outside = tmp_path / "workspaces" / "99"
    outside.mkdir()
    escape = workspace / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace))
    for selected in (escape, workspace / "missing", ""):
        with pytest.raises(VibePathError):
            ensure_within_workspace(selected, user_id=42)


def test_workspace_scope_cannot_expand_tenant_or_change_after_selection(tmp_path, monkeypatch):
    workspace = tmp_path / "workspaces" / "42"
    project = workspace / "project"
    other_project = workspace / "other-project"
    project.mkdir(parents=True)
    other_project.mkdir()
    outside = tmp_path / "workspaces" / "99"
    outside.mkdir()
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace))
    approved = ensure_within_workspace(project, user_id=42)
    with pytest.raises(VibePathError):
        ensure_within_workspace("output.csv", user_id=42, within=outside, must_exist=False)
    project.rmdir()
    project.symlink_to(other_project, target_is_directory=True)
    with pytest.raises(VibePathError):
        ensure_within_workspace("output.csv", user_id=42, within=approved, must_exist=False)


def test_workspace_creates_tenant_root_but_not_planned_output(tmp_path, monkeypatch):
    workspace = tmp_path / "workspaces" / "42"
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace))
    assert ensure_within_workspace(workspace, user_id=42) == workspace
    target = ensure_within_workspace(
        "outputs/result.csv", user_id=42, within=workspace, must_exist=False
    )
    assert target == workspace / "outputs" / "result.csv"
    assert not target.parent.exists()
    with pytest.raises(VibePathError):
        ensure_within_workspace(target, user_id=42)
