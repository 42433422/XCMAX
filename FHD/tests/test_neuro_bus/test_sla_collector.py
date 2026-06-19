"""SLA 采集器单测。"""
import json
from pathlib import Path

from app.neuro_bus.sla_collector import SLACollector
from app.neuro_bus.sla_controller import SLALevel


def test_record_measurement_writes_jsonl(tmp_path, monkeypatch):
    """采集器写入 jsonl 文件。"""
    log_path = tmp_path / "sla_measurements.jsonl"
    monkeypatch.setenv("XCAGI_NEURO_BUS_SLA_COLLECT", "1")
    monkeypatch.setenv("XCAGI_SLA_MEASUREMENTS_PATH", str(log_path))

    collector = SLACollector()
    collector.record(
        level=SLALevel.REFLEX,
        operation="greeting@ai_service",
        latency_ms=0.8,
        sla_target_ms=1.0,
        sla_hit=True,
    )

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["level"] == "reflex"
    assert row["operation"] == "greeting@ai_service"
    assert row["latency_ms"] == 0.8
    assert row["sla_target_ms"] == 1.0
    assert row["sla_hit"] is True


def test_collector_disabled_by_default(tmp_path, monkeypatch):
    """默认关闭时不写入。"""
    monkeypatch.delenv("XCAGI_NEURO_BUS_SLA_COLLECT", raising=False)
    log_path = tmp_path / "sla_measurements.jsonl"
    monkeypatch.setenv("XCAGI_SLA_MEASUREMENTS_PATH", str(log_path))

    collector = SLACollector()
    collector.record(
        level=SLALevel.CONSCIOUS,
        operation="order.create@order",
        latency_ms=150.0,
        sla_target_ms=200.0,
        sla_hit=True,
    )

    assert not log_path.exists()


def test_record_multiple_measurements_append(tmp_path, monkeypatch):
    """多次采集追加写入。"""
    monkeypatch.setenv("XCAGI_NEURO_BUS_SLA_COLLECT", "1")
    log_path = tmp_path / "sla_measurements.jsonl"
    monkeypatch.setenv("XCAGI_SLA_MEASUREMENTS_PATH", str(log_path))

    collector = SLACollector()
    for i in range(5):
        collector.record(
            level=SLALevel.SUBCONSCIOUS,
            operation=f"task_{i}@bg",
            latency_ms=float(i),
            sla_target_ms=10.0,
            sla_hit=i < 10,
        )

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5


def test_sla_monitor_finish_records_to_collector(tmp_path, monkeypatch):
    """SLAMonitor.finish() 触发采集器记录。"""
    monkeypatch.setenv("XCAGI_NEURO_BUS_SLA_COLLECT", "1")
    log_path = tmp_path / "sla_measurements.jsonl"
    monkeypatch.setenv("XCAGI_SLA_MEASUREMENTS_PATH", str(log_path))

    from app.neuro_bus.sla_collector import SLACollector
    from app.neuro_bus.sla_controller import SLAConfig, SLAMonitor

    collector = SLACollector()
    monitor = SLAMonitor(
        sla_timeout=SLAConfig.REFLEX,
        operation_name="greeting@ai_service",
        collector=collector,
    )
    monitor.finish()

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["operation"] == "greeting@ai_service"
    assert row["level"] == "reflex"
