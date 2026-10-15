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
        assert wo.derive_wo_id("k") == wo.derive_wo_id("k")

    def test_same_requirement_from_different_sources_same_id(self) -> None:
        # 整改（#1851）：同一需求从不同入口进来必须合并到同一工单
        assert wo.derive_wo_id("k") == wo.derive_wo_id("k")

    def test_different_requirement_different_id(self) -> None:
        assert wo.derive_wo_id("k1") != wo.derive_wo_id("k2")

    def test_id_format(self) -> None:
        assert wo._WO_ID_RE.match(wo.derive_wo_id("k"))


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
    """验收回执判定：只判定不补状态（2026-09-10 #1853 复审整改）。"""

    def _make_verifying(self, issue: int = 77) -> str:
        wo_id = wo.upsert_candidate(source="s", dedup_key=f"kv{issue}", reason="r")["wo_id"]
        wo.link_issue(wo_id, issue_number=issue, issue_url=f"https://x/{issue}")
        # 完成阶段必须由对应证据驱动：逐段显式推进到 verifying
        for state in ("in_dev", "merged", "released", "verifying"):
            assert wo.record_transition(wo_id, state)["ok"] is True
        return wo_id

    _HEALTHY = {
        "per_platform": {
            "win": {"installed": 2, "failed": 0, "devices": 2},
            "mac": {"installed": 1, "failed": 0, "devices": 1},
        }
    }

    def test_accepted_closes(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying()
        result = wo.record_acceptance_verdict(
            issue_number=77,
            release_version="1.0.0.2",
            verdict="accepted",
            evidence=dict(self._HEALTHY),
        )
        assert result["ok"] is True
        assert result["to"] == "closed"
        view = wo.get_work_order(wo_id)
        assert view["status"] == "closed"
        assert view["release_version"] == "1.0.0.2"

    def test_accepted_from_released_single_step_correction(self, isolated_store: Path) -> None:
        # released → verifying 允许回执驱动的单步校正（事件带明确标记）
        wo_id = wo.upsert_candidate(source="s", dedup_key="kv-rel", reason="r")["wo_id"]
        wo.link_issue(wo_id, issue_number=78, issue_url="https://x/78")
        for state in ("in_dev", "merged", "released"):
            assert wo.record_transition(wo_id, state)["ok"] is True
        result = wo.record_acceptance_verdict(
            issue_number=78,
            release_version="1.0.0.2",
            verdict="accepted",
            evidence=dict(self._HEALTHY),
        )
        assert result["ok"] is True
        view = wo.get_work_order(wo_id)
        assert view["status"] == "closed"
        correction = [
            e
            for e in view["history"]
            if e.get("event") == "transition" and e.get("to") == "verifying"
        ]
        assert correction and "校正" in str(correction[0].get("note")), (
            "起点校正必须明确标记，不得当作开发/合并动作真实发生"
        )

    def test_rejected_reopens_original(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying()
        result = wo.record_acceptance_verdict(
            issue_number=77,
            release_version="1.0.0.2",
            verdict="rejected",
            evidence={"per_platform": {"win": {"installed": 1, "failed": 1}, "mac": {}}},
        )
        assert result["ok"] is True
        assert result["to"] == "reopened"
        # 重开后可回到 in_dev 继续主线，工单 ID 不变
        assert wo.record_transition(wo_id, "in_dev")["ok"] is True
        assert wo.get_work_order(wo_id)["wo_id"] == wo_id

    def test_pending_verdict_never_advances_or_rewrites(self, isolated_store: Path) -> None:
        # 反例（#1853）：routed 工单收到 pending 不得被推进到 verifying
        wo_id = wo.upsert_candidate(source="s", dedup_key="kp", reason="r")["wo_id"]
        wo.link_issue(wo_id, issue_number=79, issue_url="https://x/79")
        before = wo.get_work_order(wo_id)
        assert before is not None
        before_events = list(before["history"])
        result = wo.record_acceptance_verdict(
            issue_number=79, release_version="1.0.0.2", verdict="pending"
        )
        assert result["ok"] is False
        assert result["reason"] == "verdict_pending"
        after = wo.get_work_order(wo_id)
        assert after is not None
        assert after["status"] == "routed", "pending 不得推进任何完成阶段"
        assert after["history"] == before_events, "pending 不得改写历史"

    def test_receipt_from_routed_refused_without_backfill(self, isolated_store: Path) -> None:
        # 完成阶段必须由开发/合并/发布证据驱动，回执不得补齐
        wo_id = wo.upsert_candidate(source="s", dedup_key="kr", reason="r")["wo_id"]
        wo.link_issue(wo_id, issue_number=80, issue_url="https://x/80")
        result = wo.record_acceptance_verdict(
            issue_number=80,
            release_version="1.0.0.2",
            verdict="accepted",
            evidence=dict(self._HEALTHY),
        )
        assert result["ok"] is False
        assert result["reason"] == "not_in_acceptance_window"
        assert wo.get_work_order(wo_id)["status"] == "routed"  # type: ignore[index]

    def test_accepted_without_release_identity_refused(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying(issue=81)
        result = wo.record_acceptance_verdict(
            issue_number=81, release_version="", verdict="accepted"
        )
        assert result["ok"] is False
        assert result["reason"] == "missing_release_identity"
        assert wo.get_work_order(wo_id)["status"] == "verifying"  # type: ignore[index]

    def test_accepted_without_business_evidence_refused(self, isolated_store: Path) -> None:
        # 发布身份/业务验收证据缺失时拒绝关闭（CI 通过 ≠ 客户能用）
        wo_id = self._make_verifying(issue=82)
        result = wo.record_acceptance_verdict(
            issue_number=82, release_version="1.0.0.2", verdict="accepted"
        )
        assert result["ok"] is False
        assert result["reason"] == "missing_acceptance_evidence"
        assert wo.get_work_order(wo_id)["status"] == "verifying"  # type: ignore[index]
        # 只有单平台健康也不够
        partial = wo.record_acceptance_verdict(
            issue_number=82,
            release_version="1.0.0.2",
            verdict="accepted",
            evidence={"per_platform": {"win": {"installed": 1, "failed": 0}}},
        )
        assert partial["ok"] is False
        assert wo.get_work_order(wo_id)["status"] == "verifying"  # type: ignore[index]

    def test_duplicate_accepted_receipt_is_idempotent(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying(issue=83)
        first = wo.record_acceptance_verdict(
            issue_number=83,
            release_version="1.0.0.2",
            verdict="accepted",
            evidence=dict(self._HEALTHY),
        )
        assert first["ok"] is True
        events_after_first = len(wo.get_work_order(wo_id)["history"])  # type: ignore[index]
        replay = wo.record_acceptance_verdict(
            issue_number=83,
            release_version="1.0.0.2",
            verdict="accepted",
            evidence=dict(self._HEALTHY),
        )
        assert replay["ok"] is True
        assert replay["reason"] == "already_closed"
        assert len(wo.get_work_order(wo_id)["history"]) == events_after_first  # type: ignore[index]

    def test_stale_receipt_does_not_overwrite_new_state(self, isolated_store: Path) -> None:
        # 乱序回执：closed 后收到旧版本 rejected 不得重开
        wo_id = self._make_verifying(issue=84)
        assert (
            wo.record_acceptance_verdict(
                issue_number=84,
                release_version="2.0.0.0",
                verdict="accepted",
                evidence=dict(self._HEALTHY),
            )["ok"]
            is True
        )
        stale = wo.record_acceptance_verdict(
            issue_number=84, release_version="1.0.0.2", verdict="rejected"
        )
        assert stale["ok"] is False
        assert stale["reason"] == "stale_receipt"
        assert wo.get_work_order(wo_id)["status"] == "closed"  # type: ignore[index]

    def test_unknown_verdict_rejected(self, isolated_store: Path) -> None:
        wo_id = self._make_verifying(issue=85)
        result = wo.record_acceptance_verdict(
            issue_number=85, release_version="1.0.0.2", verdict="maybe"
        )
        assert result["ok"] is False
        assert result["reason"] == "unknown_verdict"
        assert wo.get_work_order(wo_id)["status"] == "verifying"  # type: ignore[index]

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
    """统一 Router 四类去向的确定性规则（身份字段只用于归属）。"""

    def test_default_is_product_line(self) -> None:
        # 无法证明属于其他轨道 → 通用产品线（只有通用能力进入主产品）
        assert wo.classify_track(reason="intent_unknown") == "product_line"
        assert wo.classify_track() == "product_line"

    def test_ops_reasons_route_to_ops_support(self) -> None:
        assert wo.classify_track(reason="llm_timeout") == "ops_support"
        assert wo.classify_track(reason="install_failed") == "ops_support"

    def test_customer_id_with_ops_reason_still_ops(self) -> None:
        # 反例（#1851 整改）：已知客户反馈普通故障仍走运维，不得转定制
        track = wo.classify_track(reason="llm_timeout", context={"customer_id": "c-1"})
        assert track == "ops_support"
        assert (
            wo.classify_track(reason="deploy_failed", context={"account_id": "acc-9"})
            == "ops_support"
        )

    def test_customer_identity_alone_does_not_make_custom_track(self) -> None:
        # 身份字段只用于归属；无显式 customer_scoped 不得进定制轨道
        assert wo.classify_track(context={"customer_id": "c-1"}) == "product_line"
        assert (
            wo.classify_track(reason="intent_unknown", context={"account_id": "acc-1"})
            == "product_line"
        )

    def test_explicit_customer_scoped_routes_to_custom(self) -> None:
        # 专属范围由显式 customer_scoped 决定（派发前仍须批准标签）
        assert wo.classify_track(context={"customer_scoped": True}) == "customer_custom"
        ctx = {"skill_proposal": {"customer_scoped": True, "industry": "涂料"}}
        assert wo.classify_track(context=ctx) == "customer_custom"

    def test_industry_signal_routes_to_industry_mod(self) -> None:
        assert wo.classify_track(context={"industry": "涂料"}) == "industry_mod"
        ctx = {"intent_result": {"industry": "涂料"}}
        assert wo.classify_track(context=ctx) == "industry_mod"
        ctx2 = {"skill_proposal": {"industry": "考勤"}}
        assert wo.classify_track(context=ctx2) == "industry_mod"

    def test_ops_reason_beats_industry_and_scope(self) -> None:
        # 运行期故障永远优先：即使带行业/身份信息也不是产品需求
        ctx = {"industry": "涂料", "customer_id": "c-1", "customer_scoped": True}
        assert wo.classify_track(reason="health_check_failed", context=ctx) == "ops_support"


class TestDedupAndTenantIsolation:
    """同需求跨入口去重 + 跨租户隔离（2026-09-10 #1851 整改）。"""

    def test_same_need_from_different_entries_merges(self, isolated_store: Path) -> None:
        # 同一需求经对话与反馈两个入口到达 → 同一工单（source 只做归属）
        first = wo.upsert_candidate(source="intent", dedup_key="k-merge", reason="skill_proposal")
        assert first["created"] is True
        second = wo.upsert_candidate(
            source="market_feedback", dedup_key="k-merge", reason="skill_proposal"
        )
        assert second["created"] is False
        assert second["wo_id"] == first["wo_id"]
        assert len(wo.list_work_orders()) == 1

    def test_same_text_from_different_customers_isolated(self, isolated_store: Path) -> None:
        from app.services import capability_proposal_recorder as recorder

        a = recorder._dedup_key("打印报表失败", "skill_proposal", {"customer_id": "cust-A"})
        b = recorder._dedup_key("打印报表失败", "skill_proposal", {"customer_id": "cust-B"})
        assert a != b, "不同客户提交相同文字不得合并为同一提案（跨租户隔离）"
        generic = recorder._dedup_key("打印报表失败", "skill_proposal", None)
        assert generic != a and generic != b

    def test_same_customer_same_need_dedups(self) -> None:
        from app.services import capability_proposal_recorder as recorder

        k1 = recorder._dedup_key("打印报表失败", "skill_proposal", {"customer_id": "cust-A"})
        k2 = recorder._dedup_key(" 打印报表失败 ", "skill_proposal", {"tenant_id": "cust-A"})
        assert k1 == k2, "同客户同需求（归一化后）仍须去重"


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
