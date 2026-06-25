"""发版闭环单测：mobile_ota / 版本发现 / 共识聚合 / ci_dispatch / 整条编排。

闭环编排用注入 fake 跑端到端：shadow 对齐、blocked、released、smoke 失败回滚、待审批。
外部副作用（GitHub/COS/服务器）全经注入接口，无真实网络/落盘。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from modstore_server import (
    ci_dispatch,
    mobile_ota,
    mobile_release_loop,
    release_consensus,
    release_version_discovery,
)
from modstore_server.ci_dispatch import CiDispatcher, DispatchResult
from modstore_server.mobile_release_loop import LoopDeps, run_mobile_release_loop
from modstore_server.release_consensus import ReadinessVerdict
from modstore_server.release_version_discovery import PlatformDiff, ReleaseProposal

# ── mobile_ota ─────────────────────────────────────────────────────────────


def test_platform_release_defaults_per_platform():
    a = mobile_ota.platform_release("android", rel={})
    assert a["latest_name"] == "10.0.0" and a["latest_code"] == 10 and a["available"] is True
    h = mobile_ota.platform_release("harmony", rel={})
    assert h["latest_code"] == 100000 and h["available"] is True  # 100000 制
    i = mobile_ota.platform_release("ios", rel={})
    assert i["available"] is False  # 无原生工程


def test_platform_release_reads_mobile_block():
    rel = {"mobile": {"harmony": {"latest_code": 100100, "latest_name": "10.1.0"}}}
    h = mobile_ota.platform_release("harmony", rel=rel)
    assert h["latest_name"] == "10.1.0" and h["latest_code"] == 100100


def test_android_download_url_shape():
    a = mobile_ota.platform_release("android", sku="enterprise", rel={})
    assert a["download_url"].endswith("XCAGI-Enterprise-Android-10.0.0.apk")


def test_set_platform_release_writes_block(tmp_path, monkeypatch):
    p = tmp_path / "download_release.json"
    p.write_text(
        json.dumps({"marketing_version": "10.0.0", "android_version": "10.0.0"}), encoding="utf-8"
    )
    monkeypatch.setattr(mobile_ota.download_release, "write_public_manifests", lambda rel: [])
    res = mobile_ota.set_platform_release(
        "harmony", latest_code=100100, latest_name="10.1.0", path=p
    )
    assert res["ok"] is True
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["mobile"]["harmony"]["latest_name"] == "10.1.0"
    assert saved["mobile"]["harmony"]["latest_code"] == 100100


# ── 版本发现 ───────────────────────────────────────────────────────────────


def test_discover_from_version_md_text():
    md = "| **XCAGI 总版本** | `10.2.0` | x |\n"
    prop = release_version_discovery.discover_target(version_md_text=md, rel={})
    assert prop.target_version == "10.2.0"
    assert "android" in prop.in_scope and "harmony" in prop.in_scope
    assert "ios" not in prop.in_scope  # 不可用→不在编
    da = prop.diff_for("android")
    assert da is not None and da.needs_bump is True and da.target_name == "10.2.0"


def test_discover_override_wins():
    prop = release_version_discovery.discover_target(
        target_override="11.0.0", version_md_text="", rel={}
    )
    assert prop.target_version == "11.0.0" and prop.source == "override"


# ── 共识聚合 ───────────────────────────────────────────────────────────────


def test_deterministic_readiness():
    v = release_consensus.deterministic_readiness("android", "10.1.0", "10.0.0", available=True)
    assert v.ready is True and v.blockers == []
    v2 = release_consensus.deterministic_readiness("ios", "10.1.0", "", available=False)
    assert v2.ready is False and "平台无原生工程/不可用" in v2.blockers


def test_aggregate_aligned_and_blocked():
    in_scope = ["android", "harmony"]
    ready = {
        "android": ReadinessVerdict("android", True),
        "harmony": ReadinessVerdict("harmony", True),
    }
    rec = release_consensus.aggregate("10.1.0", in_scope, ready)
    assert rec.aligned is True and rec.consensus == "aligned"

    blocked = {
        "android": ReadinessVerdict("android", True),
        "harmony": ReadinessVerdict("harmony", False, blockers=["构建未绿"]),
    }
    rec2 = release_consensus.aggregate("10.1.0", in_scope, blocked)
    assert rec2.aligned is False and rec2.consensus == "blocked"
    assert any("harmony" in b and "构建未绿" in b for b in rec2.blockers)


def test_aggregate_empty_scope_not_aligned():
    rec = release_consensus.aggregate("10.1.0", [], {})
    assert rec.aligned is False


# ── ci_dispatch（注入 fake HTTP）────────────────────────────────────────────


def _fake_http(post_status: int, run: Dict[str, Any]):
    posts: List[Dict[str, Any]] = []

    def post(url, *, json_body, headers):
        posts.append({"url": url, "body": json_body})
        return {"status": post_status, "json": {} if post_status == 204 else {"message": "bad"}}

    def get(url, *, headers):
        return {"status": 200, "json": {"workflow_runs": [run] if run else []}}

    return post, get, posts


def test_ci_dispatch_success():
    post, get, posts = _fake_http(
        204, {"id": 999, "status": "completed", "conclusion": "success", "html_url": "u"}
    )
    d = CiDispatcher("o/r", "tok", http_post=post, http_get=get, sleep=lambda s: None)
    res = d.trigger_and_wait("fhd-release-android.yml", "main", {"version": "10.1.0"})
    assert res.ok is True and res.run_id == "999" and res.conclusion == "success"
    assert posts and posts[0]["body"]["inputs"]["version"] == "10.1.0"


def test_ci_dispatch_failure_conclusion():
    post, get, _ = _fake_http(
        204, {"id": 1, "status": "completed", "conclusion": "failure", "html_url": "u"}
    )
    d = CiDispatcher("o/r", "tok", http_post=post, http_get=get, sleep=lambda s: None)
    res = d.trigger_and_wait("wf.yml", "main", {})
    assert res.ok is False and res.conclusion == "failure"


def test_ci_dispatch_post_rejected():
    post, get, _ = _fake_http(403, {})
    d = CiDispatcher("o/r", "tok", http_post=post, http_get=get, sleep=lambda s: None)
    res = d.dispatch("wf.yml", "main", {})
    assert res.ok is False and "dispatch 失败" in res.error


def test_workflow_for():
    assert ci_dispatch.workflow_for("harmony") == "fhd-release-harmony.yml"
    assert ci_dispatch.workflow_for("nope") == ""


# ── 整条闭环编排（注入 fake deps）───────────────────────────────────────────


def _proposal(in_scope=("android", "harmony")) -> ReleaseProposal:
    diffs = [
        PlatformDiff("android", "10.0.0", "10.1.0", True, True),
        PlatformDiff("harmony", "10.0.0", "10.1.0", True, True),
        PlatformDiff("ios", "", "10.1.0", False, False),
    ]
    return ReleaseProposal("10.1.0", "test", diffs, list(in_scope))


def _deps(**over) -> LoopDeps:
    calls: Dict[str, Any] = over.pop("_calls", {})

    def build(p, t):
        calls.setdefault("build", []).append(p)
        return DispatchResult(True, "wf", "main", run_id="r1", conclusion="success")

    def rollback(p, prev):
        calls.setdefault("rollback", []).append((p, prev))

    base = dict(
        discover=lambda: _proposal(),
        readiness=lambda p, prop: ReadinessVerdict(
            p, True, prop.diff_for(p).current_name, prop.target_version
        ),
        bump_version=lambda t: True,
        request_approval=lambda rec: True,
        build=build,
        distribute=lambda p, t: True,
        ota_bump=lambda p, t: True,
        smoke=lambda p, t: True,
        rollback=rollback,
    )
    base.update(over)
    return LoopDeps(**base)


def test_loop_shadow_aligned_stops_before_irreversible():
    calls: Dict[str, Any] = {}
    deps = _deps(
        _calls=calls,
        build=lambda p, t: (_ for _ in ()).throw(AssertionError("build 不该在 shadow 调用")),
    )
    res = run_mobile_release_loop(deps, mode="shadow")
    assert res["status"] == "shadow_aligned" and res["consensus"] == "aligned"
    assert res["per_platform"] == []  # 未触发构建


def test_loop_blocked_when_platform_not_ready():
    deps = _deps(
        readiness=lambda p, prop: ReadinessVerdict(
            p, p != "harmony", blockers=[] if p != "harmony" else ["构建未绿"]
        )
    )
    res = run_mobile_release_loop(deps, mode="primary")
    assert res["status"] == "blocked" and res["ok"] is False
    assert any("harmony" in b for b in res["blockers"])


def test_loop_primary_released_all_platforms():
    calls: Dict[str, Any] = {}
    deps = _deps(_calls=calls)
    res = run_mobile_release_loop(deps, mode="primary")
    assert res["status"] == "released" and res["ok"] is True
    assert sorted(calls["build"]) == ["android", "harmony"]
    assert all(row["ok"] for row in res["per_platform"])
    assert "rollback" not in calls


def test_loop_primary_rejected_awaits_approval():
    deps = _deps(request_approval=lambda rec: False)
    res = run_mobile_release_loop(deps, mode="primary")
    assert res["status"] == "awaiting_approval"
    assert res["per_platform"] == []  # 未审批不构建


def test_loop_smoke_fail_rolls_back_that_platform():
    calls: Dict[str, Any] = {}
    deps = _deps(_calls=calls, smoke=lambda p, t: p != "harmony")
    res = run_mobile_release_loop(deps, mode="primary")
    assert res["status"] == "partial" and res["ok"] is False
    rows = {row["platform"]: row for row in res["per_platform"]}
    assert rows["android"]["ok"] is True
    assert rows["harmony"]["ok"] is False and rows["harmony"]["stage"] == "smoke"
    assert rows["harmony"].get("rolled_back") is True
    assert calls["rollback"] == [("harmony", "10.0.0")]


def test_loop_bump_failure_aborts():
    deps = _deps(bump_version=lambda t: False)
    res = run_mobile_release_loop(deps, mode="primary")
    assert res["status"] == "bump_failed" and res["ok"] is False
