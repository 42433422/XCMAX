"""routing_log.append_routing_decision 字段扩展测试。"""

import json
import os
from pathlib import Path

from app.neuro_bus.routing import routing_log
from app.neuro_bus.routing.routing_log import append_routing_decision


def _read_rows(log_path: Path) -> list[dict]:
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line]


def test_append_writes_basic_fields(tmp_path, monkeypatch):
    """基础字段（ts/trace_id/features/action/latency_ms/outcome/reward/extra）写入。"""
    log_path = tmp_path / "routing_decisions.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    append_routing_decision(
        trace_id="tid-1",
        features=[0.1, 0.2],
        action="reflex",
        latency_ms=1.5,
        outcome="policy_selected",
        reward=0.8,
        extra={"source": "policy_mlp"},
    )

    rows = _read_rows(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["trace_id"] == "tid-1"
    assert row["features"] == [0.1, 0.2]
    assert row["action"] == "reflex"
    assert row["latency_ms"] == 1.5
    assert row["outcome"] == "policy_selected"
    assert row["reward"] == 0.8
    assert row["extra"] == {"source": "policy_mlp"}
    assert "ts" in row


def test_append_writes_sla_hit_and_success_when_provided(tmp_path, monkeypatch):
    """sla_hit/success 显式传入时写入 jsonl。"""
    log_path = tmp_path / "routing_decisions.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    append_routing_decision(
        trace_id="tid-2",
        features=[0.3],
        action="subconscious",
        latency_ms=12.0,
        outcome="policy_selected",
        reward=1.0,
        extra={"source": "policy_mlp"},
        sla_hit=True,
        success=True,
    )

    rows = _read_rows(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["sla_hit"] is True
    assert row["success"] is True


def test_append_writes_none_when_sla_hit_and_success_omitted(tmp_path, monkeypatch):
    """sla_hit/success 未传时默认 None（向后兼容）。"""
    log_path = tmp_path / "routing_decisions.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    append_routing_decision(
        trace_id="tid-3",
        features=[0.4],
        action="conscious",
        latency_ms=200.0,
        outcome="policy_selected",
    )

    rows = _read_rows(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["sla_hit"] is None
    assert row["success"] is None


def test_append_writes_false_values(tmp_path, monkeypatch):
    """sla_hit=False / success=False 边界值正确写入。"""
    log_path = tmp_path / "routing_decisions.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    append_routing_decision(
        trace_id="tid-4",
        features=[0.5],
        action="reflex",
        latency_ms=2.0,
        outcome="policy_selected",
        sla_hit=False,
        success=False,
    )

    rows = _read_rows(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["sla_hit"] is False
    assert row["success"] is False


def test_append_multiple_rows_accumulate(tmp_path, monkeypatch):
    """多次调用追加写入，不覆盖。"""
    log_path = tmp_path / "routing_decisions.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    append_routing_decision(
        trace_id="tid-a",
        features=[0.1],
        action="reflex",
        latency_ms=1.0,
        outcome="policy_selected",
        sla_hit=True,
        success=True,
    )
    append_routing_decision(
        trace_id="tid-b",
        features=[0.2],
        action="conscious",
        latency_ms=250.0,
        outcome="policy_selected",
        sla_hit=False,
        success=False,
    )

    rows = _read_rows(log_path)
    assert len(rows) == 2
    assert rows[0]["trace_id"] == "tid-a"
    assert rows[0]["sla_hit"] is True
    assert rows[1]["trace_id"] == "tid-b"
    assert rows[1]["sla_hit"] is False


def test_append_creates_parent_directory(tmp_path, monkeypatch):
    """父目录不存在时自动创建。"""
    log_path = tmp_path / "nested" / "deep" / "routing_decisions.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    append_routing_decision(
        trace_id="tid-5",
        features=[0.6],
        action="reflex",
        latency_ms=0.5,
        outcome="policy_selected",
        sla_hit=None,
        success=None,
    )

    assert log_path.exists()
    rows = _read_rows(log_path)
    assert rows[0]["sla_hit"] is None
    assert rows[0]["success"] is None


def test_default_log_path_uses_desktop_data_dir_not_signed_bundle(tmp_path, monkeypatch):
    """Packaged desktop telemetry must never mutate Contents/Resources."""
    desktop_data_dir = tmp_path / "Library" / "Application Support" / "XCAGI"
    signed_bundle_root = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend" / "_internal"
    monkeypatch.delenv("XCAGI_ROUTING_LOG_PATH", raising=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(desktop_data_dir))
    monkeypatch.setattr(routing_log, "_is_frozen_runtime", lambda: True)

    log_path = routing_log._default_log_path()

    assert log_path == desktop_data_dir / "logs" / "routing_policies" / "routing_decisions.jsonl"
    assert log_path.parent.is_dir()
    assert not log_path.is_relative_to(signed_bundle_root)


def test_default_log_path_uses_user_data_when_frozen_env_is_missing(tmp_path, monkeypatch):
    """A missing Electron env still cannot redirect writes into the bundle."""
    fallback_data_dir = tmp_path / "Library" / "Application Support" / "XCAGI"
    monkeypatch.delenv("XCAGI_ROUTING_LOG_PATH", raising=False)
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.setattr(routing_log, "_is_frozen_runtime", lambda: True)
    monkeypatch.setattr(routing_log, "get_app_data_dir", lambda: str(fallback_data_dir))

    log_path = routing_log._default_log_path()

    assert log_path == fallback_data_dir / "logs" / "routing_policies" / "routing_decisions.jsonl"
    assert log_path.parent.is_dir()
