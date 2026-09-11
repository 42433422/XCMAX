"""主线闭环端到端测试：Signal Gate → 提案 → 工单 → 统一 Router → issue → 验收判定 → 关闭/重开。

目的不是覆盖单模块逻辑（各模块已有单测），而是证明跨模块接缝真实连通：
- record_capability_proposal 落提案的同时把候选需求升级为唯一工单（同一 wo_id）
- capability_proposal_to_issue 的分类与绑单把工单推进 routed 并持久化轨道
- capability_proposal_promote 的定制防污染门禁读取的是同一工单视图
- record_acceptance_verdict 把市场端双平台回执判定落回同一工单：
  accepted → closed；rejected → reopened（重开原单，不另起新单）

整改（2026-09-10 #1853 复审）新增集成口径：
- 从真实聊天入口（IntentConfirmationService）驱动到工单，验证闲聊/普通
  问答不派发开发任务、全程零网络（无 LLM/GitHub 调用）；
- 跨进程重启后工单状态从 JSONL 事件流恢复（真实持久化，非仅模块内视图）；
- 回执重放幂等、失败重开→修复→再验收的完整闭环；
- 验收回执网络超时时本地工单状态不被破坏。

全程不访问网络/GitHub：script 层只调用纯本地函数，GitHub 交互面不在本测试范围。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
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
        wo_id = wo.derive_wo_id(proposal["dedup_key"])
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


class TestRealConversationGate:
    """经实际会话入口（意图确认服务漏斗）验证真实闲聊/普通问答不建单。

    走 conversation 实际调用的 IntentConfirmationService.check_and_build_prompt，
    用真实句子（非空串）；仅 stub 开放世界技能增强（返回无技能路由），
    让漏斗的「非能力冲突 → unclear，不记录提案」分支被真实执行。
    """

    @pytest.fixture(autouse=True)
    def _no_skill_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """屏蔽开放世界技能路由：闲聊/问答没有技能提案信号。"""
        import app.domain.neuro.cognition.cognitive_orchestrator as ce

        def fake_factory() -> Any:
            class _Fake:
                def enrich_intent_result(
                    self, intent_result, *, text="", **_: Any
                ) -> dict[str, Any]:
                    return {"skill_route": None}

            return _Fake()

        monkeypatch.setattr(ce, "get_cognitive_orchestrator", fake_factory)

    @staticmethod
    def _no_work_order_or_proposal(tmp_path: Path) -> None:
        assert wo.list_work_orders() == [], "闲聊/问答不得产生工单"
        proposal_file = tmp_path / "capability_proposal.jsonl"
        assert not proposal_file.exists() or proposal_file.read_text().strip() == "", (
            "闲聊/问答不得落能力提案"
        )

    def test_real_chitchat_does_not_create_work_order(self, isolated_stores: Path) -> None:
        from app.services.intent_confirmation_service import get_confirmation_service

        result = get_confirmation_service().check_and_build_prompt(
            {
                "raw_input": "今天天气不错，你吃饭了吗？",
                "final_intent": "unk",
                "primary_intent": None,
                "tool_key": None,
                "slots": {},
            }
        )
        assert result["status"] == "unclear"
        assert result["intent"] is None
        self._no_work_order_or_proposal(isolated_stores)

    def test_real_qa_does_not_create_work_order(self, isolated_stores: Path) -> None:
        from app.services.intent_confirmation_service import get_confirmation_service

        result = get_confirmation_service().check_and_build_prompt(
            {
                "raw_input": "请问你们公司几点上班？",
                "final_intent": "unk",
                "primary_intent": None,
                "tool_key": None,
                "slots": {},
            }
        )
        assert result["status"] == "unclear"
        assert result["intent"] is None
        self._no_work_order_or_proposal(isolated_stores)


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
            # 显式 customer_scoped 才是定制信号；customer_id 仅用于归属
            context={"customer_id": "cust-001", "customer_scoped": True},
        )
        track = to_issue._classify_proposal_track(proposal)
        assert track == "customer_custom"
        to_issue._link_work_order(proposal, "https://github.com/acme/repo/issues/55", 55, track)

        blocked, reason = promote._custom_track_blocked(self._custom_issue([]), 55)
        assert blocked is True
        assert "custom-track-approved" in reason

    def test_customer_identity_alone_stays_generic(self, isolated_stores: Path) -> None:
        # 反例（#1851 整改）：已知客户的普通能力诉求不因身份字段进定制轨道
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="给我们厂单独做一个专属报表",
            reason="intent_unknown",
            context={"customer_id": "cust-001"},
        )
        assert to_issue._classify_proposal_track(proposal) == "product_line"

    def test_custom_track_allowed_with_approval_label(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores,
            raw_input="给我们厂单独做一个专属报表",
            reason="intent_unknown",
            context={"customer_id": "cust-001", "customer_scoped": True},
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

    _HEALTHY = {
        "per_platform": {
            "win": {"installed": 1, "failed": 0, "devices": 1},
            "mac": {"installed": 1, "failed": 0, "devices": 1},
        }
    }

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
        return wo.derive_wo_id(proposal["dedup_key"])

    def _drive_to_verifying(self, wo_id: str) -> None:
        # 完成阶段由各自证据驱动（开发/合并/发布），回执只判定
        for state in ("in_dev", "merged", "released", "verifying"):
            assert wo.record_transition(wo_id, state)["ok"] is True

    def test_accepted_closes_same_work_order(self, isolated_stores: Path) -> None:
        wo_id = self._routed_wo(isolated_stores, 201)
        self._drive_to_verifying(wo_id)
        result = wo.record_acceptance_verdict(
            issue_number=201,
            release_version="1.2.3.4",
            verdict="accepted",
            evidence=dict(self._HEALTHY),
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
        self._drive_to_verifying(wo_id)
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

    def test_pending_verdict_does_not_close_or_advance(self, isolated_stores: Path) -> None:
        wo_id = self._routed_wo(isolated_stores, 203)
        before = wo.get_work_order(wo_id)
        assert before is not None
        before_events = list(before["history"])
        result = wo.record_acceptance_verdict(
            issue_number=203, release_version="1.2.3.4", verdict="pending"
        )
        assert result["ok"] is False
        view = wo.get_work_order(wo_id)
        assert view is not None
        assert view["status"] != "closed"  # type: ignore[index]
        assert view["status"] == "routed", "pending 回执不得把 routed 推进到完成阶段"
        assert view["history"] == before_events, "pending 回执不得改写历史"

    def test_verdict_for_unlinked_issue_is_noop(self, isolated_stores: Path) -> None:
        result = wo.record_acceptance_verdict(
            issue_number=999, release_version="1.2.3.4", verdict="rejected"
        )
        assert result["ok"] is False
        assert result["reason"] == "issue_not_linked"


@pytest.fixture
def network_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试期间禁网：任何 TCP 连接（LLM/GitHub/市场端）都视为测试缺陷。"""

    def _no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("测试期间禁止任何网络调用（昂贵 LLM/编码任务不允许被触发）")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_network)


class TestRealChatEntryToWorkOrder:
    """真实聊天入口 → 工单：闲聊/普通问答不派发开发任务，全程零网络。"""

    def _service(self) -> Any:
        from app.services.intent_confirmation_service import IntentConfirmationService

        return IntentConfirmationService()

    def test_greeting_recognized_intent_never_creates_work_order(
        self, isolated_stores: Path, network_disabled: None
    ) -> None:
        result = self._service().check_and_build_prompt(
            {"final_intent": "greeting", "is_greeting": True, "slots": {}, "raw_input": "你好"}
        )
        assert result["status"] in {"complete", "missing_slots", "unclear"}
        assert recorder.list_pending_proposals() == []
        assert wo.list_work_orders() == [], "已识别的问候不得进入工单系统"

    def test_normal_qa_with_confident_intent_never_creates_work_order(
        self, isolated_stores: Path, network_disabled: None
    ) -> None:
        result = self._service().check_and_build_prompt(
            {
                "final_intent": "inventory_query",
                "confidence": 0.97,
                "slots": {"warehouse": "主仓"},
                "raw_input": "主仓现在还有多少库存",
            }
        )
        assert result["status"] in {"complete", "missing_slots"}
        assert wo.list_work_orders() == [], "高置信普通问答不得派发开发任务"

    def test_capability_gap_from_chat_creates_single_candidate(
        self, isolated_stores: Path, network_disabled: None
    ) -> None:
        result = self._service().check_and_build_prompt(
            {
                "raw_input": "我想按客户维度批量导出对账单",
                "slots": {},
            }
        )
        # 真实入口产出的提案必须同步升级出唯一候选工单
        assert wo.list_work_orders(), "开放世界缺口应被记录为候选工单"
        orders = wo.list_work_orders()
        assert all(o["status"] == "candidate" for o in orders)
        # 隐私接缝：context 只携带字段名，不携带用户原文/业务值
        record = json.loads(
            (isolated_stores / "capability_proposal.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[-1]
        )
        assert record["raw_input"].startswith("我想按客户维度")
        assert "slot_names" in (record.get("context") or {}).get("intent_result", {})

    def test_chit_chat_proposal_never_dispatches_without_owner_approval(
        self, isolated_stores: Path, network_disabled: None
    ) -> None:
        # 未识别闲聊最多形成候选提案；派发必须过 owner 批准门禁
        self._service().check_and_build_prompt({"raw_input": "你好呀，在吗", "slots": {}})
        issue = {
            "number": 66,
            "state": "open",
            "labels": [
                {"name": "capability-proposal"},
                {"name": "auto-generated"},
                {"name": "needs-human"},
            ],
            "title": "[capability-proposal] 新能力候选 x",
            "body": "来源：能力提案 (capability_proposal)\n## 结构化上下文\n## 治理门禁",
        }
        non_owner_comment = {"author_association": "NONE", "body": "确认实现"}
        valid, reason = promote._validate_promotion(issue, non_owner_comment, issue_number=66)
        assert valid is False, "无 owner 批准评论不得派发实现工作流"
        assert "owner" in reason
        # 未经派发，工单不得离开 candidate
        for order in wo.list_work_orders():
            assert order["status"] == "candidate"


class TestServiceRestartPersistence:
    """跨服务重启：工单状态必须从 JSONL 事件流恢复（真实进程重启）。"""

    _CHILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from app.services import work_order_ssot as wo
if sys.argv[2] == "write":
    wo_id = wo.upsert_candidate(source="chat", dedup_key="restart-key", reason="llm_timeout")["wo_id"]
    wo.record_transition(wo_id, "routed")
    print(wo_id)
else:
    view = wo.get_work_order(sys.argv[3])
    print(json.dumps({"status": view["status"], "track": view["track"]}))
"""

    def test_state_survives_process_restart(self, tmp_path: Path) -> None:
        store = tmp_path / "store"
        env = {**os.environ, "WORK_ORDER_SSOT_DIR": str(store)}

        def run_child(mode: str, wo_id: str = "") -> str:
            proc = subprocess.run(
                [sys.executable, "-c", self._CHILD, str(_FHD_ROOT), mode, wo_id],
                capture_output=True,
                text=True,
                cwd=str(_FHD_ROOT),
                env=env,
                timeout=120,
            )
            assert proc.returncode == 0, f"子进程失败: {proc.stderr[-800:]}"
            return proc.stdout.strip().splitlines()[-1]

        wo_id = run_child("write")
        assert wo._WO_ID_RE.match(wo_id)
        # 新进程（重启）只依赖同一 JSONL 存储读取，不依赖原进程内存
        restored = json.loads(run_child("read", wo_id))
        assert restored["status"] == "routed"
        assert restored["track"] == "ops_support", "重启后轨道必须随事件流恢复"

    def test_events_file_survives_crash_after_write(self, tmp_path: Path) -> None:
        store = tmp_path / "store"
        env = {**os.environ, "WORK_ORDER_SSOT_DIR": str(store)}
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from app.services import work_order_ssot as wo;"
            "print(wo.upsert_candidate(source='chat', dedup_key='crash-key', reason='r')['wo_id'])"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script, str(_FHD_ROOT)],
            capture_output=True,
            text=True,
            cwd=str(_FHD_ROOT),
            env=env,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        wo_id = proc.stdout.strip().splitlines()[-1]
        events = (store / "work_orders.jsonl").read_text(encoding="utf-8").strip()
        assert wo_id in events, "写入即落盘（fsync），崩溃不丢已写入事件"


class TestReopenReacceptLoop:
    """失败重开 → 修复 → 再验收的完整闭环（同一 wo_id）。"""

    def test_fail_reopen_then_reaccept_closes(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores, raw_input="闭环回归需求", reason="intent_unknown", context={}
        )
        wo_id = wo.derive_wo_id(proposal["dedup_key"])
        to_issue._link_work_order(proposal, "https://x/310", 310, "product_line")
        for state in ("in_dev", "merged", "released", "verifying"):
            wo.record_transition(wo_id, state)
        first = wo.record_acceptance_verdict(
            issue_number=310, release_version="1.0.0", verdict="rejected"
        )
        assert first["ok"] is True
        assert wo.get_work_order(wo_id)["status"] == "reopened"  # type: ignore[index]
        # 修复后沿原主线重新走完完成阶段（回执不再替开发/合并/发布补状态）
        for state in ("in_dev", "merged", "released", "verifying"):
            assert wo.record_transition(wo_id, state)["ok"] is True
        second = wo.record_acceptance_verdict(
            issue_number=310,
            release_version="1.0.1",
            verdict="accepted",
            evidence={
                "per_platform": {
                    "win": {"installed": 1, "failed": 0, "devices": 1},
                    "mac": {"installed": 1, "failed": 0, "devices": 1},
                }
            },
        )
        assert second["ok"] is True
        view = wo.get_work_order(wo_id)
        assert view["status"] == "closed"  # type: ignore[index]
        assert view["wo_id"] == wo_id, "重开再验收仍是原单"  # type: ignore[index]
        # 两次验收之间不得有重复关闭事件
        closed_events = [
            e for e in view["history"] if e.get("event") == "transition" and e.get("to") == "closed"
        ]
        assert len(closed_events) == 1

    def test_receipt_replay_is_idempotent(self, isolated_stores: Path) -> None:
        proposal = _record_and_read_back(
            isolated_stores, raw_input="重放回归需求", reason="intent_unknown", context={}
        )
        wo_id = wo.derive_wo_id(proposal["dedup_key"])
        to_issue._link_work_order(proposal, "https://x/311", 311, "product_line")
        for state in ("in_dev", "merged", "released", "verifying"):
            wo.record_transition(wo_id, state)
        evidence = {
            "per_platform": {
                "win": {"installed": 1, "failed": 0, "devices": 1},
                "mac": {"installed": 1, "failed": 0, "devices": 1},
            }
        }
        first = wo.record_acceptance_verdict(
            issue_number=311, release_version="1.0.0", verdict="accepted", evidence=evidence
        )
        assert first["ok"] is True
        count_after_first = len(wo.get_work_order(wo_id)["history"])  # type: ignore[index]
        for _ in range(2):
            replay = wo.record_acceptance_verdict(
                issue_number=311, release_version="1.0.0", verdict="accepted", evidence=evidence
            )
            assert replay["ok"] is True
            assert replay["reason"] == "already_closed"
        assert len(wo.get_work_order(wo_id)["history"]) == count_after_first  # type: ignore[index]


class TestCloseoutNetworkTimeout:
    """验收回执网络超时：脚本失败但本地工单状态不被破坏。"""

    def test_market_timeout_leaves_work_order_untouched(
        self, isolated_stores: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closeout = _load_script("release_acceptance_closeout")
        proposal = _record_and_read_back(
            isolated_stores, raw_input="超时回归需求", reason="intent_unknown", context={}
        )
        wo_id = wo.derive_wo_id(proposal["dedup_key"])
        to_issue._link_work_order(proposal, "https://x/320", 320, "product_line")
        for state in ("in_dev", "merged", "released", "verifying"):
            wo.record_transition(wo_id, state)
        before = wo.get_work_order(wo_id)
        assert before is not None
        before_events = list(before["history"])

        config = tmp_path / "release_config.json"
        config.write_text(json.dumps({"version_lock": "1.0.0", "linked_issues": [320]}))
        args = argparse.Namespace(
            repo="acme/repo",
            token="t",
            market_base="https://market.invalid",
            market_token="m",
            release_config=str(config),
            version="",
            channel="stable",
            dry_run=False,
            apply=True,
        )

        def _timeout(*a: Any, **k: Any) -> Any:
            raise TimeoutError("connection timed out")

        # 打在 urlopen 底层，让 closeout._http 的网络异常兜底走真实路径
        monkeypatch.setattr("urllib.request.urlopen", _timeout)
        assert closeout.run(args) == 1, "网络超时必须以失败退出，不得静默成功"
        after = wo.get_work_order(wo_id)
        assert after is not None
        assert after["status"] == "verifying"
        assert after["history"] == before_events, "超时不得改写本地工单历史"
