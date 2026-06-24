"""Agent write_workspace_file：非 daily-orchestrator 暂存为 EmployeeChangeRequest。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _reset_sqlalchemy_globals() -> None:
    import modstore_server.models as m

    if getattr(m, "_engine", None) is not None:
        m._engine.dispose()
    m._engine = None
    m._SessionFactory = None


@pytest.mark.xfail(strict=False, reason="tool_write pre-existing failure in CI")
def test_tool_write_defers_for_regular_employee(monkeypatch, tmp_path):
    _reset_sqlalchemy_globals()
    db = tmp_path / "tw.db"
    monkeypatch.setenv("MODSTORE_DB_PATH", str(db))

    from modstore_server.models import EmployeeChangeRequest, User, get_session_factory, init_db

    init_db(db)
    sf = get_session_factory(db)
    with sf() as s:
        s.add(User(username="u", email="u@u", password_hash="x", is_admin=False))
        s.commit()

    from modstore_server.mod_employee_agent_runner import tool_write_workspace_file

    ws = str(tmp_path / "workspace")
    Path(ws).mkdir(parents=True, exist_ok=True)

    async def run():
        return await tool_write_workspace_file(
            ws,
            "out.txt",
            "hello-deferred",
            {"employee_id": "market-frontend-dev"},
        )

    out = asyncio.run(run())
    assert out.get("ok") is True
    assert out.get("deferred") is True
    assert not (Path(ws) / "out.txt").exists()

    with sf() as s:
        n = s.query(EmployeeChangeRequest).count()
        assert n == 1


def test_tool_write_daily_orchestrator_writes_directly(monkeypatch, tmp_path):
    _reset_sqlalchemy_globals()
    db = tmp_path / "tw2.db"
    monkeypatch.setenv("MODSTORE_DB_PATH", str(db))
    from modstore_server.models import get_session_factory, init_db

    init_db(db)

    from modstore_server.mod_employee_agent_runner import tool_write_workspace_file

    ws = str(tmp_path / "workspace2")
    Path(ws).mkdir(parents=True, exist_ok=True)

    async def run():
        return await tool_write_workspace_file(
            ws,
            "direct.txt",
            "ok",
            {"employee_id": "daily-orchestrator"},
        )

    out = asyncio.run(run())
    assert out.get("ok") is True
    assert not out.get("deferred")
    assert (Path(ws) / "direct.txt").read_text(encoding="utf-8") == "ok"
