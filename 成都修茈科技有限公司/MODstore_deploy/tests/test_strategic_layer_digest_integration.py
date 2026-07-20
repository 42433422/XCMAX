"""daily-digest → 战略层集成测试。

验证 ``trigger_strategic_layer_dispatch`` 在不同 release_kind / result.ok 组合下
正确提案决策到 ``StrategicDecisionLedger``。
"""

from __future__ import annotations

import pytest

from modstore_server.db.base import init_db
from modstore_server.digest_daily_line_chain import trigger_strategic_layer_dispatch
from modstore_server.strategic_layer import (
    StrategicDecisionLedger,
    seed_default_boundaries,
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_db():
    init_db()
    yield


@pytest.fixture(autouse=True)
def _seed_boundaries():
    seed_default_boundaries()
    yield


def _list_decisions() -> list:
    ledger = StrategicDecisionLedger()
    return ledger.list_recent(limit=50)


class TestStrategicLayerDigestIntegration:
    """daily-digest 触发战略层决策集成测试。"""

    def test_disabled_env_skips_dispatch(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_STRATEGIC_LAYER_INTEGRATION_ENABLED", "0")
        out = trigger_strategic_layer_dispatch(
            record_id=1,
            release_kind="daily",
            release_train="1.0.0.0",
            result={"ok": True, "shadow": False},
        )
        assert out["ok"] is True
        assert out["skipped"] is True
        assert "disabled" in out["reason"]

    def test_shadow_mode_skips_dispatch(self):
        out = trigger_strategic_layer_dispatch(
            record_id=2,
            release_kind="installer",
            release_train="1.0.0.0",
            result={"ok": True, "shadow": True},
        )
        assert out["ok"] is True
        assert out["skipped"] is True
        assert out["reason"] == "shadow mode"

    def test_daily_success_skips_dispatch(self):
        """daily 成功不提案决策（report_only）。"""
        out = trigger_strategic_layer_dispatch(
            record_id=3,
            release_kind="daily",
            release_train="1.0.0.0",
            result={
                "ok": True,
                "shadow": False,
                "phase_b": {"ok": True},
                "phase_c_pipeline": {"ok": True},
            },
        )
        assert out["ok"] is True
        assert out["skipped"] is True
        assert out["reason"] == "daily ok, no strategic action"

    def test_daily_failure_proposes_operational_decision(self):
        """daily 失败 → 提案 operational 决策（review_digest_failure）。"""
        out = trigger_strategic_layer_dispatch(
            record_id=4,
            release_kind="daily",
            release_train="1.0.0.0",
            result={
                "ok": False,
                "shadow": False,
                "phase_b": {"ok": False, "error": "phase_b failed"},
                "phase_c_pipeline": {"ok": True},
            },
        )
        assert out["ok"] is True
        assert out["skipped"] is False
        assert out["action"] == "review_digest_failure"
        assert "dec-" in out["decision_id"]
        assert out["status"] in ("proposed", "auto_approved")

        # 验证决策已写入账本
        ledger = StrategicDecisionLedger()
        record = ledger.get(out["decision_id"])
        assert record is not None
        assert record.title.startswith("daily-digest#4 失败 review")
        assert "phase_b" in record.execution_plan.get("failed_phases", [])
        assert "phase_c_pipeline" not in record.execution_plan.get("failed_phases", [])

    def test_installer_success_proposes_strategic_decision(self):
        """installer 成功 → 提案 strategic 决策（review_release_train）。"""
        out = trigger_strategic_layer_dispatch(
            record_id=5,
            release_kind="installer",
            release_train="1.0.0.5",
            result={
                "ok": True,
                "shadow": False,
                "phase_b": {"ok": True},
                "phase_c_pipeline": {"ok": True},
                "phase_c": {"ok": True},
            },
        )
        assert out["ok"] is True
        assert out["skipped"] is False
        assert out["action"] == "review_release_train"
        assert "dec-" in out["decision_id"]
        assert "1.0.0.5" in out["title"]

        ledger = StrategicDecisionLedger()
        record = ledger.get(out["decision_id"])
        assert record is not None
        assert "release_train" in record.scope
        assert record.scope_ref == "1.0.0.5"

    def test_major_success_proposes_strategic_decision(self):
        """major 成功 → 提案 strategic 决策。"""
        out = trigger_strategic_layer_dispatch(
            record_id=6,
            release_kind="major",
            release_train="2.0.0.0",
            result={
                "ok": True,
                "shadow": False,
                "phase_b": {"ok": True},
                "phase_c_pipeline": {"ok": True},
                "phase_c": {"ok": True},
            },
        )
        assert out["ok"] is True
        assert out["action"] == "review_release_train"
        assert "2.0.0.0" in out["title"]

    def test_installer_failure_proposes_operational_decision(self):
        """installer 失败 → 优先按失败路径提案 operational（不是 strategic）。"""
        out = trigger_strategic_layer_dispatch(
            record_id=7,
            release_kind="installer",
            release_train="1.0.0.7",
            result={
                "ok": False,
                "shadow": False,
                "phase_c": {"ok": False, "error": "FASTGATE blocked"},
            },
        )
        assert out["ok"] is True
        assert out["action"] == "review_digest_failure"
        assert "phase_c" in out["title"]

    def test_multiple_failed_phases_listed_in_title(self):
        """多个 phase 失败时 title 应列出所有失败 phase。"""
        out = trigger_strategic_layer_dispatch(
            record_id=8,
            release_kind="daily",
            release_train="1.0.0.0",
            result={
                "ok": False,
                "shadow": False,
                "phase_b": {"ok": False},
                "phase_c_pipeline": {"ok": False},
                "phase_c": {"ok": False},
            },
        )
        assert out["ok"] is True
        assert "phase_b" in out["title"]
        assert "phase_c_pipeline" in out["title"]
        assert "phase_c" in out["title"]

    def test_autonomy_evaluation_reflected_in_status(self):
        """决策状态反映自治边界评估（review_digest_failure 通常是 require_human → proposed）。"""
        out = trigger_strategic_layer_dispatch(
            record_id=9,
            release_kind="daily",
            release_train="1.0.0.0",
            result={
                "ok": False,
                "shadow": False,
                "phase_b": {"ok": False},
            },
        )
        assert out["ok"] is True
        # autonomy_action 至少应是 require_human / require_council / auto / report_only 之一
        assert out["autonomy_action"] in (
            "require_human",
            "require_council",
            "auto",
            "report_only",
        )
        # 如果是 auto / report_only → 状态 auto_approved；否则 proposed
        if out["autonomy_action"] in ("auto", "report_only"):
            assert out["status"] == "auto_approved"
        else:
            assert out["status"] == "proposed"
