"""工厂 Workspace 注册表 :mod:`app.application.workspaces` 守卫。"""

from __future__ import annotations

import pytest

from app.application.workspaces import (
    DEFAULT_WORKSPACE_ID,
    Workspace,
    WorkspaceError,
    WorkspaceRegistry,
)


def test_default_xcmax_workspace_resolves_and_isolation_none():
    reg = WorkspaceRegistry()
    ws = reg.get(DEFAULT_WORKSPACE_ID)
    assert ws.id == DEFAULT_WORKSPACE_ID
    assert ws.root.exists()
    assert ws.isolation == "none"


def test_unknown_workspace_rejected():
    reg = WorkspaceRegistry({"schema_version": 1, "workspaces": {}})
    with pytest.raises(WorkspaceError):
        reg.get("ghost-repo")


def test_missing_id_falls_back_to_xcmax():
    reg = WorkspaceRegistry()
    assert reg.get(None).id == DEFAULT_WORKSPACE_ID
    assert reg.get("").id == DEFAULT_WORKSPACE_ID


def test_checkout_isolation_none_returns_root(tmp_path):
    ws = Workspace(id="t", label="t", root=tmp_path, isolation="none")
    reg = WorkspaceRegistry()
    # P1 自举：isolation=none → checkout 直接返回工程根（零额外磁盘/worktree）。
    assert reg.checkout(ws, task_id="task-1") == tmp_path


def test_checkout_missing_root_raises():
    reg = WorkspaceRegistry()
    ws = Workspace(
        id="t", label="t", root=__import__("pathlib").Path("/no/such/root"), isolation="none"
    )
    with pytest.raises(WorkspaceError):
        reg.checkout(ws, task_id="task-1")


def test_custom_doc_parsing():
    reg = WorkspaceRegistry(
        {
            "schema_version": 1,
            "workspaces": {
                "ext": {
                    "id": "ext",
                    "label": "外部项目",
                    "root": "/tmp",
                    "vcs": {"kind": "git", "default_branch": "develop"},
                    "isolation": "worktree",
                }
            },
        }
    )
    ws = reg.get("ext")
    assert ws.default_branch == "develop"
    assert ws.isolation == "worktree"
    assert [w.id for w in reg.list()] == ["ext"]
