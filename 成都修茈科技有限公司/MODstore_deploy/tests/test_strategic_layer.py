# 成都修茈科技有限公司/MODstore_deploy/tests/test_strategic_layer.py
"""战略-执行分层机制单元测试 + 集成测试。

覆盖：
- ``AutonomyEvaluator``：默认规则、glob 匹配、优先级、未匹配保守默认
- ``StrategicDecisionLedger``：propose（auto_approved/proposed）、生命周期转换、状态机保护
- ``CouncilMeetingService``：schedule → start → conclude → action items；cancel
- ``StrategicReportService``：周报/月报生成、幂等覆盖、查询

测试通过 pytest 全局 ``MODSTORE_DB_PATH`` 临时 SQLite 隔离（见 ``conftest.py``）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modstore_server.models import init_db
from modstore_server.strategic_layer import (
    AutonomyAction,
    AutonomyEvaluator,
    CouncilMeetingService,
    DecidedBy,
    DecisionLifecycleError,
    DecisionProposer,
    DecisionStatus,
    DecisionType,
    MeetingDecisionRef,
    MeetingParticipants,
    MeetingStatus,
    MeetingType,
    RiskLevel,
    StrategicDecisionLedger,
    StrategicReportService,
    seed_default_boundaries,
)

# ─── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _ensure_db():
    """确保 ``init_db`` 已为当前测试模块运行（创建 strategic_* 表）。"""
    init_db()
    yield


@pytest.fixture(autouse=True)
def _seed_boundaries():
    """每个测试前确保 13 条默认自治边界已 seed（幂等）。"""
    seed_default_boundaries()
    yield


# ─── AutonomyEvaluator ────────────────────────────────────────────────────


class TestAutonomyEvaluator:
    """自治边界评估器测试套件。"""

    def test_seed_default_boundaries_is_idempotent(self):
        # 第一次 seed 已经在 fixture 中完成；再次调用应返回 0
        inserted = seed_default_boundaries()
        assert inserted == 0

    def test_list_rules_returns_default_set(self):
        evaluator = AutonomyEvaluator.from_db()
        rules = evaluator.list_rules()
        # 14 = 13 (原始默认) + 1 (exec-track-digest-action-items).
        assert len(rules) == 14
        rule_ids = {r.rule_id for r in rules}
        assert "exec-unit-test" in rule_ids
        assert "exec-track-digest-action-items" in rule_ids
        assert "strat-prod-deploy" in rule_ids
        assert "strat-rollback" in rule_ids

    def test_evaluate_auto_action_matches_unit_test(self):
        evaluator = AutonomyEvaluator.from_db()
        result = evaluator.evaluate("pytest tests/test_strategic.py")
        assert result.action == AutonomyAction.AUTO
        assert result.risk_level == RiskLevel.LOW
        assert result.rule is not None
        assert result.rule.rule_id == "exec-unit-test"

    def test_evaluate_report_only_action_matches_pr_create(self):
        evaluator = AutonomyEvaluator.from_db()
        result = evaluator.evaluate("github pr create 123")
        assert result.action == AutonomyAction.REPORT_ONLY
        assert result.risk_level == RiskLevel.MEDIUM

    def test_evaluate_require_human_action_matches_prod_deploy(self):
        evaluator = AutonomyEvaluator.from_db()
        result = evaluator.evaluate("production deploy v10.0.1")
        assert result.action == AutonomyAction.REQUIRE_HUMAN
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.rule is not None
        assert result.rule.rule_id == "strat-prod-deploy"

    def test_evaluate_unknown_action_falls_back_to_require_human(self):
        """未匹配规则时，保守默认 require_human + medium。"""
        evaluator = AutonomyEvaluator.from_db()
        result = evaluator.evaluate("totally unknown random action xyz")
        assert result.action == AutonomyAction.REQUIRE_HUMAN
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.rule is None

    def test_evaluate_case_insensitive_glob_match(self):
        """glob 匹配大小写不敏感（fnmatchcase on lowercased）。"""
        evaluator = AutonomyEvaluator.from_db()
        result = evaluator.evaluate("PYTEST tests/test_foo.py")
        assert result.action == AutonomyAction.AUTO


# ─── StrategicDecisionLedger ──────────────────────────────────────────────


class TestStrategicDecisionLedger:
    """战略决策账本测试套件。"""

    def test_propose_auto_action_creates_auto_approved(self):
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Run unit tests",
            action="pytest tests/test_foo.py",
            proposer=DecisionProposer(actor="ai-strategist", rationale="PR triggered"),
            decision_type=DecisionType.OPERATIONAL,
            scope="module",
            scope_ref="FHD/app/foo",
        )
        assert rec.status == DecisionStatus.AUTO_APPROVED
        assert rec.autonomy_action == AutonomyAction.AUTO.value
        assert rec.decided_by == DecidedBy.AI_AUTONOMY.value
        assert rec.decided_at is not None

    def test_propose_require_human_creates_proposed(self):
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Deploy v10.0.1 to production",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale="Release ready"),
            decision_type=DecisionType.STRATEGIC,
            scope="release_train",
            scope_ref="v10.0.1",
        )
        assert rec.status == DecisionStatus.PROPOSED
        assert rec.autonomy_action == AutonomyAction.REQUIRE_HUMAN.value
        assert rec.autonomy_risk_level == RiskLevel.CRITICAL.value
        assert rec.decided_by == ""
        assert rec.decided_at is None

    def test_propose_rejects_empty_title(self):
        ledger = StrategicDecisionLedger()
        with pytest.raises(ValueError, match="title must not be empty"):
            ledger.propose(
                title="",
                action="pytest tests/test_foo.py",
                proposer=DecisionProposer(actor="ai-strategist", rationale=""),
            )

    def test_propose_rejects_empty_action(self):
        ledger = StrategicDecisionLedger()
        with pytest.raises(ValueError, match="action must not be empty"):
            ledger.propose(
                title="Some title",
                action="",
                proposer=DecisionProposer(actor="ai-strategist", rationale=""),
            )

    def test_lifecycle_approve_start_complete_review(self):
        """完整生命周期：proposed → approved → executing → completed → reviewed。"""
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Deploy v10.0.1",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
            decision_type=DecisionType.STRATEGIC,
            scope="release_train",
            scope_ref="v10.0.1",
        )

        approved = ledger.approve(rec.decision_id, decided_by=DecidedBy.USER, review_notes="LGTM")
        assert approved.status == DecisionStatus.APPROVED

        started = ledger.start_execution(rec.decision_id, execution_plan={"step": "deploy"})
        assert started.status == DecisionStatus.EXECUTING

        completed = ledger.complete_execution(
            rec.decision_id,
            execution_result={"deployed": True, "version": "v10.0.1"},
        )
        assert completed.status == DecisionStatus.COMPLETED
        assert completed.review_at is not None

        reviewed = ledger.review(rec.decision_id, reviewer="founder", review_notes="smooth")
        assert reviewed.reviewed_by == "founder"
        assert reviewed.review_notes == "smooth"

    def test_reject_requires_review_notes(self):
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Bad idea",
            action="production deploy v9.9.9",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        with pytest.raises(ValueError, match="review_notes required for rejection"):
            ledger.reject(rec.decision_id, decided_by=DecidedBy.USER, review_notes="")

    def test_cannot_approve_rejected_decision(self):
        """终态保护：rejected 不能再 approve。"""
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Bad idea",
            action="production deploy v9.9.9",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        ledger.reject(rec.decision_id, decided_by=DecidedBy.USER, review_notes="no")
        with pytest.raises(DecisionLifecycleError):
            ledger.approve(rec.decision_id, decided_by=DecidedBy.USER, review_notes="try again")

    def test_cannot_approve_completed_decision(self):
        """终态保护：completed 不能再 approve。"""
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Deploy",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        ledger.approve(rec.decision_id, decided_by=DecidedBy.USER, review_notes="ok")
        ledger.start_execution(rec.decision_id)
        ledger.complete_execution(rec.decision_id, execution_result={})
        with pytest.raises(DecisionLifecycleError):
            ledger.approve(rec.decision_id, decided_by=DecidedBy.USER, review_notes="again")

    def test_cannot_review_non_completed_decision(self):
        """复盘只能在 completed 状态下调用。"""
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Deploy",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        # proposed 状态不能 review
        with pytest.raises(DecisionLifecycleError):
            ledger.review(rec.decision_id, reviewer="founder", review_notes="premature")

    def test_cannot_review_twice(self):
        """复盘只能调用一次。"""
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Deploy",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        ledger.approve(rec.decision_id, decided_by=DecidedBy.USER, review_notes="ok")
        ledger.start_execution(rec.decision_id)
        ledger.complete_execution(rec.decision_id, execution_result={})
        ledger.review(rec.decision_id, reviewer="founder", review_notes="first review")
        with pytest.raises(DecisionLifecycleError, match="already reviewed"):
            ledger.review(rec.decision_id, reviewer="founder", review_notes="second review")

    def test_withdraw_from_proposed(self):
        """proposed 可以撤回。"""
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="Withdraw me",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        withdrawn = ledger.withdraw(rec.decision_id, actor="founder", reason="changed mind")
        assert withdrawn.status == DecisionStatus.WITHDRAWN

    def test_withdraw_requires_reason(self):
        ledger = StrategicDecisionLedger()
        rec = ledger.propose(
            title="X",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        with pytest.raises(ValueError, match="reason required for withdrawal"):
            ledger.withdraw(rec.decision_id, actor="founder", reason="")

    def test_get_returns_none_for_unknown_id(self):
        ledger = StrategicDecisionLedger()
        assert ledger.get("dec-nonexistent-id-12345") is None

    def test_list_recent_filters_by_status(self):
        ledger = StrategicDecisionLedger()
        # 提议一个 auto_approved
        ledger.propose(
            title="Auto one",
            action="pytest tests/test_foo.py",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        # 提议一个 proposed
        ledger.propose(
            title="Human one",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )
        auto_only = ledger.list_recent(status=DecisionStatus.AUTO_APPROVED, limit=100)
        assert all(r.status == DecisionStatus.AUTO_APPROVED for r in auto_only)
        assert len(auto_only) >= 1

        proposed_only = ledger.list_recent(status=DecisionStatus.PROPOSED, limit=100)
        assert all(r.status == DecisionStatus.PROPOSED for r in proposed_only)
        assert len(proposed_only) >= 1


# ─── CouncilMeetingService ────────────────────────────────────────────────


class TestCouncilMeetingService:
    """员工自治会议测试套件。"""

    def test_schedule_creates_scheduled_meeting(self):
        svc = CouncilMeetingService()
        sched_at = datetime.now(timezone.utc) + timedelta(hours=1)
        meeting_id = svc.schedule(
            meeting_type=MeetingType.WEEKLY_REVIEW,
            title="Week 30 review",
            agenda="Review decisions\nPlan next week",
            participants=MeetingParticipants(
                required=["ai-strategist"],
                optional=["ops-engineer"],
                chair="founder",
            ),
            scheduled_at=sched_at,
        )
        assert meeting_id.startswith("mtg-")
        meeting = svc.get(meeting_id)
        assert meeting is not None
        assert meeting["status"] == MeetingStatus.SCHEDULED.value
        assert meeting["title"] == "Week 30 review"
        assert meeting["meeting_type"] == MeetingType.WEEKLY_REVIEW.value
        assert meeting["participants"]["chair"] == "founder"

    def test_schedule_rejects_empty_title(self):
        svc = CouncilMeetingService()
        with pytest.raises(ValueError, match="title must not be empty"):
            svc.schedule(
                meeting_type=MeetingType.AD_HOC,
                title="",
                agenda="agenda",
                participants=MeetingParticipants(),
                scheduled_at=datetime.now(timezone.utc),
            )

    def test_schedule_rejects_empty_agenda(self):
        svc = CouncilMeetingService()
        with pytest.raises(ValueError, match="agenda must not be empty"):
            svc.schedule(
                meeting_type=MeetingType.AD_HOC,
                title="title",
                agenda="",
                participants=MeetingParticipants(),
                scheduled_at=datetime.now(timezone.utc),
            )

    def test_start_transition_scheduled_to_in_progress(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        meeting = svc.start(meeting_id)
        assert meeting["status"] == MeetingStatus.IN_PROGRESS.value
        assert meeting["started_at"] is not None

    def test_start_rejects_non_scheduled_meeting(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        svc.start(meeting_id)
        # 已 in_progress，不能再次 start
        with pytest.raises(ValueError, match="cannot start meeting in status"):
            svc.start(meeting_id)

    def test_conclude_writes_decisions_and_action_items(self):
        """conclude 将决议写入决策账本，并把 action items 落地。"""
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        svc.start(meeting_id)

        # 先提议一个决策供会议审议
        ledger = StrategicDecisionLedger()
        decision = ledger.propose(
            title="Adopt new CI policy",
            action="production deploy v10.0.1",  # require_human → proposed
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )

        meeting = svc.conclude(
            meeting_id,
            minutes_md="Approved 1 decision, 2 action items.",
            decisions=[
                MeetingDecisionRef(
                    decision_id=decision.decision_id,
                    vote_outcome="approved",
                    vote_summary={"votes": "unanimous"},
                ),
            ],
            action_items=[
                {
                    "description": "Update CI docs",
                    "assigned_to": "docs-writer",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
                {
                    "description": "Monitor CI 24h",
                    "assigned_to": "ops-engineer",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
            ],
            actor="founder",
        )
        assert meeting["status"] == MeetingStatus.CONCLUDED.value
        assert meeting["concluded_at"] is not None
        assert len(meeting["decisions"]) == 1
        assert len(meeting["action_items"]) == 2

        # 验证决策账本被会议推进
        updated = ledger.get(decision.decision_id)
        assert updated.status == DecisionStatus.APPROVED
        assert updated.decided_by == DecidedBy.COUNCIL_VOTE.value

    def test_conclude_skips_invalid_action_items(self):
        """action item 缺少必需字段时跳过，不阻断 conclude。"""
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        svc.start(meeting_id)

        meeting = svc.conclude(
            meeting_id,
            minutes_md="Meeting with malformed action item",
            decisions=[],
            action_items=[
                {"description": "", "assigned_to": "x", "decision_id": "y"},  # 缺 description
                {"description": "valid", "assigned_to": "", "decision_id": "y"},  # 缺 assigned_to
                {"description": "valid", "assigned_to": "x", "decision_id": ""},  # 缺 decision_id
            ],
            actor="founder",
        )
        assert meeting["status"] == MeetingStatus.CONCLUDED.value
        assert len(meeting["action_items"]) == 0  # 全部被跳过

    def test_cancel_meeting(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        meeting = svc.cancel(meeting_id, reason="founder unavailable")
        assert meeting["status"] == MeetingStatus.CANCELLED.value

    def test_cancel_rejects_empty_reason(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        with pytest.raises(ValueError, match="reason required"):
            svc.cancel(meeting_id, reason="")

    def test_list_recent_returns_meetings(self):
        svc = CouncilMeetingService()
        self._schedule_meeting(svc, title="Meeting A")
        self._schedule_meeting(svc, title="Meeting B")
        meetings = svc.list_recent(limit=10)
        assert len(meetings) >= 2

    def test_list_action_items_filters_by_assignee(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        svc.start(meeting_id)

        # 创建一个决策供 action item 引用
        ledger = StrategicDecisionLedger()
        decision = ledger.propose(
            title="X",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )

        svc.conclude(
            meeting_id,
            minutes_md="Two action items for different assignees",
            decisions=[],
            action_items=[
                {
                    "description": "Task A",
                    "assigned_to": "alice",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
                {
                    "description": "Task B",
                    "assigned_to": "bob",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
            ],
            actor="founder",
        )

        alice_items = svc.list_action_items(assigned_to="alice", limit=100)
        assert len(alice_items) == 1
        assert alice_items[0]["assigned_to"] == "alice"

    def test_update_action_item_status(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        svc.start(meeting_id)

        ledger = StrategicDecisionLedger()
        decision = ledger.propose(
            title="X",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )

        svc.conclude(
            meeting_id,
            minutes_md="action item test",
            decisions=[],
            action_items=[
                {
                    "description": "Do something",
                    "assigned_to": "alice",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
            ],
            actor="founder",
        )

        items = svc.list_action_items(limit=10)
        assert len(items) >= 1
        action_id = items[0]["action_id"]

        updated = svc.update_action_item(action_id, status="in_progress")
        assert updated["status"] == "in_progress"

        completed = svc.update_action_item(action_id, status="completed")
        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None

    def test_update_action_item_rejects_invalid_status(self):
        svc = CouncilMeetingService()
        meeting_id = self._schedule_meeting(svc)
        svc.start(meeting_id)

        ledger = StrategicDecisionLedger()
        decision = ledger.propose(
            title="X",
            action="production deploy v10.0.1",
            proposer=DecisionProposer(actor="ai-strategist", rationale=""),
        )

        svc.conclude(
            meeting_id,
            minutes_md="invalid status test",
            decisions=[],
            action_items=[
                {
                    "description": "Do something",
                    "assigned_to": "alice",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
            ],
            actor="founder",
        )

        items = svc.list_action_items(limit=10)
        action_id = items[0]["action_id"]
        with pytest.raises(ValueError, match="invalid status"):
            svc.update_action_item(action_id, status="totally_invalid_status")

    # ─── helpers ───

    @staticmethod
    def _schedule_meeting(svc: CouncilMeetingService, *, title: str = "Test meeting") -> str:
        return svc.schedule(
            meeting_type=MeetingType.AD_HOC,
            title=title,
            agenda="Test agenda",
            participants=MeetingParticipants(required=["ai-strategist"], chair="founder"),
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )


# ─── StrategicReportService ───────────────────────────────────────────────


class TestStrategicReportService:
    """战略层周报/月报测试套件。"""

    def test_generate_weekly_report_default_week(self):
        rs = StrategicReportService()
        report = rs.generate_weekly_report(actor="ai-strategist")
        assert report["report_type"] == "weekly"
        assert report["report_key"].startswith("weekly:")
        assert "content_md" in report
        assert len(report["content_md"]) > 0
        assert "metrics" in report
        assert "period" in report["metrics"]
        assert report["status"] == "generated"
        assert report["generated_by"] == "ai-strategist"

    def test_generate_weekly_report_is_idempotent(self):
        """同 report_key 重复生成会覆盖，不创建重复记录。"""
        rs = StrategicReportService()
        # 用同一个 target_date 生成两次
        from datetime import date

        target = date(2026, 7, 20)  # 周日
        first = rs.generate_weekly_report(target_date=target, actor="ai-strategist")
        second = rs.generate_weekly_report(target_date=target, actor="ai-strategist")
        assert first["report_key"] == second["report_key"]
        # list_reports 应该只有一条该 key 的记录
        reports = rs.list_reports(report_type="weekly", limit=100)
        matching = [r for r in reports if r["report_key"] == first["report_key"]]
        assert len(matching) == 1

    def test_generate_monthly_report_default_last_month(self):
        rs = StrategicReportService()
        report = rs.generate_monthly_report(actor="ai-strategist")
        assert report["report_type"] == "monthly"
        assert report["report_key"].startswith("monthly:")
        assert "content_md" in report
        assert len(report["content_md"]) > 0

    def test_generate_monthly_report_explicit_year_month(self):
        rs = StrategicReportService()
        report = rs.generate_monthly_report(year=2026, month=6, actor="test")
        assert report["report_key"] == "monthly:2026-06"
        assert report["period_start"] == "2026-06-01"
        assert report["period_end"] == "2026-06-30"

    def test_get_report_returns_none_for_unknown_key(self):
        rs = StrategicReportService()
        assert rs.get_report("weekly:1999-W01") is None

    def test_get_report_returns_persisted_report(self):
        rs = StrategicReportService()
        generated = rs.generate_weekly_report(actor="test")
        fetched = rs.get_report(generated["report_key"])
        assert fetched is not None
        assert fetched["report_key"] == generated["report_key"]
        assert fetched["content_md"] == generated["content_md"]

    def test_list_reports_filters_by_type(self):
        rs = StrategicReportService()
        rs.generate_weekly_report(actor="test")
        rs.generate_monthly_report(actor="test")
        weekly_only = rs.list_reports(report_type="weekly", limit=100)
        monthly_only = rs.list_reports(report_type="monthly", limit=100)
        assert all(r["report_type"] == "weekly" for r in weekly_only)
        assert all(r["report_type"] == "monthly" for r in monthly_only)

    def test_weekly_report_includes_decision_metrics(self):
        """周报 metrics 应包含本周期内的决策统计。"""
        # 先创建几个决策（在本周内）
        ledger = StrategicDecisionLedger()
        for i in range(3):
            ledger.propose(
                title=f"Decision {i}",
                action="pytest tests/test_foo.py",  # auto
                proposer=DecisionProposer(actor="ai-strategist", rationale=""),
            )

        rs = StrategicReportService()
        report = rs.generate_weekly_report(actor="test")
        decisions_metric = report["metrics"].get("decisions", {})
        assert decisions_metric.get("total", 0) >= 3
        assert "by_status" in decisions_metric
        assert "auto_approved_rate" in decisions_metric


# ─── 集成测试：daily-digest 与战略层联动 ─────────────────────────────────


class TestStrategicLayerIntegration:
    """战略层与 daily-digest 流程的集成测试。"""

    def test_full_pipeline_propose_meeting_conclude_report(self):
        """端到端：提议 → 会议审议 → 落地 action item → 周报聚合。

        验证：
        1. 一个 require_human 决策进入 proposed
        2. council meeting 通过该决策
        3. 生成 2 个 action items
        4. 周报 metrics 反映本周决策与 action items
        """
        ledger = StrategicDecisionLedger()
        decision = ledger.propose(
            title="Adopt v10.0.2 release",
            action="production deploy v10.0.2",
            proposer=DecisionProposer(actor="ai-strategist", rationale="patch ready"),
            decision_type=DecisionType.STRATEGIC,
            scope="release_train",
            scope_ref="v10.0.2",
        )
        assert decision.status == DecisionStatus.PROPOSED

        # 调度会议
        meeting_svc = CouncilMeetingService()
        meeting_id = meeting_svc.schedule(
            meeting_type=MeetingType.WEEKLY_REVIEW,
            title="Ad hoc release review",
            agenda="Approve v10.0.2 release",
            participants=MeetingParticipants(required=["ai-strategist"], chair="founder"),
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        meeting_svc.start(meeting_id)

        meeting_svc.conclude(
            meeting_id,
            minutes_md="Approved v10.0.2 release; 2 action items assigned.",
            decisions=[
                MeetingDecisionRef(
                    decision_id=decision.decision_id,
                    vote_outcome="approved",
                    vote_summary={"votes": "unanimous"},
                ),
            ],
            action_items=[
                {
                    "description": "Publish release notes",
                    "assigned_to": "release-engineer",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
                {
                    "description": "Monitor production 24h",
                    "assigned_to": "ops-engineer",
                    "decision_id": decision.decision_id,
                    "due_at": None,
                },
            ],
            actor="founder",
        )

        # 验证决策被会议推进
        updated = ledger.get(decision.decision_id)
        assert updated.status == DecisionStatus.APPROVED
        assert updated.decided_by == DecidedBy.COUNCIL_VOTE.value

        # 验证 action items 落地
        items = meeting_svc.list_action_items(limit=10)
        assert len(items) >= 2

        # 验证周报聚合了本周决策
        rs = StrategicReportService()
        report = rs.generate_weekly_report(actor="test")
        decisions_metric = report["metrics"]["decisions"]
        assert decisions_metric["total"] >= 1
        assert "approved" in decisions_metric["by_status"]

        action_items_metric = report["metrics"]["action_items"]
        assert action_items_metric["total"] >= 2
