"""Tests for digest_line_executor (Phase A)."""

from __future__ import annotations

import modstore_server.models as models
from modstore_server.digest_line_executor import execute_digest_line_work_units
from modstore_server.models import DailyDigestRecord, get_session_factory


def _seed_digest(ps_md: str, base_version: str = "2026-06-03#main#abc#r1") -> int:
    models.init_db()
    sf = get_session_factory()
    with sf() as session:
        row = DailyDigestRecord(
            day="2026-06-03",
            subject="test digest",
            body_text="body",
            vibe_prep_ps_md=ps_md,
            vibe_prep_meta_json=f'{{"ok": true, "base_version": "{base_version}"}}',
        )
        session.add(row)
        session.flush()
        rid = int(row.id)
        session.commit()
        return rid


def test_execute_ps_patches_dispatches(monkeypatch):
    ps = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [fhd-core-maintainer] 核心\n\n"
        "- **P0** 修 pytest\n"
    )
    rid = _seed_digest(ps)
    calls = []

    def fake_dispatch(subtasks, **kwargs):
        calls.append({"n": len(subtasks), "kwargs": kwargs})
        return {"ok": True, "results": [{"employee_id": "fhd-core-maintainer", "ok": True}]}

    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")
    monkeypatch.setattr(
        "modstore_server.employee_orchestrator.dispatch_subtasks",
        fake_dispatch,
    )

    out = execute_digest_line_work_units(rid, dispatch_line="P-S", mode="test")
    assert out["ok"] is True
    assert out["unit_count"] == 1
    assert calls and calls[0]["n"] == 1

    out2 = execute_digest_line_work_units(rid, dispatch_line="P-S", mode="test")
    assert out2.get("skipped") is True


def test_execute_skips_when_no_units(monkeypatch):
    ps = "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n" "## [fhd-core-maintainer] 核心\n\n"
    rid = _seed_digest(ps)
    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")
    out = execute_digest_line_work_units(rid, force=True)
    assert out["ok"] is True
    assert out.get("reason") == "no matching work units"
