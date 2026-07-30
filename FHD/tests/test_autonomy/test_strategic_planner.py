"""战略规划器：目标分解 / 反思修正 / 自适应阈值。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.autonomy.adaptive_thresholds import (
    get_threshold,
    load_adaptive_thresholds,
    propose_threshold_update,
    save_thresholds,
)
from app.domain.autonomy.strategic_planner import (
    QuarterlyPlan,
    StrategicPlanner,
    current_quarter,
    heuristic_quarterly_plan,
)


@pytest.mark.asyncio
async def test_heuristic_decompose_returns_three_features():
    plan = heuristic_quarterly_plan(
        "这个季度做哪三个功能",
        context={
            "project_gaps": ["客服积压未验收"],
            "autonomy_debts": ["impact-predictor 仍是 switch-case"],
            "capability_proposals": [{"raw_input": "合规审计助手"}],
        },
        quarter="2026-Q3",
    )
    assert plan.quarter == "2026-Q3"
    assert len(plan.features) == 3
    assert plan.source == "heuristic_fallback"
    assert all(f.title for f in plan.features)


@pytest.mark.asyncio
async def test_llm_decompose_and_reflect_with_fake_chat():
    class FakeChat:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "quarter": "2026-Q3",
                        "goal": "AGI 主导工程",
                        "rationale": "fake",
                        "features": [
                            {
                                "title": "功能A",
                                "why": "a",
                                "success_metric": "metric-a",
                                "horizon_weeks": 4,
                                "risk": "low",
                            },
                            {
                                "title": "功能B",
                                "why": "b",
                                "success_metric": "metric-b",
                                "horizon_weeks": 5,
                                "risk": "medium",
                            },
                            {
                                "title": "功能C",
                                "why": "c",
                                "success_metric": "metric-c",
                                "horizon_weeks": 6,
                                "risk": "high",
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "goal": "AGI 主导工程（修订）",
                    "rationale": "revised",
                    "features": [
                        {
                            "title": "功能B",
                            "why": "优先收入",
                            "success_metric": "paid_orders>0",
                            "horizon_weeks": 4,
                            "risk": "medium",
                        },
                        {
                            "title": "功能A",
                            "why": "a",
                            "success_metric": "metric-a",
                            "horizon_weeks": 4,
                            "risk": "low",
                        },
                        {
                            "title": "功能C",
                            "why": "c",
                            "success_metric": "metric-c",
                            "horizon_weeks": 6,
                            "risk": "high",
                        },
                    ],
                },
                ensure_ascii=False,
            )

    planner = StrategicPlanner(chat=FakeChat())
    plan = await planner.plan_with_reflection(
        "这个季度做哪三个功能",
        quarter="2026-Q3",
        critique="优先收入闭环",
    )
    assert isinstance(plan, QuarterlyPlan)
    assert len(plan.features) == 3
    assert plan.features[0].title == "功能B"
    assert any(r.get("phase") == "reflect" for r in plan.revisions)


def test_adaptive_threshold_floor_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "t.json"
    monkeypatch.setenv("XCAGI_ADAPTIVE_THRESHOLDS_PATH", str(path))
    thresholds = load_adaptive_thresholds()
    crash = thresholds["crash_threshold"]
    assert crash.floor == 2
    assert crash.ceiling == 5
    proposal = propose_threshold_update("crash_threshold", 1, reason="too sensitive")
    assert proposal["proposed"] == 2  # clamped to floor
    assert proposal["requires_promotion"] is True
    crash_hi = propose_threshold_update("crash_threshold", 9, reason="too loose")
    assert crash_hi["proposed"] == 5
    # promote manually
    thresholds["crash_threshold"] = get_threshold("crash_threshold")
    from app.domain.autonomy.adaptive_thresholds import AdaptiveThreshold

    thresholds["crash_threshold"] = AdaptiveThreshold(
        name="crash_threshold",
        value=4,
        floor=2,
        ceiling=5,
        unit="count_per_window",
        source="promoted",
    )
    save_thresholds(thresholds, path=path)
    loaded = get_threshold("crash_threshold", path=path)
    assert loaded.value == 4
    assert loaded.source == "promoted"


@pytest.mark.asyncio
async def test_app_service_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_STRATEGIC_PLAN_LOG", str(tmp_path / "plans.jsonl"))
    from app.application.autonomy.strategic_plan_app_service import (
        build_quarterly_plan,
        latest_plan,
    )

    plan = await build_quarterly_plan(
        "这个季度做哪三个功能",
        use_llm=False,
        persist=True,
        quarter=current_quarter(),
    )
    assert plan["feature_count"] == 3
    assert latest_plan() is not None
    assert Path(tmp_path / "plans.jsonl").is_file()
