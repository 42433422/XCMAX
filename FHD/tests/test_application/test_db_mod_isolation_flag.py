"""Mod 分库开关与 ORM 路由一致性。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DB_MOD = _REPO / "app/db/__init__.py"
_spec = importlib.util.spec_from_file_location("db_mod_isolation_test", _DB_MOD)
assert _spec and _spec.loader
db_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db_mod)


def test_sqlite_mod_suffix_disabled_when_isolated_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", "0")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/xcagi.db")
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    token = set_request_active_mod_id("xcagi-planner-bridge")
    try:
        url = db_mod._database_url_for_active_mod("sqlite:///tmp/xcagi.db")
    finally:
        reset_request_active_mod_id(token)
    assert url == "sqlite:///tmp/xcagi.db"
