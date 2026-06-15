"""COVERAGE_RAMP C3.1: log_subscription_snapshot 启动诊断。

覆盖：
- 空 bus：summary 字典 + log "0 flat event types"
- 有 handler 的 bus：flat + domain + global 计数
- flat 超过 40 个时仍只 sample 40 个
- summary 透传给调用方
"""

from __future__ import annotations

from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.runtime_diagnostics import log_subscription_snapshot


def test_snapshot_empty_bus(caplog):
    bus = NeuroBus(worker_threads=1)
    out = log_subscription_snapshot(bus)
    assert out["flat_event_handlers"] == {}
    assert out["domain_handlers"] == {}
    assert out["global_handlers"] == 0


def test_snapshot_with_handlers(caplog):

    bus = NeuroBus(worker_threads=1)

    async def h1(event):
        return None

    async def h2(event):
        return None

    bus.subscribe("alpha", h1)
    bus.subscribe("alpha", h2)
    bus.subscribe_to_domain("sales", "beta", h1)
    bus.subscribe_all(h1)

    with caplog.at_level("INFO", logger="app.neuro_bus.runtime_diagnostics"):
        out = log_subscription_snapshot(bus)
    assert out["flat_event_handlers"]["alpha"] == 2
    assert out["domain_handlers"]["sales"]["beta"] == 1
    assert out["global_handlers"] == 1
    assert any("NeuroBus subscription snapshot" in r.message for r in caplog.records)


def test_snapshot_sample_caps_at_40(caplog):

    bus = NeuroBus(worker_threads=1)

    async def h(event):
        return None

    # 注册 50 个不同 event_type
    for i in range(50):
        bus.subscribe(f"e{i:02d}", h)

    caplog.clear()
    with caplog.at_level("DEBUG", logger="app.neuro_bus.runtime_diagnostics"):
        out = log_subscription_snapshot(bus)

    assert len(out["flat_event_handlers"]) == 50
    # sample 段只会 log 前 40 个 (look for sample marker)
    debug_records = [r.message for r in caplog.records if "sample" in r.message.lower()]
    assert len(debug_records) >= 1


def test_snapshot_no_sample_when_empty(caplog):

    bus = NeuroBus(worker_threads=1)
    caplog.clear()
    with caplog.at_level("DEBUG", logger="app.neuro_bus.runtime_diagnostics"):
        log_subscription_snapshot(bus)
    # 空 bus 不应进入 sample 分支
    debug_records = [r.message for r in caplog.records if "sample" in r.message.lower()]
    assert debug_records == []


def test_snapshot_summary_returned_is_bus_summarize():
    bus = NeuroBus(worker_threads=1)
    expected = bus.summarize_subscriptions()
    out = log_subscription_snapshot(bus)
    assert out == expected
