"""独立交付集成验收：真实回执 → 真实验收逻辑 → 实际回写路径 → 原工单更新。

不是把 accepted 结论直接注入再宣称通过；验收判定完全由市场端真实
``release_acceptance.judge_release_acceptance`` 依据接收到的回执计算得出，
再经 ``release_acceptance_closeout.run`` 的真实编排（GitHub 回写 + 本地
work_order.record_acceptance_verdict）更新原工单。

隔离：收据存内存 store、GitHub 用内存模拟器，工单/提案事件流入 tmp_path；
不访问网络。覆盖：成功关闭、失败-重开-修复-再验收、回写超时、重复回执幂等、
不同构建混入不污染判定。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import capability_proposal_recorder as recorder
from app.services import work_order_ssot as wo

_FHD_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _FHD_ROOT.parent

# 真实市场端验收判定（复用时只依赖标准库，可独立加载）
_MODSTORE_ACCEPTANCE = (
    _REPO_ROOT
    / "成都修茈科技有限公司"
    / "MODstore_deploy"
    / "modstore_server"
    / "release_acceptance.py"
)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


closeout = _load_module(
    "release_acceptance_closeout", _FHD_ROOT / "scripts" / "dev" / "release_acceptance_closeout.py"
)
to_issue = _load_module(
    "capability_proposal_to_issue",
    _FHD_ROOT / "scripts" / "dev" / "capability_proposal_to_issue.py",
)


@pytest.fixture(scope="module")
def judge() -> Any:
    if not _MODSTORE_ACCEPTANCE.exists():
        pytest.skip("market acceptance judge not in checkout")
    return _load_module("real_release_acceptance", _MODSTORE_ACCEPTANCE)


@dataclass
class _Receipt:
    installation_id: str
    platform: str
    status: str
    target_version: str
    target_build_sha: str
    error: str = ""
    reported_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _ReceiptStore:
    """内存收据库：按 version+channel+build_sha 过滤后喂给真实 judge。"""

    def __init__(self) -> None:
        self.rows: list[_Receipt] = []

    def stage(
        self,
        *,
        install_id: str,
        platform: str,
        status: str,
        version: str,
        build_sha: str,
        error: str = "",
    ) -> None:
        self.rows.append(
            _Receipt(
                installation_id=install_id,
                platform=platform,
                status=status,
                target_version=version,
                target_build_sha=build_sha,
                error=error,
            )
        )

    def acceptance(self, judge: Any, version: str, build_sha: str) -> dict[str, Any]:
        matched = [
            r for r in self.rows if r.target_version == version and r.target_build_sha == build_sha
        ]
        result: dict[str, Any] = judge.judge_release_acceptance(matched, version=version)
        return result


class _GitHubSim:
    """内存 GitHub issue 模拟：closeout 的 _http 由这里承载。"""

    def __init__(self) -> None:
        self.issues: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.comment_count = 0
        self.fail_after: str | None = None  # e.g. "comments" 用于注入回写超时
        self.wo_acceptance_calls: list[dict[str, Any]] = []
        self.wo_acceptance_fail = False  # 模拟共享宿主不可达 → 走本地兜底

    def new_issue(self, number: int) -> None:
        self.issues[number] = {"number": number, "state": "open", "labels": [], "body": ""}

    def _labels(self, issue: dict[str, Any]) -> dict[str, Any]:
        names = [label["name"] for label in issue["labels"]]
        return {"labels": [{"name": n} for n in names]}

    def http(self, method: str, url: str, _token: str, body: dict[str, Any] | None = None) -> Any:
        if self.fail_after and self.fail_after in url:
            return {"_error": 504, "_body": "gateway timeout (simulated)"}
        if "/api/work-orders/acceptance" in url:
            if body:
                self.wo_acceptance_calls.append(body)
            if self.wo_acceptance_fail:
                return {"_error": 503, "_body": "market unreachable"}
            return {"ok": True, "wo_id": "WO-remote", "from": "verifying", "to": "closed"}
        if "/labels" in url and method == "POST" and "repos/" not in url:
            return {}  # ensure-label 就当存在
        import re

        m = re.search(r"/repos/[^/]+/[^/]+/issues/(\d+)", url)
        number = int(m.group(1)) if m else 0
        if "/comments" in url:
            if body:
                self.comments.setdefault(number, []).append({"body": body.get("body", "")})
                self.comment_count += 1
            return {"id": self.comment_count}
        if url.rstrip("/").endswith(f"/issues/{number}"):
            if method == "PATCH" and body:
                self.issues[number]["state"] = body.get("state", self.issues[number]["state"])
            return {
                "number": number,
                "labels": self.issues[number]["labels"],
                "state": self.issues[number]["state"],
            }
        if "/labels" in url and "/issues/" in url and number > 0:
            payload = (body or {}).get("labels", []) if body else []
            names: list[str] = [
                str(one) if isinstance(one, str) else str(one.get("name") or "") for one in payload
            ]
            for name in names:
                if name and name not in [label["name"] for label in self.issues[number]["labels"]]:
                    self.issues[number]["labels"].append({"name": name})
            return self._labels(self.issues[number])
        return {}


@pytest.fixture
def isolates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(recorder, "_REPORT_DIR", tmp_path)
    monkeypatch.setattr(recorder, "_PROPOSAL_FILE", tmp_path / "capability_proposal.jsonl")
    monkeypatch.setattr(
        recorder, "_PROCESSED_FILE", tmp_path / "capability_proposal_processed.jsonl"
    )
    monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")
    return tmp_path


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, judge: Any):
    """把真实 judge 接入真实 closeout 编排（收据 store + GitHub 模拟器）。"""
    store = _ReceiptStore()
    gh = _GitHubSim()

    def fake_fetch(  # 仅负责按发布构建取回执并让真 judge 计算，绝不注入结论
        _base: str, _token: str, version: str, channel: str, build_sha: str = ""
    ) -> dict[str, Any]:
        assert channel in ("stable", "staging")
        return store.acceptance(judge, version, build_sha)

    monkeypatch.setattr(closeout, "_fetch_acceptance", fake_fetch)
    monkeypatch.setattr(closeout, "_http", gh.http)
    return SimpleNamespace(store=store, gh=gh)


def _make_work_order(tmp_path: Path, issue_number: int, *, customer_scoped: bool = False) -> str:
    ctx: dict[str, Any] = {"customer_id": f"cust-{issue_number}"} if customer_scoped else {}
    result = recorder.record_capability_proposal(
        raw_input=f"需求-{uuid.uuid4().hex}",
        reason="intent_unknown",
        context=ctx,
    )
    assert result["recorded"] is True
    key = str(result["dedup_key"])
    source = "intent_confirmation_service"
    proposal: dict[str, Any] = {
        "source": source,
        "dedup_key": key,
        "reason": "intent_unknown",
        "context": ctx,
    }
    track = to_issue._classify_proposal_track(proposal)
    to_issue._link_work_order(
        proposal, f"https://github.com/acme/repo/issues/{issue_number}", issue_number, track
    )
    wo_id = wo.derive_wo_id(key)
    # 完成阶段必须由对应开发/合并/发布证据驱动（#1853：验收回执不得补齐完成阶段）。
    # 这里按真实主线推进到 released，再交由 closeout 用市场回执判定验收。
    ref = {"issue_number": issue_number, "pr": f"acme/repo#pr-{issue_number}"}
    assert wo.record_transition(wo_id, "in_dev", ref=ref, note="开发立项", source="dev")["ok"]
    assert wo.record_transition(wo_id, "merged", ref=ref, note="合入主线", source="merge")["ok"]
    assert wo.record_transition(
        wo_id, "released", ref=ref, note="随发布构建上线", source="release"
    )["ok"]
    return wo_id


def _config(tmp_path: Path, version: str, build_sha: str, issue_numbers: list[int]) -> Path:
    cfg = tmp_path / f"release-{uuid.uuid4().hex[:8]}.json"
    cfg.write_text(
        json.dumps(
            {
                "version_lock": version,
                "git_sha": build_sha,
                "linked_issues": issue_numbers,
            }
        ),
        encoding="utf-8",
    )
    return cfg


def _args(cfg: Path) -> SimpleNamespace:
    return SimpleNamespace(
        repo="acme/repo",
        token="token",
        market_base="https://market.test",
        market_token="mkt",
        release_config=str(cfg),
        version="",
        channel="stable",
        dry_run=False,
        apply=True,
    )


class TestDeliveryCloseout:
    def test_same_release_dual_platform_accepted_closes_original(
        self, isolates: Path, pipeline: SimpleNamespace
    ) -> None:
        version = "1.0.0.1"
        sha = "a" * 40
        number = 901
        wo_id = _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=sha,
        )
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="installed",
            version=version,
            build_sha=sha,
        )

        rc = closeout.run(_args(_config(isolates, version, sha, [number])))

        assert rc == 0
        # 验收结论经真实回写路径发往共享宿主（远端优先）
        call = pipeline.gh.wo_acceptance_calls[-1]
        assert call["issue_number"] == number
        assert call["verdict"] == "accepted"
        assert call["release_version"] == version
        assert call["evidence"]["per_platform"]["win"]["installed"] == 1
        assert call["evidence"]["per_platform"]["mac"]["installed"] == 1
        # 远端权威，本地 JSONL 视图不重复写
        assert wo.get_work_order(wo_id)["status"] != "closed"  # type: ignore[index]
        assert [label["name"] for label in pipeline.gh.issues[number]["labels"]] == [
            "customer-accepted"
        ]
        assert pipeline.gh.comment_count == 1

    def test_market_unreachable_falls_back_to_local(
        self, isolates: Path, pipeline: SimpleNamespace
    ) -> None:
        """共享宿主不可达 → closeout 降级本地事件流，仍能关闭原工单。"""
        version = "1.0.0.9"
        sha = "9" * 40
        number = 910
        wo_id = _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)
        pipeline.gh.wo_acceptance_fail = True
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=sha,
        )
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="installed",
            version=version,
            build_sha=sha,
        )

        rc = closeout.run(_args(_config(isolates, version, sha, [number])))
        assert rc == 0
        view = wo.get_work_order(wo_id)
        assert view is not None and view["status"] == "closed"
        assert view["release_version"] == version

    def test_fail_reopen_fix_reaccept_updates_same_order(
        self, isolates: Path, pipeline: SimpleNamespace
    ) -> None:
        version = "1.0.0.2"
        sha = "b" * 40
        number = 902
        _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)

        # 阶段1：win 成功、mac 失败 → rejected → 重开原工单
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=sha,
        )
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="failed",
            version=version,
            build_sha=sha,
            error="launch crash",
        )
        rc1 = closeout.run(_args(_config(isolates, version, sha, [number])))
        assert rc1 == 0
        assert pipeline.gh.wo_acceptance_calls[-1]["verdict"] == "rejected"
        assert "acceptance-failed" in [
            label["name"] for label in pipeline.gh.issues[number]["labels"]
        ]

        # 阶段2：修复后 mac 成功、win 保持成功 → accepted → 同一工单再发验收
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="installed",
            version=version,
            build_sha=sha,
        )
        rc2 = closeout.run(_args(_config(isolates, version, sha, [number])))
        assert rc2 == 0
        assert pipeline.gh.wo_acceptance_calls[-1]["verdict"] == "accepted"
        assert len(pipeline.gh.wo_acceptance_calls) == 2

    def test_writeback_timeout_does_not_close(
        self, isolates: Path, pipeline: SimpleNamespace
    ) -> None:
        version = "1.0.0.3"
        sha = "c" * 40
        number = 903
        wo_id = _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=sha,
        )
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="installed",
            version=version,
            build_sha=sha,
        )
        pipeline.gh.fail_after = "/comments"

        rc = closeout.run(_args(_config(isolates, version, sha, [number])))

        # 回写失败 → 不推进工单（不得误报已验收）；运行器报错返回 1
        assert rc == 1
        assert wo.get_work_order(wo_id)["status"] != "closed"  # type: ignore[index]

    def test_repeated_receipts_idempotent(self, isolates: Path, pipeline: SimpleNamespace) -> None:
        version = "1.0.0.4"
        sha = "d" * 40
        number = 904
        wo_id = _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=sha,
        )
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="installed",
            version=version,
            build_sha=sha,
        )

        cfg = _config(isolates, version, sha, [number])
        assert closeout.run(_args(cfg)) == 0
        assert pipeline.gh.wo_acceptance_calls[-1]["verdict"] == "accepted"

        # 同一发布再跑一次（重复回执/重复 closeout）：不重复评论、结果稳定
        rc2 = closeout.run(_args(cfg))
        assert rc2 == 0
        assert pipeline.gh.comment_count == 1, "重复执行不得重复评论"
        assert len(pipeline.gh.wo_acceptance_calls) == 2, "label 幂等但验收落库保守重放"

    def test_different_build_does_not_pollute_acceptance(
        self, isolates: Path, pipeline: SimpleNamespace
    ) -> None:
        version = "1.0.0.5"
        released_sha = "e" * 40
        other_sha = "f" * 40
        number = 905
        wo_id = _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)

        # 发布构建 e 双平台健康；另有不同构建 f 的 mac 失败回执
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=released_sha,
        )
        pipeline.store.stage(
            install_id="dev-mac",
            platform="darwin",
            status="installed",
            version=version,
            build_sha=released_sha,
        )
        pipeline.store.stage(
            install_id="dev-mac-other",
            platform="darwin",
            status="failed",
            version=version,
            build_sha=other_sha,
            error="other build broken",
        )

        # 关联实际发布构建 SHA → 其他构建不参与 → accepted
        rc = closeout.run(_args(_config(isolates, version, released_sha, [number])))
        assert rc == 0
        assert pipeline.gh.wo_acceptance_calls[-1]["verdict"] == "accepted"
        assert wo.get_work_order(wo_id)["status"] != "closed"  # type: ignore[index] 远端权威

    def test_unrelated_build_failure_alone_stays_pending(
        self, isolates: Path, pipeline: SimpleNamespace
    ) -> None:
        version = "1.0.0.6"
        released_sha = "g" * 40
        other_sha = "h" * 40
        number = 906
        wo_id = _make_work_order(isolates, number)
        pipeline.gh.new_issue(number)

        # 仅发布构建 win 健康、mac 缺失；只有其它构建有失败 → 不含在发布构建内 → pending
        pipeline.store.stage(
            install_id="dev-win",
            platform="win32",
            status="installed",
            version=version,
            build_sha=released_sha,
        )
        pipeline.store.stage(
            install_id="dev-mac-other",
            platform="darwin",
            status="failed",
            version=version,
            build_sha=other_sha,
            error="other build broken",
        )

        rc = closeout.run(_args(_config(isolates, version, released_sha, [number])))
        assert rc == 0
        assert wo.get_work_order(wo_id)["status"] != "closed"  # type: ignore[index]
        assert pipeline.gh.comment_count == 0, "pending 不得回写/关闭"
