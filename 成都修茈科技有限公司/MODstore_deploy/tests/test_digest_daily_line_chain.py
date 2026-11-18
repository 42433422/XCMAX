# ruff: noqa: E402
"""Tests for digest_daily_line_chain (Phase B/C employee wiring)."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

import modstore_server.models as models

pytestmark = pytest.mark.release_gate
from modstore_server.digest_daily_line_chain import (
    execute_installer_employee_chain,
    execute_phase_a_line_chain,
    execute_phase_b_line_chain,
    wait_for_phase_a,
)
from modstore_server.models import DailyDigestRecord, get_session_factory


def _seed_full_digest(tmp_path, monkeypatch, *, include_app: bool = False) -> int:
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "chain.sqlite"))
    models.init_db()

    pw = (
        "# Vibe 预备 · P-W 软件线 · 更新清单\n\n"
        "## [market-frontend-dev] 营销\n\n"
        "- **P1** 更新 SEO sitemap\n"
    )
    sr = (
        "# Vibe 预备 · S-R 软件线 · 更新清单\n\n"
        "## [daily-orchestrator] 编排\n\n"
        "- **P1** 归档过期 digest TTL\n"
    )
    ps = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [fhd-core-maintainer] 核心\n\n"
        "- **P0** 修 pytest\n"
    )
    app = ""
    if include_app:
        app = (
            "# Vibe 预备 · P-App 移动发布线 · 补丁清单\n\n"
            "## [mobile-android-release-officer]\n\n"
            "- **P2** 修复渠道包签名\n"
        )
    sf = get_session_factory()
    with sf() as session:
        row = DailyDigestRecord(
            day="2026-06-04",
            subject="chain test",
            vibe_prep_pw_md=pw,
            vibe_prep_sr_md=sr,
            vibe_prep_ps_md=ps,
            vibe_prep_app_md=app,
            vibe_prep_meta_json='{"base_version": "2026-06-04#main#abc#r1"}',
            release_train_after="1.0.1.0",
            release_kind="installer",
        )
        session.add(row)
        session.commit()
        return int(row.id)


def test_phase_a_shadow_dispatches_ps_and_app(tmp_path, monkeypatch) -> None:
    rid = _seed_full_digest(tmp_path, monkeypatch, include_app=True)
    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")

    out = execute_phase_a_line_chain(rid, dry_run=True)
    assert out["ok"] is True
    assert out["phase"] == "A"
    assert "P-S" in out["line_results"]
    assert "P-App" in out["line_results"]
    app = out["line_results"]["P-App"]
    assert app.get("dry_run") is True
    assert app.get("unit_count", 0) >= 1
    assert "mobile-android-release-officer" in (app.get("planned_employees") or [])

    gate = wait_for_phase_a(rid, required=True)
    assert gate["ok"] is True

    sf = get_session_factory()
    with sf() as session:
        raw = session.get(DailyDigestRecord, rid).vibe_line_execute_json
    meta = json.loads(raw)
    assert meta.get("phase_a", {}).get("ok") is True


def test_phase_b_shadow_plans_pw_and_sr(tmp_path, monkeypatch) -> None:
    rid = _seed_full_digest(tmp_path, monkeypatch)
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_PHASE_B_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_REQUIRE_PHASE_A", "0")

    out = execute_phase_b_line_chain(rid, shadow=True)
    assert out["ok"] is True
    assert out["shadow"] is True
    assert "P-W" in out["line_results"]
    assert "P-App" in out["line_results"]
    assert "S-R" in out["line_results"]
    assert "patches" not in str(out["line_results"].get("P-App", {}).get("list_kinds") or [])
    pw = out["line_results"]["P-W"]
    assert pw.get("dry_run") is True
    assert pw.get("unit_count", 0) >= 1
    assert "market-frontend-dev" in (pw.get("planned_employees") or [])

    sf = get_session_factory()
    with sf() as session:
        raw = session.get(DailyDigestRecord, rid).vibe_line_execute_json
    meta = json.loads(raw)
    assert meta.get("phase_b", {}).get("ok") is True


def test_installer_chain_shadow_employee_sequence(tmp_path, monkeypatch) -> None:
    rid = _seed_full_digest(tmp_path, monkeypatch)
    monkeypatch.setenv("MODSTORE_INSTALLER_PUSH_ENABLED", "1")

    out = execute_installer_employee_chain(
        rid,
        release_train="1.0.1.0",
        release_kind="installer",
        shadow=True,
    )
    assert out["ok"] is True
    assert out["employee_chain"] == [
        "deploy-release-officer",
        "deploy-release-officer",
        "push-update-context-officer",
    ]
    assert len(out["steps"]) == 3


def test_major_chain_includes_extra_employees(tmp_path, monkeypatch) -> None:
    rid = _seed_full_digest(tmp_path, monkeypatch)
    monkeypatch.setenv("MODSTORE_INSTALLER_PUSH_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_MAJOR_PUSH_ENABLED", "1")

    out = execute_installer_employee_chain(
        rid,
        release_train="2.0.0.0",
        release_kind="major",
        shadow=True,
    )
    assert out["ok"] is True
    assert out["employee_chain"][0] == "dbops-engineer"
    assert "push-update-context-officer" in out["employee_chain"]
    assert len(out["steps"]) == 6
    assert all(s.get("shadow") for s in out["steps"])


@pytest.mark.parametrize("health_status,market_status", [(200, 200), (503, 200), (200, 503)])
def test_installer_chain_primary_dispatches(
    monkeypatch, tmp_path, health_status, market_status
) -> None:
    rid = _seed_full_digest(tmp_path, monkeypatch)
    calls = []
    probes = []
    health_url = "http://127.0.0.1:9999/api/health"
    market_url = "https://downloads.example.test/market/download"
    smoke_state = tmp_path / "post-deploy-smoke.json"

    def fake_get(url, *, timeout_sec):
        probes.append((url, timeout_sec))
        return {health_url: health_status, market_url: market_status}[url], ""

    push = Mock(return_value={"ok": True, "public_written": []})
    rollback = Mock(return_value={"ok": True})

    def fake_plan(task, ctx, **kwargs):
        calls.append({"employee": kwargs.get("target_employee_id"), "task": task[:40]})
        return {"ok": True, "results": []}

    monkeypatch.setenv("MODSTORE_INSTALLER_PUSH_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_INSTALLER_FASTGATE_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_TIMEOUT_SEC", "7")
    monkeypatch.setenv("MODSTORE_DEPLOY_HEALTH_URL", health_url)
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_MARKET_URL", market_url)
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_STATE_FILE", str(smoke_state))
    monkeypatch.setenv("MODSTORE_INSTALLER_COS_UPLOADED", "1")
    # Exercise the real gate while isolating HTTP, release writes and rollback
    # effects (backups/alerts); this unit test must never touch live services.
    monkeypatch.setattr("modstore_server.post_deploy_smoke._http_get_status", fake_get)
    monkeypatch.setattr("modstore_server.download_release.record_installer_push", push)
    monkeypatch.setattr("modstore_server.auto_rollback.auto_rollback_on_gate_failure", rollback)
    monkeypatch.setattr(
        "modstore_server.employee_orchestrator.plan_and_dispatch",
        fake_plan,
    )

    out = execute_installer_employee_chain(
        rid,
        release_train="1.0.1.0",
        release_kind="installer",
        shadow=False,
    )
    assert out["ok"] is True
    assert len(calls) == 3
    assert calls[0]["employee"] == "deploy-release-officer"
    assert calls[-1]["employee"] == "push-update-context-officer"
    assert probes == [(health_url, 7.0), (market_url, 7.0)]
    gate_ok = health_status == 200 and market_status == 200
    assert out["fastgate"]["ok"] is gate_ok
    assert out["fastgate"]["skipped"] is False
    assert out["fastgate"]["release_train"] == "1.0.1.0"
    assert out["fastgate"]["release_kind"] == "installer"
    assert json.loads(smoke_state.read_text(encoding="utf-8"))["ok"] is gate_ok
    if gate_ok:
        push.assert_called_once_with(
            release_train="1.0.1.0",
            release_kind="installer",
            cos_uploaded=True,
            actor="installer-employee-chain",
        )
        assert out["download_release"] == push.return_value
        rollback.assert_not_called()
    else:
        push.assert_not_called()
        assert out["download_release"] == {
            "ok": False,
            "blocked_by": "fastgate",
            "reason": out["fastgate"]["reason"],
        }
        rollback.assert_called_once_with(
            gate="FASTGATE",
            release_train="1.0.1.0",
            release_kind="installer",
            reason=out["fastgate"]["reason"],
        )
        assert out["rollback"] == rollback.return_value

    models._engine = None
    models._SessionFactory = None
