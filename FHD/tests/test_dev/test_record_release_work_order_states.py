# mypy: disable-error-code="func-returns-value"
"""record_release_work_order_states：发布时回收 merged/released。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "dev" / "record_release_work_order_states.py"
_spec = importlib.util.spec_from_file_location("record_release_work_order_states", _SCRIPT)
assert _spec is not None and _spec.loader is not None
rrws = importlib.util.module_from_spec(_spec)
sys.modules["record_release_work_order_states"] = rrws
_spec.loader.exec_module(rrws)


def _config(tmp_path: Path, version: str, sha: str, issues: list[int]) -> Path:
    cfg = tmp_path / "download_release.json"
    cfg.write_text(
        json.dumps({"version_lock": version, "git_sha": sha, "linked_issues": issues}),
        encoding="utf-8",
    )
    return cfg


def _args(cfg: Path, **overrides: Any) -> Any:
    values = {
        "market_base": "https://market.test",
        "market_token": "token",
        "release_config": str(cfg),
        "version": "",
        "dry_run": False,
        "apply": True,
    }
    values.update(overrides)
    return type("Args", (), values)  # type: ignore[return-value]


class _MarketSim:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.views: dict[int, dict[str, Any]] = {}

    def http(self, method: str, url: str, _token: str, body: dict[str, Any] | None = None) -> Any:
        if method == "GET":
            number = int(url.rsplit("/", 1)[-1])
            return self.views.get(number, {})
        if method == "POST":
            self.calls.append((url, body or {}))
            return {"ok": True, "wo_id": str((body or {}).get("wo_id") or "")}
        return {}


def test_progresses_merged_then_released(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sim = _MarketSim()
    sim.views[42] = {"wo_id": "WO-abc", "status": "in_dev"}
    monkeypatch.setattr(rrws, "_http", sim.http)
    rc = rrws.run(_args(_config(tmp_path, "1.0.0.1", "a" * 40, [42])))
    assert rc == 0
    targets = [body["to_state"] for _, body in sim.calls]
    assert targets == ["merged", "released"]
    first_ref = sim.calls[0][1]["ref"]
    assert first_ref["release_version"] == "1.0.0.1"
    assert first_ref["build_sha"] == "a" * 40
    assert first_ref["issue_number"] == 42


def test_merges_from_candidate_and_skips_released(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sim = _MarketSim()
    sim.views[1] = {"wo_id": "WO-a", "status": "candidate"}
    sim.views[2] = {"wo_id": "WO-b", "status": "released"}
    sim.views[3] = {}
    monkeypatch.setattr(rrws, "_http", sim.http)
    rc = rrws.run(_args(_config(tmp_path, "1.0.0.2", "b" * 40, [1, 2, 3])))
    assert rc == 0
    wo_ids = [body["wo_id"] for _, body in sim.calls]
    assert wo_ids == ["WO-a", "WO-a"]  # candidate → merged → released
    assert sim.views[2]["wo_id"] not in wo_ids, "已 released 的工单不得重复推进"


def test_dry_run_makes_no_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sim = _MarketSim()
    sim.views[7] = {"wo_id": "WO-c", "status": "in_dev"}
    monkeypatch.setattr(rrws, "_http", sim.http)
    rc = rrws.run(_args(_config(tmp_path, "1.0.0.3", "c" * 40, [7]), dry_run=True, apply=False))
    assert rc == 0
    assert sim.calls == []


def test_market_unreachable_still_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cable = {"down": False}

    def flaky_http(method: str, url: str, _token: str, body: dict[str, Any] | None = None) -> Any:
        if cable["down"]:
            return {"_error": "network", "_body": "boom"}
        return {"ok": True, "wo_id": str((body or {}).get("wo_id") or "")}

    monkeypatch.setattr(rrws, "_http", flaky_http)
    with monkeypatch.context() as m:
        m2 = m

        def view_getter(
            method: str, url: str, _token: str, body: dict[str, Any] | None = None
        ) -> Any:
            if method == "GET":
                return {"wo_id": "WO-d", "status": "routed"}
            return flaky_http(method, url, _token, body)

        m2.setattr(rrws, "_http", view_getter)
        rc = rrws.run(_args(_config(tmp_path, "1.0.0.4", "d" * 40, [9])))
    assert rc == 0  # 失败不阻断发布
