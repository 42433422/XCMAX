"""ops_action_handlers：用户数据路径护栏。"""

from __future__ import annotations

import pytest

import modstore_server.models as models
from modstore_server.integrations import ops_action_handlers as ops


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
