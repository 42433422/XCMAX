# NeuroBus 升级批次 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 NeuroBus 升级批次 1（SLA 采集 + Tracer OTel 底层化 + Redis Streams 升级 + 领域文件拆分），为批次 2 的 NN 路由训练铺路。

**Architecture:** 4 个改进项并行无依赖。SLA 采集扩展 `SLAMonitor` 写 jsonl；Tracer 保留接口内部委托 OTel SDK；Redis Streams 新增 `RedisStreamsBridge` 与 PubSub 并存灰度切换；领域文件按 `domain.py + handlers.py` 规范拆分 7 个领域。

**Tech Stack:** Python 3.11 / FastAPI / Redis / OpenTelemetry SDK / pytest / fakeredis

**Spec:** `docs/superpowers/specs/2026-06-19-neurobus-upgrade-design.md`

---

## 文件结构

### 新增文件
- `FHD/app/neuro_bus/sla_collector.py` — SLA 实测采集器
- `FHD/scripts/dev/analyze_sla.py` — SLA 分析报告脚本
- `FHD/app/neuro_bus/transports/redis_streams.py` — Redis Streams 桥接
- `FHD/app/neuro_bus/domains/payment_domain_handlers.py` — payment 处理器
- `FHD/app/neuro_bus/domains/order_domain_handlers.py` — order 处理器
- `FHD/app/neuro_bus/domains/customer_domain_handlers.py` — customer 处理器
- `FHD/app/neuro_bus/domains/ai_service_domain_handlers.py` — ai_service 处理器
- `FHD/app/neuro_bus/domains/intent_domain_handlers.py` — intent 处理器
- `FHD/app/neuro_bus/domains/safety_domain_handlers.py` — safety 处理器
- `FHD/app/neuro_bus/domains/wechat_domain_handlers.py` — wechat 处理器
- `FHD/tests/test_neuro_bus/test_sla_collector.py`
- `FHD/tests/test_neuro_bus/test_tracer_otel.py`
- `FHD/tests/test_neuro_bus/test_redis_streams.py`
- `FHD/tests/test_neuro_bus/test_domain_split.py`

### 修改文件
- `FHD/app/neuro_bus/sla_controller.py` — 集成采集器
- `FHD/app/neuro_bus/tracer.py` — 内部委托 OTel SDK
- `FHD/app/neuro_bus/neuro_http_trace.py` — 改用 OTel Propagator
- `FHD/app/neuro_bus/bus.py` — 支持 transport 切换
- `FHD/app/neuro_bus/initializer.py` — 根据 env 选择 transport
- `FHD/app/neuro_bus/domains/{payment,order,customer,ai_service,intent,safety,wechat}_domain.py` — 迁出处理器 + 加 import *
- `FHD/requirements.txt` — 新增 OTel 依赖
- `FHD/k8s/configmap.yaml` — 新增 OTel/SLA/Streams 环境变量

---

## Task 1: SLA 实测采集器

**Files:**
- Create: `FHD/app/neuro_bus/sla_collector.py`
- Test: `FHD/tests/test_neuro_bus/test_sla_collector.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_neuro_bus/test_sla_collector.py
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_sla_collector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.neuro_bus.sla_collector'`

- [ ] **Step 3: 实现 SLACollector**

```python
# FHD/app/neuro_bus/sla_collector.py
"""SLA 实测采集器 — 写入 jsonl 供离线分析。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.neuro_bus.sla_controller import SLALevel


def _default_measurements_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    d = root / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sla_measurements.jsonl"


def _collect_enabled() -> bool:
    return os.environ.get("XCAGI_NEURO_BUS_SLA_COLLECT", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


class SLACollector:
    """SLA 实测采集器。默认关闭，XCAGI_NEURO_BUS_SLA_COLLECT=1 启用。"""

    def __init__(self) -> None:
        self._path = Path(
            os.environ.get(
                "XCAGI_SLA_MEASUREMENTS_PATH",
                str(_default_measurements_path()),
            )
        )
        self._enabled = _collect_enabled()

    def record(
        self,
        level: SLALevel,
        operation: str,
        latency_ms: float,
        sla_target_ms: float,
        sla_hit: bool,
    ) -> None:
        """记录一次 SLA 测量。"""
        if not self._enabled:
            return
        row = {
            "ts": time.time(),
            "level": level.value,
            "operation": operation,
            "latency_ms": latency_ms,
            "sla_target_ms": sla_target_ms,
            "sla_hit": sla_hit,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_sla_collector.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd FHD && git add app/neuro_bus/sla_collector.py tests/test_neuro_bus/test_sla_collector.py
git commit -m "feat(neuro_bus): add SLA measurement collector with jsonl output"
```

---

## Task 2: SLA 采集器集成到 SLAMonitor

**Files:**
- Modify: `FHD/app/neuro_bus/sla_controller.py:97-113`
- Test: `FHD/tests/test_neuro_bus/test_sla_collector.py`

- [ ] **Step 1: 写失败测试**

追加到 `FHD/tests/test_neuro_bus/test_sla_collector.py`：

```python
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_sla_collector.py::test_sla_monitor_finish_records_to_collector -v`
Expected: FAIL with `TypeError: SLAMonitor.__init__() got an unexpected keyword argument 'collector'`

- [ ] **Step 3: 修改 SLAMonitor 接受 collector**

修改 `FHD/app/neuro_bus/sla_controller.py` 的 `SLAMonitor` 类（约第 66-113 行）：

```python
class SLAMonitor:
    """监控单个操作的 SLA 合规性。"""

    def __init__(
        self,
        sla_timeout: SLATimeout,
        operation_name: str,
        level: SLALevel | None = None,
        collector: "SLACollector | None" = None,
    ):
        self._sla = sla_timeout
        self._operation_name = operation_name
        self._level = level
        self._collector = collector
        self._start_time = time.time()
        self._finished = False

    def check(self) -> dict[str, Any]:
        elapsed_ms = (time.time() - self._start_time) * 1000
        status = "ok"
        if elapsed_ms > self._sla.max_ms:
            status = "violated"
        elif elapsed_ms > self._sla.warning_threshold_ms:
            status = "warning"
        return {
            "operation": self._operation_name,
            "elapsed_ms": elapsed_ms,
            "target_ms": self._sla.target_ms,
            "max_ms": self._sla.max_ms,
            "status": status,
        }

    def finish(self) -> dict[str, Any]:
        self._finished = True
        result = self.check()
        if result["status"] == "violated":
            logger.error(
                f"SLA VIOLATED: {self._operation_name} took {result['elapsed_ms']:.2f}ms, "
                f"max allowed: {self._sla.max_ms}ms"
            )
        elif result["status"] == "warning":
            logger.warning(
                f"SLA WARNING: {self._operation_name} took {result['elapsed_ms']:.2f}ms, "
                f"target: {self._sla.target_ms}ms"
            )
        # 触发采集器记录
        if self._collector is not None and self._level is not None:
            self._collector.record(
                level=self._level,
                operation=self._operation_name,
                latency_ms=result["elapsed_ms"],
                sla_target_ms=self._sla.target_ms,
                sla_hit=result["status"] != "violated",
            )
        return result

    def is_violated(self) -> bool:
        return self.check()["status"] == "violated"
```

同时在文件顶部加 import（TYPE_CHECKING 避免循环）：

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.neuro_bus.sla_collector import SLACollector
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_sla_collector.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd FHD && git add app/neuro_bus/sla_controller.py tests/test_neuro_bus/test_sla_collector.py
git commit -m "feat(neuro_bus): integrate SLACollector into SLAMonitor.finish()"
```

---

## Task 3: SLA 分析脚本

**Files:**
- Create: `FHD/scripts/dev/analyze_sla.py`

- [ ] **Step 1: 实现分析脚本**

```python
#!/usr/bin/env python3
"""SLA 实测分析报告 — 读取 sla_measurements.jsonl，输出 P50/P99/P999 + 达标率。"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def analyze(log_path: Path) -> dict:
    """分析 SLA 测量数据。"""
    by_level_op: dict[str, list[float]] = defaultdict(list)
    sla_hit_count: dict[str, int] = defaultdict(int)
    total_count: dict[str, int] = defaultdict(int)

    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = f"{row['level']}@{row['operation']}"
            by_level_op[key].append(row["latency_ms"])
            total_count[key] += 1
            if row["sla_hit"]:
                sla_hit_count[key] += 1

    report = {}
    for key, latencies in by_level_op.items():
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        p50 = latencies_sorted[int(n * 0.50)]
        p99 = latencies_sorted[int(n * 0.99)] if n >= 100 else latencies_sorted[-1]
        p999 = latencies_sorted[int(n * 0.999)] if n >= 1000 else latencies_sorted[-1]
        hit_rate = sla_hit_count[key] / total_count[key] if total_count[key] else 0.0
        report[key] = {
            "count": n,
            "p50_ms": round(p50, 3),
            "p99_ms": round(p99, 3),
            "p999_ms": round(p999, 3),
            "sla_hit_rate": round(hit_rate, 4),
        }
    return report


def main() -> int:
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("metrics/sla_measurements.jsonl")
    if not log_path.exists():
        print(f"ERROR: {log_path} not found", file=sys.stderr)
        return 1

    report = analyze(log_path)
    print(f"{'Level@Operation':<40} {'Count':>6} {'P50ms':>8} {'P99ms':>8} {'P999ms':>8} {'HitRate':>8}")
    print("-" * 80)
    for key, stats in sorted(report.items()):
        print(
            f"{key:<40} {stats['count']:>6} {stats['p50_ms']:>8} "
            f"{stats['p99_ms']:>8} {stats['p999_ms']:>8} {stats['sla_hit_rate']:>8.2%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 验证脚本可运行**

Run: `cd FHD && python scripts/dev/analyze_sla.py`
Expected: 输出表头（无数据时）

- [ ] **Step 3: Commit**

```bash
cd FHD && git add scripts/dev/analyze_sla.py
git commit -m "feat(neuro_bus): add SLA analysis script with P50/P99/P999 + hit rate"
```

---

## Task 4: Tracer OTel 底层化 — 降级路径测试

**Files:**
- Create: `FHD/tests/test_neuro_bus/test_tracer_otel.py`

- [ ] **Step 1: 写降级路径测试（OTel 未安装时）**

```python
# FHD/tests/test_neuro_bus/test_tracer_otel.py
"""Tracer OTel 集成测试。"""
import sys
from unittest.mock import patch

import pytest


def test_span_creates_without_otel(monkeypatch):
    """OTel SDK 不可用时，Span 退化为内存对象。"""
    # 模拟 OTel 不可用
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)

    from app.neuro_bus.tracer import Span, SpanStatus

    span = Span(
        span_id="",
        trace_id="trace-1",
        parent_id=None,
        name="test.op",
        start_time=0.0,
    )
    assert span.span_id  # 自动生成
    assert span.status == SpanStatus.OK
    span.set_tag("key", "value")
    assert span.tags["key"] == "value"
    span.add_event("event1", {"attr": 1})
    assert len(span.events) == 1
    span.finish()
    assert span.end_time is not None


def test_span_finish_sets_status_error():
    """finish(ERROR) 设置错误状态。"""
    from app.neuro_bus.tracer import Span, SpanStatus

    span = Span(
        span_id="s1",
        trace_id="t1",
        parent_id=None,
        name="test.fail",
        start_time=0.0,
    )
    span.finish(SpanStatus.ERROR)
    assert span.status == SpanStatus.ERROR


def test_span_duration_ms():
    """duration_ms 正确计算。"""
    from app.neuro_bus.tracer import Span

    span = Span(
        span_id="s1",
        trace_id="t1",
        parent_id=None,
        name="test.dur",
        start_time=100.0,
    )
    span.end_time = 100.5
    assert span.duration_ms == 500.0
```

- [ ] **Step 2: 运行测试验证通过（当前行为已满足）**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_tracer_otel.py -v`
Expected: 3 passed（当前 Span 已是内存对象）

- [ ] **Step 3: Commit**

```bash
cd FHD && git add tests/test_neuro_bus/test_tracer_otel.py
git commit -m "test(neuro_bus): add tracer degradation path tests"
```

---

## Task 5: Tracer OTel 底层委托

**Files:**
- Modify: `FHD/app/neuro_bus/tracer.py`
- Test: `FHD/tests/test_neuro_bus/test_tracer_otel.py`

- [ ] **Step 1: 写 OTel 委托测试**

追加到 `FHD/tests/test_neuro_bus/test_tracer_otel.py`：

```python
def test_span_delegates_to_otel_when_available(monkeypatch):
    """OTel 可用时，Span 委托给 OTel SDK。"""
    # 创建 mock OTel 模块
    mock_span = MagicMock()
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    mock_trace = MagicMock()
    mock_trace.get_tracer.return_value = mock_tracer

    mock_otel = MagicMock()
    mock_otel.trace = mock_trace

    monkeypatch.setitem(sys.modules, "opentelemetry", mock_otel)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)

    from app.neuro_bus.tracer import Span

    span = Span(
        span_id="",
        trace_id="t1",
        parent_id=None,
        name="otel.test",
        start_time=0.0,
    )
    span.set_tag("env", "test")
    span.add_event("started", {"k": 1})
    span.finish()

    mock_span.set_attribute.assert_called_with("env", "test")
    mock_span.add_event.assert_called_with("started", {"k": 1})
    mock_span.end.assert_called_once()
```

需要在文件顶部加 import：

```python
from unittest.mock import MagicMock, patch
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_tracer_otel.py::test_span_delegates_to_otel_when_available -v`
Expected: FAIL（当前 Span 不委托 OTel）

- [ ] **Step 3: 修改 tracer.py 委托 OTel**

修改 `FHD/app/neuro_bus/tracer.py`，在 `Span` 类中加 OTel 委托：

```python
# 文件顶部新增
try:
    from opentelemetry import trace as otel_trace
    _OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None
    _OTEL_AVAILABLE = False


@dataclass
class Span:
    """追踪 Span — 内部委托 OTel SDK（可用时）。"""

    span_id: str
    trace_id: str
    parent_id: str | None
    name: str
    start_time: float
    end_time: float | None = None
    status: SpanStatus = SpanStatus.OK
    tags: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.span_id:
            self.span_id = str(uuid.uuid4())[:16]
        # 委托 OTel SDK
        self._otel_span = None
        if _OTEL_AVAILABLE:
            tracer = otel_trace.get_tracer("xcagi.neurobus")
            self._otel_span = tracer.start_as_current_span(self.name).__enter__()

    def finish(self, status: SpanStatus = SpanStatus.OK):
        self.end_time = time.time()
        self.status = status
        if self._otel_span is not None:
            self._otel_span.end()

    def add_event(self, name: str, attributes: dict[str, Any] | None = None):
        self.events.append({"name": name, "timestamp": time.time(), "attributes": attributes or {}})
        if self._otel_span is not None:
            self._otel_span.add_event(name, attributes or {})

    def set_tag(self, key: str, value: Any):
        self.tags[key] = value
        if self._otel_span is not None:
            self._otel_span.set_attribute(key, value)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_tracer_otel.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd FHD && git add app/neuro_bus/tracer.py tests/test_neuro_bus/test_tracer_otel.py
git commit -m "feat(neuro_bus): delegate Span to OTel SDK when available"
```

---

## Task 6: 新增 OTel 依赖

**Files:**
- Modify: `FHD/requirements.txt`

- [ ] **Step 1: 添加 OTel 依赖**

在 `FHD/requirements.txt` 末尾追加：

```
# OpenTelemetry (NeuroBus tracer 底层)
opentelemetry-api>=1.24.0
opentelemetry-sdk>=1.24.0
opentelemetry-exporter-otlp>=1.24.0
```

- [ ] **Step 2: 验证依赖可安装**

Run: `cd FHD && pip install -r requirements.txt --dry-run 2>&1 | grep opentelemetry`
Expected: 显示 opentelemetry-api/sdk/exporter-otlp

- [ ] **Step 3: Commit**

```bash
cd FHD && git add requirements.txt
git commit -m "deps: add OpenTelemetry SDK for NeuroBus tracer"
```

---

## Task 7: Redis Streams Bridge — 基础测试

**Files:**
- Create: `FHD/tests/test_neuro_bus/test_redis_streams.py`

- [ ] **Step 1: 写 Streams 基础测试**

```python
# FHD/tests/test_neuro_bus/test_redis_streams.py
"""Redis Streams Bridge 测试。"""
import json
from unittest.mock import MagicMock, patch

import pytest


def test_streams_bridge_publish_calls_xadd(monkeypatch):
    """publish 调用 XADD。"""
    mock_redis = MagicMock()
    mock_redis.xadd.return_value = b"1234567890-0"

    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    event_dict = {"event_type": "test.event", "data": "hello"}
    bridge.publish(event_dict)

    mock_redis.xadd.assert_called_once()
    args, kwargs = mock_redis.xadd.call_args
    assert args[0] == "neurobus:events"
    assert "payload" in kwargs["fields"]
    assert kwargs["maxlen"] == 100000


def test_streams_bridge_consume_calls_xreadgroup(monkeypatch):
    """consume 调用 XREADGROUP。"""
    mock_redis = MagicMock()
    mock_redis.xreadgroup.return_value = [
        (b"neurobus:events", [(b"1234567890-0", {b"payload": b'{"event_type":"test"}'})])
    ]

    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    messages = bridge.consume(count=10, block_ms=1000)

    mock_redis.xreadgroup.assert_called_once()
    assert len(messages) == 1
    assert messages[0]["event_type"] == "test"


def test_streams_bridge_ack_calls_xack():
    """ack 调用 XACK。"""
    mock_redis = MagicMock()
    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    bridge.ack("1234567890-0")

    mock_redis.xack.assert_called_once_with("neurobus:events", "neurobus-workers", "1234567890-0")


def test_streams_bridge_send_to_dlq():
    """失败消息转入 DLQ stream。"""
    mock_redis = MagicMock()
    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    bridge.send_to_dlq({"event_type": "failed"}, "1234567890-0")

    mock_redis.xadd.assert_called_once()
    args, kwargs = mock_redis.xadd.call_args
    assert args[0] == "neurobus:dlq"
    mock_redis.xack.assert_called_once()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_redis_streams.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.neuro_bus.transports.redis_streams'`

- [ ] **Step 3: Commit 测试**

```bash
cd FHD && git add tests/test_neuro_bus/test_redis_streams.py
git commit -m "test(neuro_bus): add Redis Streams bridge tests"
```

---

## Task 8: Redis Streams Bridge 实现

**Files:**
- Create: `FHD/app/neuro_bus/transports/redis_streams.py`

- [ ] **Step 1: 实现 RedisStreamsBridge**

```python
# FHD/app/neuro_bus/transports/redis_streams.py
"""Redis Streams 桥 — 跨 Pod 事件广播，消费确认 + 持久化 + DLQ。

启用：XCAGI_NEURO_BUS_REDIS_TRANSPORT=streams
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.neuro_bus.bus import NeuroBus

STREAM_KEY = "neurobus:events"
DLQ_KEY = "neurobus:dlq"
CONSUMER_GROUP = "neurobus-workers"
MAXLEN = 100000


def streams_enabled() -> bool:
    return os.environ.get("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "").strip().lower() == "streams"


class RedisStreamsBridge:
    """Redis Streams 桥接器。"""

    def __init__(
        self,
        bus: "NeuroBus",
        redis_client: Any | None = None,
        consumer_id: str | None = None,
    ) -> None:
        self._bus = bus
        self._redis = redis_client
        self._consumer_id = consumer_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._ensure_group()

    def _ensure_group(self) -> None:
        """确保消费组存在。"""
        if self._redis is None:
            return
        try:
            self._redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True)
            logger.info("created consumer group %s on %s", CONSUMER_GROUP, STREAM_KEY)
        except Exception as e:
            # BUSYGROUP 表示已存在
            if "BUSYGROUP" not in str(e):
                logger.debug("xgroup create: %s", e)

    def publish(self, event_dict: dict[str, Any]) -> str | None:
        """发布事件到 Stream。"""
        if self._redis is None:
            return None
        msg_id = self._redis.xadd(
            STREAM_KEY,
            {"payload": json.dumps(event_dict, ensure_ascii=False)},
            maxlen=MAXLEN,
            approximate=True,
        )
        return msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

    def consume(self, count: int = 100, block_ms: int = 5000) -> list[dict[str, Any]]:
        """从 Stream 消费消息（不自动 ACK）。"""
        if self._redis is None:
            return []
        result = self._redis.xreadgroup(
            CONSUMER_GROUP,
            self._consumer_id,
            {STREAM_KEY: ">"},
            count=count,
            block=block_ms,
        )
        messages: list[dict[str, Any]] = []
        for _stream, entries in result:
            for msg_id, fields in entries:
                payload = fields.get(b"payload") or fields.get("payload")
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                try:
                    msg = json.loads(payload)
                    msg["_msg_id"] = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                    messages.append(msg)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning("failed to decode stream message %s: %s", msg_id, e)
                    self.ack(msg_id)
        return messages

    def ack(self, msg_id: str) -> None:
        """确认消息已处理。"""
        if self._redis is None:
            return
        self._redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)

    def send_to_dlq(self, event_dict: dict[str, Any], original_msg_id: str) -> None:
        """失败消息转入 DLQ 并 ACK 原消息。"""
        if self._redis is None:
            return
        self._redis.xadd(
            DLQ_KEY,
            {"payload": json.dumps(event_dict, ensure_ascii=False), "original_id": original_msg_id},
            maxlen=MAXLEN,
            approximate=True,
        )
        self.ack(original_msg_id)
        logger.warning("message %s moved to DLQ", original_msg_id)
```

- [ ] **Step 2: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_redis_streams.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
cd FHD && git add app/neuro_bus/transports/redis_streams.py
git commit -m "feat(neuro_bus): add Redis Streams bridge with XADD/XREADGROUP/XACK/DLQ"
```

---

## Task 9: Bus 支持 transport 切换

**Files:**
- Modify: `FHD/app/neuro_bus/initializer.py`

- [ ] **Step 1: 修改 initializer 支持 transport 切换**

在 `FHD/app/neuro_bus/initializer.py` 中找到 transport 初始化逻辑，添加 Streams 切换：

```python
# 在 initializer.py 顶部加 import
from app.neuro_bus.transports.redis_streams import RedisStreamsBridge, streams_enabled

# 在 transport 初始化函数中（找到 RedisPubSubBridge 初始化处）添加：
def _init_transport(bus):
    """根据环境变量选择 transport。"""
    if streams_enabled():
        # Streams 模式
        redis_client = _get_redis_client()  # 复用现有 redis 获取逻辑
        bridge = RedisStreamsBridge(bus=bus, redis_client=redis_client)
        logger.info("NeuroBus transport: redis_streams")
        return bridge
    elif redis_pubsub_enabled():
        # PubSub 模式（现有）
        bridge = RedisPubSubBridge(bus=bus)
        logger.info("NeuroBus transport: redis_pubsub")
        return bridge
    else:
        logger.info("NeuroBus transport: local_only")
        return None
```

注意：实际实现需根据 `initializer.py` 现有结构调整。先读现有代码再改。

- [ ] **Step 2: 验证切换逻辑**

Run: `cd FHD && XCAGI_NEURO_BUS_REDIS_TRANSPORT=streams python -c "from app.neuro_bus.transports.redis_streams import streams_enabled; print(streams_enabled())"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
cd FHD && git add app/neuro_bus/initializer.py
git commit -m "feat(neuro_bus): support transport switching via XCAGI_NEURO_BUS_REDIS_TRANSPORT"
```

---

## Task 10-16: 领域文件拆分（7 个领域）

每个领域拆分遵循相同模式。以 `payment` 为例，其余 6 个领域同理。

### Task 10: payment 领域拆分

**Files:**
- Create: `FHD/app/neuro_bus/domains/payment_domain_handlers.py`
- Modify: `FHD/app/neuro_bus/domains/payment_domain.py`

- [ ] **Step 1: 读取 payment_domain.py 现有内容**

Run: `cd FHD && wc -l app/neuro_bus/domains/payment_domain.py`

- [ ] **Step 2: 创建 payment_domain_handlers.py，迁出所有处理器函数**

将 `payment_domain.py` 中所有 `@handler` 装饰的函数和处理器依赖的 import 迁移到新文件。新文件结构：

```python
# FHD/app/neuro_bus/domains/payment_domain_handlers.py
"""Payment 领域处理器逻辑。"""
# 迁移所有 @handler 函数 + 处理器依赖的 import
```

- [ ] **Step 3: 修改 payment_domain.py，末尾加 import ***

```python
# FHD/app/neuro_bus/domains/payment_domain.py 末尾追加
from .payment_domain_handlers import *  # noqa: F401,F403  向后兼容
```

- [ ] **Step 4: 验证导入兼容**

Run: `cd FHD && python -c "from app.neuro_bus.domains import payment_domain; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd FHD && git add app/neuro_bus/domains/payment_domain.py app/neuro_bus/domains/payment_domain_handlers.py
git commit -m "refactor(neuro_bus): split payment domain into domain + handlers"
```

### Task 11-16: 其余 6 个领域拆分

对 `order` / `customer` / `ai_service` / `intent` / `safety` / `wechat` 重复 Task 10 的 5 个步骤。每个领域一个 commit。

---

## Task 17: 领域拆分兼容性测试

**Files:**
- Create: `FHD/tests/test_neuro_bus/test_domain_split.py`

- [ ] **Step 1: 写兼容性测试**

```python
# FHD/tests/test_neuro_bus/test_domain_split.py
"""领域拆分后导入兼容性测试。"""
import importlib

import pytest


@pytest.mark.parametrize(
    "domain_name",
    [
        "payment", "order", "customer", "ai_service",
        "intent", "safety", "wechat",
    ],
)
def test_domain_imports_handlers(domain_name):
    """domain.py 通过 import * 暴露 handlers 的所有符号。"""
    domain_mod = importlib.import_module(f"app.neuro_bus.domains.{domain_name}_domain")
    handlers_mod = importlib.import_module(f"app.neuro_bus.domains.{domain_name}_domain_handlers")
    # domain 模块应能正常导入
    assert domain_mod is not None
    assert handlers_mod is not None


def test_already_split_domains_unchanged():
    """已拆分的领域（ocr/print/shipment/inventory/product）保持不变。"""
    for name in ["ocr", "print", "shipment", "inventory", "product"]:
        mod = importlib.import_module(f"app.neuro_bus.domains.{name}_domain")
        assert mod is not None
```

- [ ] **Step 2: 运行测试**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_domain_split.py -v`
Expected: 8 passed

- [ ] **Step 3: Commit**

```bash
cd FHD && git add tests/test_neuro_bus/test_domain_split.py
git commit -m "test(neuro_bus): add domain split compatibility tests"
```

---

## Task 18: K8s ConfigMap 更新

**Files:**
- Modify: `FHD/k8s/configmap.yaml`

- [ ] **Step 1: 添加新环境变量**

在 `FHD/k8s/configmap.yaml` 的 NeuroBus 配置段追加：

```yaml
# SLA 采集
XCAGI_NEURO_BUS_SLA_COLLECT: "1"
# Redis transport（staging 用 streams 灰度）
XCAGI_NEURO_BUS_REDIS_TRANSPORT: "streams"
# OTel exporter
OTEL_EXPORTER_OTLP_ENDPOINT: "http://otel-collector.observability:4317"
OTEL_SERVICE_NAME: "xcagi-neurobus"
```

- [ ] **Step 2: Commit**

```bash
cd FHD && git add k8s/configmap.yaml
git commit -m "ops(k8s): add SLA/Streams/OTel env vars to NeuroBus configmap"
```

---

## Task 19: 全量回归测试

- [ ] **Step 1: 运行 NeuroBus 全量测试**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/ -v --tb=short`
Expected: 全部通过（含新增测试）

- [ ] **Step 2: 运行覆盖率检查**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/ --cov=app/neuro_bus --cov-report=term-missing`
Expected: 覆盖率不回退

- [ ] **Step 3: 运行 ruff lint**

Run: `cd FHD && ruff check app/neuro_bus/ tests/test_neuro_bus/`
Expected: 无错误

- [ ] **Step 4: 运行 mypy**

Run: `cd FHD && mypy app/neuro_bus/ --no-error-summary`
Expected: 无新增错误

- [ ] **Step 5: 最终 commit（如有 lint 修复）**

```bash
cd FHD && git add -A && git commit -m "chore(neuro_bus): batch1 lint and type fixes"
```

---

## 验收清单

批次 1 完成后必须满足：

- [ ] `SLACollector` 写入 `sla_measurements.jsonl`，`analyze_sla.py` 输出报告
- [ ] `Span` 在 OTel 可用时委托 SDK，不可用时降级为内存对象
- [ ] `RedisStreamsBridge` 支持 XADD/XREADGROUP/XACK/DLQ
- [ ] 7 个领域文件拆分完成，`import *` 兼容性测试通过
- [ ] `XCAGI_NEURO_BUS_REDIS_TRANSPORT=streams` 可切换 transport
- [ ] 全量 `pytest tests/test_neuro_bus/` 通过
- [ ] ruff lint 无错误
- [ ] mypy 无新增错误
- [ ] K8s configmap 含新环境变量

## 批次 2 启动条件

- 批次 1 全部验收通过
- `sla_measurements.jsonl` 积累 2 周数据（约 100 万条）
- staging 环境 Streams 模式稳定运行 1 周
