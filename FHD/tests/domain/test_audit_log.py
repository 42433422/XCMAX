"""test_audit_log.py — app/domain/autonomy/audit_log.py 单元测试。

覆盖：路径解析（env vars）、append 边界（None/非 dict metadata）、
list_autonomy_audit 过滤、latest_action_event、summarize 边界、digest 渲染。
与 test_autonomy_guard.py 中的 audit 测试互补，不重复覆盖 append-only trigger 和
prohibited_miss 检测（已在 test_autonomy_guard.py 覆盖）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.autonomy.audit_log import (
    _db_path,
    _jsonl_path,
    _runtime_dir,
    append_autonomy_audit,
    autonomy_daily_digest_html,
    latest_action_event,
    list_autonomy_audit,
    summarize_autonomy_audit,
)
from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

UTC = UTC


@pytest.fixture(autouse=True)
def isolated_audit_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离 SQLite + JSONL 路径，每个测试独立。"""
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv(
        "XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval-ledger.jsonl")
    )
    monkeypatch.delenv("XCAGI_AUTONOMY_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    reload_autonomy_guard()
    yield
    reload_autonomy_guard()


# --------------------------------------------------------------------------- #
# 路径解析：_runtime_dir / _db_path / _jsonl_path
# --------------------------------------------------------------------------- #


class TestRuntimeDirEnvResolution:
    """覆盖 _runtime_dir 的三档 env var 回退。"""

    def test_explicit_autonomy_data_dir_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        custom = tmp_path / "custom-autonomy"
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(custom))
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "ignored"))
        result = _runtime_dir()
        assert result == custom

    def test_falls_back_to_xcagi_data_dir_with_autonomy_suffix(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("XCAGI_AUTONOMY_DATA_DIR", raising=False)
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        result = _runtime_dir()
        assert result == tmp_path / "autonomy"

    def test_falls_back_to_default_metrics_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("XCAGI_AUTONOMY_DATA_DIR", raising=False)
        monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
        result = _runtime_dir()
        # 默认回退到 _FHD_ROOT / "metrics"
        assert result.name == "metrics"

    def test_empty_string_env_vars_are_ignored(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", "   ")
        monkeypatch.setenv("XCAGI_DATA_DIR", "")
        result = _runtime_dir()
        assert result.name == "metrics"


class TestDbPathEnvResolution:
    """覆盖 _db_path 的 env var 覆盖。"""

    def test_explicit_db_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        custom = tmp_path / "custom.db"
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(custom))
        assert _db_path() == custom

    def test_db_path_falls_back_to_runtime_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", raising=False)
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path))
        result = _db_path()
        assert result.parent == tmp_path
        assert result.name == "autonomy-audit.sqlite3"

    def test_db_path_expands_user(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", "~/expanded.db")
        result = _db_path()
        assert "~" not in str(result)


class TestJsonlPathEnvResolution:
    """覆盖 _jsonl_path 的 env var 覆盖。"""

    def test_explicit_jsonl_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        custom = tmp_path / "custom.jsonl"
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(custom))
        assert _jsonl_path() == custom

    def test_jsonl_path_falls_back_to_runtime_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", raising=False)
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path))
        result = _jsonl_path()
        assert result.parent == tmp_path
        assert result.name == "autonomy-audit-log.jsonl"


# --------------------------------------------------------------------------- #
# append_autonomy_audit 边界
# --------------------------------------------------------------------------- #


class TestAppendAutonomyAudit:
    def test_happy_path_writes_to_sqlite_and_jsonl(self, tmp_path: Path):
        row = append_autonomy_audit(
            {
                "action_id": "happy-1",
                "action": "restart_service",
                "risk_level": "LOW",
                "decision": "allow",
                "outcome": "allowed",
                "source": "test",
            }
        )
        assert row["action_id"] == "happy-1"
        assert row["id"] >= 1
        assert row["highlighted"] is False  # "allow" 不在 _VETO_DECISIONS

        # JSONL mirror 存在（可能还包含 __configuration__ 启动记录，按 action_id 过滤）
        jsonl_path = _jsonl_path()
        lines = [
            line for line in jsonl_path.read_text(encoding="utf-8").strip().splitlines() if line
        ]
        matching = [json.loads(line) for line in lines if line.find('"happy-1"') >= 0]
        assert len(matching) == 1
        assert matching[0]["action_id"] == "happy-1"

    def test_none_action_id_defaults_to_system(self):
        row = append_autonomy_audit({"action": "test", "risk_level": "LOW"})
        assert row["action_id"] == "system"

    def test_none_action_defaults_to_unknown(self):
        row = append_autonomy_audit({"action_id": "x", "risk_level": "LOW"})
        assert row["action"] == "unknown"

    def test_none_risk_level_defaults_to_blocked(self):
        row = append_autonomy_audit({"action_id": "x", "action": "test"})
        assert row["risk_level"] == "BLOCKED"

    def test_none_decision_defaults_to_blocked(self):
        row = append_autonomy_audit({"action_id": "x", "action": "test", "risk_level": "LOW"})
        assert row["decision"] == "blocked"

    def test_none_timestamp_uses_iso_now(self):
        before = datetime.now(UTC).isoformat()
        row = append_autonomy_audit(
            {"action_id": "ts-test", "action": "test", "risk_level": "LOW", "decision": "allow"}
        )
        after = datetime.now(UTC).isoformat()
        assert before <= row["timestamp"] <= after

    def test_metadata_dict_is_serialized_as_json(self):
        row = append_autonomy_audit(
            {
                "action_id": "meta-dict",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
                "metadata": {"key": "value", "nested": {"num": 42}},
            }
        )
        assert row["metadata"] == {"key": "value", "nested": {"num": 42}}
        # 验证 SQLite 中存储的是 JSON 字符串
        with sqlite3.connect(_db_path()) as conn:
            raw = conn.execute(
                "SELECT metadata_json FROM autonomy_audit_log WHERE action_id = ?",
                ("meta-dict",),
            ).fetchone()
        assert raw is not None
        parsed = json.loads(raw[0])
        assert parsed == {"key": "value", "nested": {"num": 42}}

    def test_metadata_non_dict_defaults_to_empty_dict(self):
        row = append_autonomy_audit(
            {
                "action_id": "meta-non-dict",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
                "metadata": "not-a-dict",
            }
        )
        assert row["metadata"] == {}

    def test_metadata_none_defaults_to_empty_dict(self):
        row = append_autonomy_audit(
            {
                "action_id": "meta-none",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
                "metadata": None,
            }
        )
        assert row["metadata"] == {}

    @pytest.mark.parametrize(
        "decision",
        [
            "require_human",
            "pending_approval",
            "approval_requested",
            "rejected",
            "blocked",
            "prohibited",
            "cooldown",
        ],
    )
    def test_veto_decisions_are_highlighted(self, decision: str):
        row = append_autonomy_audit(
            {
                "action_id": f"veto-{decision}",
                "action": "test",
                "risk_level": "MEDIUM",
                "decision": decision,
            }
        )
        assert row["highlighted"] is True

    def test_non_veto_decision_not_highlighted(self):
        row = append_autonomy_audit(
            {
                "action_id": "non-veto",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
            }
        )
        assert row["highlighted"] is False

    def test_risk_level_is_uppercased(self):
        row = append_autonomy_audit(
            {
                "action_id": "upper-test",
                "action": "test",
                "risk_level": "low",
                "decision": "allow",
            }
        )
        assert row["risk_level"] == "LOW"

    def test_empty_approver_becomes_none(self):
        row = append_autonomy_audit(
            {
                "action_id": "approver-empty",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
                "approver": "",
            }
        )
        assert row["approver"] is None

    def test_empty_policy_becomes_none(self):
        row = append_autonomy_audit(
            {
                "action_id": "policy-empty",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
                "policy": "",
            }
        )
        assert row["policy"] is None


# --------------------------------------------------------------------------- #
# list_autonomy_audit 过滤
# --------------------------------------------------------------------------- #


class TestListAutonomyAudit:
    def _seed_records(self) -> None:
        """写入 5 条不同属性的记录。"""
        base = datetime.now(UTC).isoformat()
        records = [
            {
                "action_id": "list-1",
                "action": "restart_service",
                "risk_level": "LOW",
                "decision": "allow",
                "outcome": "allowed",
                "source": "prod",
                "timestamp": base,
            },
            {
                "action_id": "list-2",
                "action": "rollback_release",
                "risk_level": "MEDIUM",
                "decision": "require_human",
                "outcome": "not_executed",
                "source": "prod",
                "timestamp": base,
            },
            {
                "action_id": "list-3",
                "action": "db_migration",
                "risk_level": "BLOCKED",
                "decision": "prohibited",
                "outcome": "exception_raised",
                "source": "prod",
                "timestamp": base,
            },
            {
                "action_id": "e2e-list-4",
                "action": "restart_service",
                "risk_level": "LOW",
                "decision": "allow",
                "outcome": "allowed",
                "source": "test",
                "timestamp": base,
            },
            {
                "action_id": "list-5",
                "action": "freeze_manifest",
                "risk_level": "MEDIUM",
                "decision": "approved",
                "approver": "operator",
                "outcome": "allowed",
                "source": "prod",
                "timestamp": base,
            },
        ]
        for record in records:
            append_autonomy_audit(record)

    def test_no_filter_returns_all(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=100)
        assert len(rows) >= 5

    def test_filter_by_risk_level(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=100, risk_level="medium")
        assert all(r["risk_level"] == "MEDIUM" for r in rows)
        assert any(r["action_id"] == "list-2" for r in rows)

    def test_filter_by_risk_level_case_insensitive(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=100, risk_level="medium")
        assert all(r["risk_level"] == "MEDIUM" for r in rows)

    def test_filter_by_decision(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=100, decision="prohibited")
        assert len(rows) == 1
        assert rows[0]["action_id"] == "list-3"

    def test_filter_by_veto_only(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=100, veto_only=True)
        # require_human + prohibited 都是 veto
        decisions = {r["decision"] for r in rows}
        assert "require_human" in decisions
        assert "prohibited" in decisions
        assert "allow" not in decisions

    def test_filter_by_action_id(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=100, action_id="list-2")
        assert len(rows) == 1
        assert rows[0]["action_id"] == "list-2"

    def test_filter_by_since(self):
        self._seed_records()
        # 用未来时间过滤 → 应返回空
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        rows = list_autonomy_audit(limit=100, since=future)
        assert rows == []

    def test_since_with_past_time_returns_records(self):
        self._seed_records()
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        rows = list_autonomy_audit(limit=100, since=past)
        assert len(rows) >= 5

    def test_limit_clamped_to_minimum_1(self):
        self._seed_records()
        rows = list_autonomy_audit(limit=0)
        assert len(rows) == 1

    def test_limit_clamped_to_maximum_1000(self):
        rows = list_autonomy_audit(limit=5000)
        # 不会报错；返回的行数受实际数据限制
        assert isinstance(rows, list)

    def test_returns_metadata_as_dict(self):
        append_autonomy_audit(
            {
                "action_id": "meta-return",
                "action": "test",
                "risk_level": "LOW",
                "decision": "allow",
                "metadata": {"k": "v"},
            }
        )
        rows = list_autonomy_audit(limit=10, action_id="meta-return")
        assert rows[0]["metadata"] == {"k": "v"}
        assert "metadata_json" not in rows[0]

    def test_corrupted_metadata_json_falls_back_to_empty_dict(self):
        # 直接 INSERT 一条 metadata_json 损坏的记录（trigger 仅阻止 UPDATE/DELETE，不阻止 INSERT）
        with sqlite3.connect(_db_path()) as conn:
            conn.execute(
                "INSERT INTO autonomy_audit_log (action_id, action, risk_level, decision, "
                "timestamp, outcome, event_type, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "corrupt-meta-2",
                    "test",
                    "LOW",
                    "allow",
                    datetime.now(UTC).isoformat(),
                    "allowed",
                    "decision",
                    "not-valid-json{",
                ),
            )
        rows = list_autonomy_audit(limit=10, action_id="corrupt-meta-2")
        assert len(rows) == 1
        assert rows[0]["metadata"] == {}

    def test_highlighted_field_set_in_list_results(self):
        append_autonomy_audit(
            {
                "action_id": "highlight-list",
                "action": "test",
                "risk_level": "MEDIUM",
                "decision": "require_human",
            }
        )
        rows = list_autonomy_audit(limit=10, action_id="highlight-list")
        assert rows[0]["highlighted"] is True


# --------------------------------------------------------------------------- #
# latest_action_event
# --------------------------------------------------------------------------- #


class TestLatestActionEvent:
    def test_returns_none_when_no_records(self):
        result = latest_action_event("never_seen_action")
        assert result is None

    def test_returns_latest_by_timestamp(self):
        old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        new_ts = datetime.now(UTC).isoformat()
        append_autonomy_audit(
            {
                "action_id": "old-event",
                "action": "find_latest",
                "risk_level": "LOW",
                "decision": "allow",
                "timestamp": old_ts,
            }
        )
        append_autonomy_audit(
            {
                "action_id": "new-event",
                "action": "find_latest",
                "risk_level": "LOW",
                "decision": "allow",
                "timestamp": new_ts,
            }
        )
        result = latest_action_event("find_latest")
        assert result is not None
        assert result["action_id"] == "new-event"

    def test_filters_by_decisions(self):
        append_autonomy_audit(
            {
                "action_id": "allow-event",
                "action": "filter_test",
                "risk_level": "LOW",
                "decision": "allow",
            }
        )
        append_autonomy_audit(
            {
                "action_id": "blocked-event",
                "action": "filter_test",
                "risk_level": "BLOCKED",
                "decision": "blocked",
            }
        )
        # 只看 allow 决策
        result = latest_action_event("filter_test", decisions={"allow"})
        assert result is not None
        assert result["action_id"] == "allow-event"

    def test_returns_none_when_no_matching_decision(self):
        append_autonomy_audit(
            {
                "action_id": "only-allow",
                "action": "no_match",
                "risk_level": "LOW",
                "decision": "allow",
            }
        )
        result = latest_action_event("no_match", decisions={"prohibited"})
        assert result is None

    def test_returns_metadata_as_dict(self):
        append_autonomy_audit(
            {
                "action_id": "meta-latest",
                "action": "meta_action",
                "risk_level": "LOW",
                "decision": "allow",
                "metadata": {"k": "v"},
            }
        )
        result = latest_action_event("meta_action")
        assert result is not None
        assert result["metadata"] == {"k": "v"}
        assert "metadata_json" not in result

    def test_corrupted_metadata_json_falls_back_to_empty_dict(self):
        # 直接 INSERT 一条 metadata_json 损坏的记录触发 json.loads 异常分支
        with sqlite3.connect(_db_path()) as conn:
            conn.execute(
                "INSERT INTO autonomy_audit_log (action_id, action, risk_level, decision, "
                "timestamp, outcome, event_type, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "corrupt-latest",
                    "corrupt_action",
                    "LOW",
                    "allow",
                    datetime.now(UTC).isoformat(),
                    "allowed",
                    "decision",
                    "not-valid-json{",
                ),
            )
        result = latest_action_event("corrupt_action")
        assert result is not None
        assert result["metadata"] == {}
        assert "metadata_json" not in result


# --------------------------------------------------------------------------- #
# summarize_autonomy_audit 边界
# --------------------------------------------------------------------------- #


class TestSummarizeAutonomyAudit:
    def test_empty_database_returns_zeros(self):
        summary = summarize_autonomy_audit(days=1)
        assert summary["total"] == 0
        assert summary["veto_count"] == 0
        assert summary["auto_pass_count"] == 0
        assert summary["veto_rate"] == 0.0
        assert summary["auto_pass_rate"] == 0.0
        assert summary["has_prohibited_miss"] is False
        assert summary["cohort"] == "operational"

    def test_days_clamped_to_minimum_1(self):
        summary = summarize_autonomy_audit(days=0)
        assert summary["window_days"] == 1

    def test_days_clamped_to_maximum_3650(self):
        summary = summarize_autonomy_audit(days=99999)
        assert summary["window_days"] == 3650

    def test_include_synthetic_changes_cohort_label(self):
        append_autonomy_audit(
            {
                "action_id": "e2e-synthetic-1",
                "action": "test_action",
                "risk_level": "LOW",
                "decision": "allow",
                "source": "test",
            }
        )
        operational = summarize_autonomy_audit(days=1, include_synthetic=False)
        all_cohort = summarize_autonomy_audit(days=1, include_synthetic=True)
        assert operational["cohort"] == "operational"
        assert all_cohort["cohort"] == "all"
        # operational 不计 e2e- 前缀的 action_id
        assert operational["synthetic_probe_count"] == 1
        # all cohort 包含 synthetic
        assert all_cohort["total"] >= 1

    def test_veto_rate_calculation(self):
        # 2 条 operational：1 allow + 1 require_human
        append_autonomy_audit(
            {
                "action_id": "rate-allow",
                "action": "a1",
                "risk_level": "LOW",
                "decision": "allow",
                "source": "prod",
            }
        )
        append_autonomy_audit(
            {
                "action_id": "rate-veto",
                "action": "a2",
                "risk_level": "MEDIUM",
                "decision": "require_human",
                "source": "prod",
            }
        )
        summary = summarize_autonomy_audit(days=1)
        assert summary["total"] == 2
        assert summary["veto_count"] == 1
        assert summary["veto_rate"] == 50.0
        assert summary["auto_pass_rate"] == 50.0

    def test_observed_days_with_invalid_first_ts_returns_zero(self):
        # 直接插入一条 first_ts 损坏的记录到 autonomy_audit_log
        with sqlite3.connect(_db_path()) as conn:
            conn.execute(
                "INSERT INTO autonomy_audit_log (action_id, action, risk_level, decision, "
                "timestamp, outcome, event_type, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "bad-first-ts",
                    "test_action",
                    "LOW",
                    "allow",
                    "not-an-iso-ts",
                    "allowed",
                    "decision",
                    "{}",
                ),
            )
        summary = summarize_autonomy_audit(days=1)
        # observed_days 在 first_ts 解析失败时应为 0.0
        assert summary["observed_days"] == 0.0

    def test_prohibited_event_count(self):
        append_autonomy_audit(
            {
                "action_id": "prohib-1",
                "action": "db_migration",
                "risk_level": "BLOCKED",
                "decision": "prohibited",
                "source": "prod",
            }
        )
        summary = summarize_autonomy_audit(days=1)
        assert summary["prohibited_event_count"] == 1

    def test_human_approval_count_for_high_risk(self):
        append_autonomy_audit(
            {
                "action_id": "human-approve-1",
                "action": "apply_release",
                "risk_level": "HIGH",
                "decision": "approved",
                "approver": "operator",
                "source": "prod",
            }
        )
        summary = summarize_autonomy_audit(days=1)
        assert summary["human_approval_count"] == 1

    def test_by_decision_and_by_risk_level_breakdowns(self):
        append_autonomy_audit(
            {
                "action_id": "break-1",
                "action": "a1",
                "risk_level": "LOW",
                "decision": "allow",
                "source": "prod",
            }
        )
        append_autonomy_audit(
            {
                "action_id": "break-2",
                "action": "a2",
                "risk_level": "MEDIUM",
                "decision": "require_human",
                "source": "prod",
            }
        )
        summary = summarize_autonomy_audit(days=1)
        assert summary["by_decision"].get("allow") == 1
        assert summary["by_decision"].get("require_human") == 1
        assert summary["by_risk_level"].get("LOW") == 1
        assert summary["by_risk_level"].get("MEDIUM") == 1

    def test_target_veto_rate_bounds(self):
        summary = summarize_autonomy_audit(days=1)
        assert summary["target_veto_rate"]["min"] == 1.0
        assert summary["target_veto_rate"]["max"] == 5.0

    def test_counting_rule_description_present(self):
        summary = summarize_autonomy_audit(days=1)
        assert "unique operational action_id" in summary["counting_rule"]


# --------------------------------------------------------------------------- #
# autonomy_daily_digest_html
# --------------------------------------------------------------------------- #


class TestDailyDigestHtml:
    def test_renders_with_empty_database(self):
        html = autonomy_daily_digest_html(days=1)
        assert "Autonomy 决策" in html
        assert "0 次" in html

    def test_renders_with_data(self):
        append_autonomy_audit(
            {
                "action_id": "digest-1",
                "action": "restart_service",
                "risk_level": "LOW",
                "decision": "allow",
                "source": "prod",
            }
        )
        html = autonomy_daily_digest_html(days=1)
        assert "Autonomy 决策" in html
        assert "30天" in html
        assert "90天" in html

    def test_tone_is_red_when_veto_exists(self):
        append_autonomy_audit(
            {
                "action_id": "veto-digest",
                "action": "rollback_release",
                "risk_level": "MEDIUM",
                "decision": "require_human",
                "source": "prod",
            }
        )
        html = autonomy_daily_digest_html(days=1)
        # veto_count > 0 → tone 为红色 #b91c1c
        assert "#b91c1c" in html

    def test_tone_is_green_when_no_veto(self):
        append_autonomy_audit(
            {
                "action_id": "clean-digest",
                "action": "restart_service",
                "risk_level": "LOW",
                "decision": "allow",
                "source": "prod",
            }
        )
        html = autonomy_daily_digest_html(days=1)
        assert "#047857" in html

    def test_includes_boundary_review_info(self):
        html = autonomy_daily_digest_html(days=1)
        assert "边界复盘" in html
        assert "revision" in html
