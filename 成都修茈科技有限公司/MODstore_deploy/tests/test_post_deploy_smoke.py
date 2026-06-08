"""post_deploy_smoke unit tests (no live network)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.release_gate


def test_post_deploy_smoke_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_ENABLED", "0")
    from modstore_server.post_deploy_smoke import run_post_deploy_smoke

    out = run_post_deploy_smoke()
    assert out["ok"] is True
    assert out.get("skipped") is True


def test_post_deploy_smoke_mock_probes(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_DEPLOY_HEALTH_URL", "http://127.0.0.1:8000/health")
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_MARKET_URL", "https://example.com/market/download")

    from modstore_server import post_deploy_smoke as pds

    def fake_get(url: str, *, timeout_sec: float) -> tuple[int, str]:
        if "8000" in url:
            return 200, ""
        return 503, "bad gateway"

    monkeypatch.setattr(pds, "_http_get_status", fake_get)
    out = pds.run_post_deploy_smoke()
    assert out["ok"] is False
    assert len(out["probes"]) == 2


def test_slo_halt_blocks_when_last_smoke_failed(monkeypatch, tmp_path) -> None:
    state = tmp_path / "smoke.json"
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_STATE_FILE", str(state))
    monkeypatch.setenv("MODSTORE_SLO_HALT_AUTO_MERGE", "1")
    state.write_text('{"ok": false, "skipped": false}', encoding="utf-8")

    from modstore_server.post_deploy_smoke import slo_halt_blocks_auto_merge

    assert slo_halt_blocks_auto_merge() is True


def test_slo_halt_off_when_env_disabled(monkeypatch, tmp_path) -> None:
    state = tmp_path / "smoke.json"
    monkeypatch.setenv("MODSTORE_POST_DEPLOY_SMOKE_STATE_FILE", str(state))
    monkeypatch.setenv("MODSTORE_SLO_HALT_AUTO_MERGE", "0")
    state.write_text('{"ok": false, "skipped": false}', encoding="utf-8")

    from modstore_server.post_deploy_smoke import slo_halt_blocks_auto_merge

    assert slo_halt_blocks_auto_merge() is False
