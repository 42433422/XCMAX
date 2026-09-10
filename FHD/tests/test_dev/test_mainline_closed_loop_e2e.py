"""主线闭环端到端测试：Signal Gate → 提案 → 工单 → 统一 Router → issue → 验收判定 → 关闭/重开。

目的不是覆盖单模块逻辑（各模块已有单测），而是证明跨模块接缝真实连通：
- record_capability_proposal 落提案的同时把候选需求升级为唯一工单（同一 wo_id）
- capability_proposal_to_issue 的分类与绑单把工单推进 routed 并持久化轨道
- capability_proposal_promote 的定制防污染门禁读取的是同一工单视图
- record_acceptance_verdict 把市场端双平台回执判定落回同一工单：
  accepted → closed；rejected → reopened（重开原单，不另起新单）

全程不访问网络/GitHub：script 层只调用纯本地函数，GitHub 交互面不在本测试范围。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.services import capability_proposal_recorder as recorder
from app.services import work_order_ssot as wo

_FHD_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str) -> Any:
    path = _FHD_ROOT / "scripts" / "dev" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


to_issue = _load_script("capability_proposal_to_issue")
promote = _load_script("capability_proposal_promote")


@pytest.fixture
def isolated_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """提案与工单事件流都隔离到 tmp_path，互不影响也不碰真实仓库数据。"""
    monkeypatch.setattr(recorder, "_REPORT_DIR", tmp_path)
    monkeypatch.setattr(recorder, "_PROPOSAL_FILE", tmp_path / "capability_proposal.jsonl")
    monkeypatch.setattr(
        recorder, "_PROCESSED_FILE", tmp_path / "capability_proposal_processed.jsonl"
    )
    monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")
    return tmp_path


def _record_and_read_back(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    """经 Signal Gate 出口记录提案，并按 relay 真实方式从 JSONL 读回。"""
    result = recorder.record_capability_proposal(**kwargs)
    assert result["recorded"] is True
    line = (tmp_path / "capability_proposal.jsonl").read_text(encoding="utf-8").strip()
    record: dict[str, Any] = json.loads(line.splitlines()[-1])
    return record


class TestSignalToWorkOrder:
    """Signal Gate → 提案去重聚合 → 唯一工单 ID（前端接缝）。"""

    def test_proposal_auto_upgrades_to_work_order(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="我们涂料厂需要按批次追溯原料",
            reason="intent_unknown",
            context={"intent_result": {"industry": "涂料"}},
        )
        wo_id = wo.derive_wo_id(proposal["source"], proposal["dedup_key"])
        view = wo.get_work_order(wo_id)
        assert view is not None, "提案落盘必须同步升级出唯一工单"
        assert view["status"] == "candidate"
        assert view["dedup_key"] == proposal["dedup_key"]

    def test_duplicate_proposal_does_not_create_second_order(self, isolated_stores: Path) -> None:
        kwargs: dict[str, Any] = {
            "raw_input": "同一个需求说两遍",
            "reason": "intent_unknown",
            "context": {},
        }
        _record_and_read_back(isolated_stores, **kwargs)
        second = recorder.record_capability_proposal(**kwargs)
        assert second["reason"] == "duplicate"
        assert len(wo.list_work_orders()) == 1, "去重命中不得另起工单"

    def test_empty_input_never_creates_work_order(self, isolated_stores: Path) -> None:
        result = recorder.record_capability_proposal(raw_input="   ", reason="intent_unknown")
        assert result["recorded"] is False
        assert wo.list_work_orders() == [], "闲聊/空输入必须挡在工单系统之外"


class TestRouterToIssue:
    """统一 Router → issue 绑定（候选期终点）。"""

    def test_industry_proposal_routed_with_track(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="涂料行业需要批次追溯",
            reason="intent_unknown",
            context={"intent_result": {"industry": "涂料"}},
        )
        track = to_issue._classify_proposal_track(proposal)
        assert track == "industry_mod"

        to_issue._link_work_order(proposal, "https://github.com/acme/repo/issues/123", 123, track)
        view = wo.find_by_issue(123)
        assert view is not None, "issue 绑定后必须能反查工单"
        assert view["status"] == "routed"
        assert view["track"] == "industry_mod"

    def test_ops_reason_classified_as_ops_support(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="刚才服务又超时了",
            reason="llm_timeout",
            context={},
        )
        assert to_issue._classify_proposal_track(proposal) == "ops_support"

    def test_default_track_is_product_line(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="希望支持批量导出报表",
            reason="intent_unknown",
            context={},
        )
        assert to_issue._classify_proposal_track(proposal) == "product_line"


class TestCustomTrackGate:
    """定制防污染：单客户定制无批准标签不得派发进主线。"""

    def _custom_issue(self, labels: list[str]) -> dict[str, Any]:
        return {"number": 55, "labels": [{"name": n} for n in labels]}

    def test_custom_track_blocked_without_approval(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="给我们厂单独做一个专属报表",
            reason="intent_unknown",
            context={"customer_id": "cust-001"},
        )
        track = to_issue._classify_proposal_track(proposal)
        assert track == "customer_custom"
        to_issue._link_work_order(proposal, "https://github.com/acme/repo/issues/55", 55, track)

        blocked, reason = promote._custom_track_blocked(self._custom_issue([]), 55)
        assert blocked is True
        assert "custom-track-approved" in reason

    def test_custom_track_allowed_with_approval_label(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="给我们厂单独做一个专属报表",
            reason="intent_unknown",
            context={"customer_id": "cust-001"},
        )
        to_issue._link_work_order(
            proposal,
            "https://github.com/acme/repo/issues/55",
            55,
            to_issue._classify_proposal_track(proposal),
        )
        blocked, _ = promote._custom_track_blocked(
            self._custom_issue(["custom-track-approved"]), 55
        )
        assert blocked is False

    def test_product_line_track_not_blocked(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="希望支持批量导出报表",
            reason="intent_unknown",
            context={},
        )
        to_issue._link_work_order(
            proposal, "https://github.com/acme/repo/issues/56", 56, "product_line"
        )
        blocked, _ = promote._custom_track_blocked(self._custom_issue([]), 56)
        assert blocked is False


class TestAcceptanceCloseout:
    """验收后半段：双平台回执判定落回同一工单（同一 wo_id 贯穿到底）。"""

    def _routed_wo(self, tmp_path: Path, issue_number: int) -> str:
        proposal = _record_and_read_back(
            tmp_path,
            raw_input=f"需求-{issue_number}",
            reason="intent_unknown",
            context={},
        )
        to_issue._link_work_order(
            proposal,
            f"https://github.com/acme/repo/issues/{issue_number}",
            issue_number,
            "product_line",
        )
        return wo.derive_wo_id(proposal["source"], proposal["dedup_key"])

    def test_accepted_closes_same_work_order(self, isolated_stores: Path) -> None:
        wo_id = self._routed_wo(isolated_stores, 201)
        result = wo.record_acceptance_verdict(
            issue_number=201,
            release_version="1.2.3.4",
            verdict="accepted",
            evidence={"per_platform": {"win": {"installed": 1}, "mac": {"installed": 1}}},
        )
        assert result["ok"] is True
        view = wo.get_work_order(wo_id)
        assert view is not None
        assert view["status"] == "closed"
        assert view["release_version"] == "1.2.3.4"
        # 同一 wo_id 贯穿：时间线含 candidate → routed → … → verifying → closed
        states = [view["history"][0]["event"]]
        states += [e.get("to") for e in view["history"] if e.get("event") == "transition"]
        assert states[0] == "created"
        assert "routed" in states and states[-1] == "closed"

    def test_rejected_reopens_original_work_order(self, isolated_stores: Path) -> None:
        wo_id = self._routed_wo(isolated_stores, 202)
        result = wo.record_acceptance_verdict(
            issue_number=202,
            release_version="1.2.3.4",
            verdict="rejected",
            evidence={"failures": [{"platform": "win", "status": "failed"}]},
        )
        assert result["ok"] is True
        view = wo.get_work_order(wo_id)
        assert view is not None
        assert view["status"] == "reopened", "失败必须重开原单，不另起新单"
        # 重开后允许回到 in_dev 继续修，闭环直到关闭
        moved = wo.record_transition(wo_id, "in_dev", note="修复后重新开发")
        assert moved["ok"] is True
        assert wo.get_work_order(wo_id)["status"] == "in_dev"  # type: ignore[index]

    def test_pending_verdict_does_not_close(self, isolated_stores: Path) -> None:
        wo_id = self._routed_wo(isolated_stores, 203)
        result = wo.record_acceptance_verdict(
            issue_number=203, release_version="1.2.3.4", verdict="pending"
        )
        assert result["ok"] is False
        assert wo.get_work_order(wo_id)["status"] != "closed"  # type: ignore[index]

    def test_verdict_for_unlinked_issue_is_noop(self, isolated_stores: Path) -> None:
        result = wo.record_acceptance_verdict(
            issue_number=999, release_version="1.2.3.4", verdict="rejected"
        )
        assert result["ok"] is False
        assert result["reason"] == "issue_not_linked"
