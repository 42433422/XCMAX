"""work_order_ssot 单元测试。

覆盖：
- wo_id 幂等派生（同 source+dedup_key 同 ID）
- upsert_candidate 幂等（重复升级不重复建单）
- 状态机合法/非法迁移（含 reopened 不另起新单）
- link_issue 与 find_by_issue 反查
- record_acceptance_verdict：accepted→closed / rejected→reopened
- 事件流折叠视图与 list_work_orders 过滤
- 统一 Router：classify_track 四类去向规则、routed 迁移强制携带轨道、
  缺省自动分类、非法轨道拒绝
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import work_order_ssot as wo


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个测试用独立事件流文件，避免污染彼此。"""
    monkeypatch.setenv("WORK_ORDER_SSOT_DIR", str(tmp_path))
    monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")
    return wo._EVENTS_FILE


class TestDeriveWoId:
    def test_same_input_same_id(self) -> None:
        assert wo.derive_wo_id("s", "k") == wo.derive_wo_id("s", "k")

    def test_different_source_different_id(self) -> None:
        assert wo.derive_wo_id("a", "k") != wo.derive_wo_id("b", "k")

    def test_id_format(self) -> None:
        assert wo._WO_ID_RE.match(wo.derive_wo_id("s", "k"))


class TestUpsertCandidate:
    def test_create_then_dedup(self, isolated_store: Path) -> None:
        first = wo.upsert_candidate(source="intent", dedup_key="k1", reason="skill_proposal")
        assert first["created"] is True
        assert first["status"] == "candidate"
        second = wo.upsert_candidate(source="intent", dedup_key="k1", reason="skill_proposal")
        assert second["created"] is False
        assert second["wo_id"] == first["wo_id"]

    def test_empty_dedup_key_rejected(self, isolated_store: Path) -> None:
        result = wo.upsert_candidate(source="s", dedup_key="", reason="r")
        assert result["created"] is False
        assert result["reason"] == "empty_dedup_key"


class TestStateMachine:
    def _make_candidate(self, key: str = "k1") -> str:
        return wo.upsert_candidate(source="s", dedup_key=key, reason="r")["wo_id"]

    def test_happy_path_to_closed(self, isolated_store: Path) -> None:
        wo_id = self._make_candidate()
        assert wo.record_transition(wo_id, "routed")["ok"] is True
        assert wo.record_transition(wo_id, "in_dev")["ok"] is True
        assert wo.record_transition(wo_id, "merged")["ok"] is True
        assert wo.record_transition(wo_id, "released")["ok"] is True
        assert wo.record_transition(wo_id, "verifying")["ok"] is True
        assert wo.record_transition(wo_id, "closed")["ok"] is True
        assert wo.get_work_order(wo_id)["status"] == "closed"

    def test_invalid_transition_rejected(self, isolated_store: Path) -> None:
        wo_id = self._make_candidate()
        result = wo.record_transition(wo_id, "closed")
        assert result["ok"] is False
        assert result["reason"] == "invalid_transition"
        assert wo.get_work_order(wo_id)["status"] == "candidate"

    def test_unknown_state_rejected(self, isolated_store: Path) -> None:
        wo_id = self._make_candidate()
        assert wo.record_transition(wo_id, "flying")["ok"] is False

    def test_unknown_work_order_rejected(self, isolated_store: Path) -> None:
        result = wo.record_transition("WO-000000000000", "routed")
        assert result["ok"] is False
        assert result["reason"] == "unknown_work_order"

    def test_reopen_goes_back_to_in_dev(self, isolated_store: Path) -> None:
        """失败重开原工单回到开发线，不另起新单。"""
        wo_id = self._make_candidate()
        for state in ("routed", "in_dev", "merged", "released", "verifying"):
            wo.record_transition(wo_id, state)
        assert wo.record_transition(wo_id, "reopened")["ok"] is True
        assert wo.record_transition(wo_id, "in_dev")["ok"] is True
        view = wo.get_work_order(wo_id)
        assert view["status"] == "in_dev"
        assert view["wo_id"] == wo_id  # 同一主 ID

    def test_idempotent_same_state(self, isolated_store: Path) -> None:
        wo_id = self._make_candidate()
        result = wo.record_transition(wo_id, "candidate")
        assert result["ok"] is True
        assert result["reason"] == "already_in_state"


class TestIssueLink:
    def test_link_and_reverse_lookup(self, isolated_store: Path) -> None:
        wo_id = wo.upsert_candidate(source="s", dedup_key="k9", reason="r")["wo_id"]
        result = wo.link_issue(wo_id, issue_number=123, issue_url="https://x/123")
        assert result["ok"] is True
        view = wo.find_by_issue(123)
        assert view is not None
        assert view["wo_id"] == wo_id
        assert view["status"] == "routed"
        assert view["issue_url"] == "https://x/123"

    def test_find_by_issue_missing(self, isolated_store: Path) -> None:
        assert wo.find_by_issue(999) is None


class TestAcceptanceVerdict:
    def _make_verifying(self) -> str:
        wo_id = wo.upsert_candidate(source="s", dedup_key="kv", reason="r")["wo_id"]
        wo.link_issue(wo_id, issue_number=77, issue_url="https://x/77")
        wo.record_transition(wo_id, "in_dev")
        return wo_id

    def test_accepted_closes(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying()
        result = wo.record_acceptance_verdict(
            issue_number=77, release_version="1.0.0.2", verdict="accepted"
        )
        assert result["ok"] is True
        assert result["to"] == "closed"
        view = wo.get_work_order(wo_id)
        assert view["status"] == "closed"
        assert view["release_version"] == "1.0.0.2"

    def test_rejected_reopens_original(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying()
        result = wo.record_acceptance_verdict(
            issue_number=77,
            release_version="1.0.0.2",
            verdict="rejected",
            evidence={"failed": 2},
        )
        assert result["ok"] is True
        assert result["to"] == "reopened"
        # 重开后可回到 in_dev 继续主线，工单 ID 不变
        assert wo.record_transition(wo_id, "in_dev")["ok"] is True
        assert wo.get_work_order(wo_id)["wo_id"] == wo_id

    def test_pending_verdict_not_recorded(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying()
        result = wo.record_acceptance_verdict(
            issue_number=77, release_version="1.0.0.2", verdict="pending"
        )
        assert result["ok"] is False
        assert result["reason"] == "verdict_pending"
        # pending 不得自动补写开发/合并/发布完成状态：工单保持原 in_dev
        view = wo.get_work_order(wo_id)
        assert view["status"] == "in_dev"
        to_states = [e.get("to") for e in view["history"] if e.get("event") == "transition"]
        assert "merged" not in to_states
        assert "released" not in to_states
        assert "verifying" not in to_states

    def test_unlinked_issue_rejected(self, isolated_store: Path) -> None:
        result = wo.record_acceptance_verdict(
            issue_number=404, release_version="1.0.0.2", verdict="accepted"
        )
        assert result["ok"] is False
        assert result["reason"] == "issue_not_linked"


class TestListWorkOrders:
    def test_filter_and_order(self, isolated_store: Path) -> None:
        a = wo.upsert_candidate(source="s", dedup_key="ka", reason="r")["wo_id"]
        wo.upsert_candidate(source="s", dedup_key="kb", reason="r")
        wo.record_transition(a, "routed")
        routed = wo.list_work_orders(status="routed")
        assert [v["wo_id"] for v in routed] == [a]
        all_orders = wo.list_work_orders()
        assert len(all_orders) == 2
        assert all_orders[0]["wo_id"] == a  # 最新更新的在前

    def test_history_preserved(self, isolated_store: Path) -> None:
        wo_id = wo.upsert_candidate(source="s", dedup_key="kh", reason="r")["wo_id"]
        wo.record_transition(wo_id, "routed", note="升级为 issue")
        view = wo.get_work_order(wo_id)
        events = [h["event"] for h in view["history"]]
        assert events == ["created", "transition"]


class TestClassifyTrack:
    """统一 Router 四类去向的确定性规则。"""

    def test_default_is_product_line(self) -> None:
        # 无法证明属于其他轨道 → 通用产品线（只有通用能力进入主产品）
        assert wo.classify_track(reason="intent_unknown") == "product_line"
        assert wo.classify_track() == "product_line"

    def test_ops_reasons_route_to_ops_support(self) -> None:
        assert wo.classify_track(reason="llm_timeout") == "ops_support"
        assert wo.classify_track(reason="install_failed") == "ops_support"

    def test_ops_reason_with_customer_id_stays_ops(self) -> None:
        # 带客户标识的普通故障仍是运维问题，不得因此自动归入客户定制
        track = wo.classify_track(reason="llm_timeout", context={"customer_id": "c-1"})
        assert track == "ops_support"

    def test_bare_customer_id_without_ops_is_custom(self) -> None:
        # 无运维故障、仅显式客户作用域 → 单客户定制
        assert wo.classify_track(context={"customer_id": "c-1"}) == "customer_custom"
        assert wo.classify_track(context={"account_id": "a-1"}) == "customer_custom"

    def test_industry_signal_routes_to_industry_mod(self) -> None:
        assert wo.classify_track(context={"industry": "涂料"}) == "industry_mod"
        ctx = {"intent_result": {"industry": "涂料"}}
        assert wo.classify_track(context=ctx) == "industry_mod"
        ctx2 = {"skill_proposal": {"industry": "考勤"}}
        assert wo.classify_track(context=ctx2) == "industry_mod"

    def test_customer_scoped_in_skill_proposal(self) -> None:
        ctx = {"skill_proposal": {"customer_scoped": True, "industry": "涂料"}}
        assert wo.classify_track(context=ctx) == "customer_custom"


class TestRouterTrackGate:
    """routed 迁移必须携带合法轨道；缺省自动分类。"""

    def test_routed_auto_classifies_from_created_event(self, isolated_store: Path) -> None:
        wo_id = wo.upsert_candidate(source="s", dedup_key="kt", reason="llm_timeout")["wo_id"]
        result = wo.record_transition(wo_id, "routed")
        assert result["ok"] is True
        assert wo.get_work_order(wo_id)["track"] == "ops_support"

    def test_routed_explicit_track_preserved(self, isolated_store: Path) -> None:
        wo_id = wo.upsert_candidate(source="s", dedup_key="kt2", reason="r")["wo_id"]
        result = wo.link_issue(wo_id, issue_number=7, issue_url="https://x/7", track="industry_mod")
        assert result["ok"] is True
        view = wo.get_work_order(wo_id)
        assert view["status"] == "routed"
        assert view["track"] == "industry_mod"

    def test_routed_rejects_unknown_track(self, isolated_store: Path) -> None:
        wo_id = wo.upsert_candidate(source="s", dedup_key="kt3", reason="r")["wo_id"]
        result = wo.record_transition(wo_id, "routed", ref={"track": "sidestreet"})
        assert result["ok"] is False
        assert result["reason"] == "unknown_track"
        assert wo.get_work_order(wo_id)["status"] == "candidate"

    def test_track_survives_later_transitions(self, isolated_store: Path) -> None:
        wo_id = wo.upsert_candidate(source="s", dedup_key="kt4", reason="r")["wo_id"]
        wo.link_issue(wo_id, issue_number=9, issue_url="u", track="customer_custom")
        wo.record_transition(wo_id, "in_dev")
        assert wo.get_work_order(wo_id)["track"] == "customer_custom"
