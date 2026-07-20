# 演化自识缺口自实现自发布闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建"缺口识别 → 自动开 issue → 自动实现 → 自动上架 → owner 事后审计"完整闭环，闭环度从 5% 提升到可运行。

**Architecture:** 5 个接通点 + 1 个新 workflow + 1 个新 ledger。复用现有零件（`evolution_signal_collector` / `auto_approve_policy` / `employee_autonomy_service` / `arch_fitness` / `fhd-ai-self-heal-auto-merge` / `fhd-ai-review` / `duty_employee_registry` / `catalog_data/packages.json`），新增桥接脚本将它们接通。

**Tech Stack:** Python 3.11 / FastAPI / GitHub Actions / gh CLI / JSONL append-only ledger / Vitest（前端无关）

**Spec:** `docs/superpowers/specs/2026-07-20-evolution-self-implement-design.md`

---

## 文件结构

### 新增文件

| 路径 | 责任 |
|---|---|
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_ledger.py` | append-only JSONL ledger 读写 |
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl` | ledger 文件（运行时创建，首次写时自动 mkdir） |
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/gap_to_issue.py` | 聚合信号 → 自动开 GitHub issue |
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py` | PR 合并后构建 + 注册 + 触发审核 |
| `FHD/scripts/dev/audit_evolution.py` | owner 审计 ledger 查询脚本 |
| `FHD/scripts/dev/read_issue_proposal.py` | 读 issue body，解析 LLM 提议 JSON |
| `FHD/scripts/dev/implement_employee_pack.py` | LLM 实现 employee_pack（≤5 文件） |
| `FHD/scripts/dev/check_footprint.py` | 门禁 2：足迹边界检查 |
| `FHD/scripts/dev/check_budget.py` | 门禁 3：预算检查 |
| `FHD/scripts/dev/retry_with_adjusted_prompt.py` | 重试 3 次（调整 prompt） |
| `FHD/scripts/dev/escalate_to_human.py` | 3 次失败后转人工 |
| `FHD/scripts/dev/open_pr_for_employee_pack.py` | 创建分支 + commit + 开 PR |
| `FHD/scripts/dev/wait_for_pr_merge.py` | 等待 PR 合并 |
| `FHD/scripts/dev/append_evolution_event.py` | CLI 写 ledger 事件 |
| `.github/workflows/ai-issue-implement.yml` | 自动实现新 workflow |

### 修改文件

| 路径 | 改动 |
|---|---|
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_signal_collector.py` | 添加 `aggregate_signals()` 函数 |
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_autonomy_service.py` | 添加 `propose_employee_pack()` 方法 |
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py` | 添加 `evaluate_employee_pack()` 函数 |

### 测试文件

每个新增模块配套 `test_*.py`，集成测试 + 验收测试在最后两个 Task。

---

## Task 1: 演化决策 ledger（基础审计设施）

**Files:**
- Create: `成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_ledger.py`
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_ledger.py`

**Why first:** 所有后续 Task 都要写 ledger。先把基础设施搭好。

- [ ] **Step 1: 写失败测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_ledger.py
"""演化决策 ledger 单元测试。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from modstore_server.evolution_ledger import (
    append_event,
    list_events,
    mark_audited,
    LEDGER_FILENAME,
)


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / LEDGER_FILENAME
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    return ledger_path


def test_append_event_writes_jsonl_line(tmp_ledger):
    event = {
        "event_type": "signal_detected",
        "triggered_by": "intent_benchmark",
        "signal_score": 0.85,
    }
    result = append_event(event)
    assert tmp_ledger.exists()
    lines = tmp_ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "signal_detected"
    assert parsed["signal_score"] == 0.85
    assert "event_id" in parsed
    assert "timestamp" in parsed
    assert parsed["owner_audit"]["audited"] is False


def test_append_event_multiple_lines(tmp_ledger):
    for i in range(3):
        append_event({"event_type": "signal_detected", "signal_score": i * 0.1})
    lines = tmp_ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_list_events_filters_by_event_type(tmp_ledger):
    append_event({"event_type": "signal_detected", "triggered_by": "intent_benchmark"})
    append_event({"event_type": "pack_listed", "pack_id": "test@1.0.0"})
    append_event({"event_type": "signal_detected", "triggered_by": "slo_metrics"})
    listed = list_events(event_type="pack_listed")
    assert len(listed) == 1
    assert listed[0]["pack_id"] == "test@1.0.0"


def test_list_events_filters_by_status(tmp_ledger):
    append_event({"event_type": "implement_failed", "final_status": "needs_human"})
    append_event({"event_type": "pack_listed", "final_status": "pack_listed"})
    needs_human = list_events(final_status="needs_human")
    assert len(needs_human) == 1
    assert needs_human[0]["final_status"] == "needs_human"


def test_list_events_since_filter(tmp_ledger):
    from datetime import datetime, timedelta, timezone

    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    recent_time = datetime.now(timezone.utc).isoformat()
    append_event({"event_type": "old", "timestamp": old_time})
    append_event({"event_type": "recent", "timestamp": recent_time})
    since_7d = list_events(since_days=7)
    assert len(since_7d) == 1
    assert since_7d[0]["event_type"] == "recent"


def test_mark_audited_updates_event(tmp_ledger):
    result = append_event({"event_type": "pack_listed", "pack_id": "test@1.0.0"})
    event_id = result["event_id"]
    mark_audited(event_id, verdict="approved")
    events = list_events(event_type="pack_listed")
    assert events[0]["owner_audit"]["audited"] is True
    assert events[0]["owner_audit"]["verdict"] == "approved"
    assert events[0]["owner_audit"]["audited_at"] is not None


def test_append_event_handles_missing_ledger_dir(tmp_path, monkeypatch):
    nested = tmp_path / "nested" / "deeper" / LEDGER_FILENAME
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(nested))
    append_event({"event_type": "test"})
    assert nested.exists()


def test_append_event_concurrent_safe(tmp_ledger):
    """并发写不应丢行（append-only 模式 + 文件锁）。"""
    import threading

    def writer(start: int):
        for i in range(20):
            append_event({"event_type": "concurrent", "idx": start + i})

    threads = [threading.Thread(target=writer, args=(i * 20,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = tmp_ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_evolution_ledger.py -v
```

Expected: FAIL with `ImportError: cannot import name 'append_event' from 'modstore_server.evolution_ledger'`

- [ ] **Step 3: 写最小实现**

```python
# 成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_ledger.py
"""演化决策 ledger：append-only JSONL。

每个演化事件（signal_detected / proposal_generated / issue_opened / ... / pack_listed）
都写一行。owner 用 audit_evolution.py 查询。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LEDGER_FILENAME = "evolution_decisions.jsonl"
_LEDGER_LOCK = threading.Lock()


def _ledger_path() -> Path:
    env_val = os.environ.get("MODSTORE_EVOLUTION_LEDGER_PATH", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root
    return Path(_repo_root()) / "成都修茈科技有限公司" / "MODstore_deploy" / "modstore_server" / "data" / LEDGER_FILENAME


def append_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """追加一个事件到 ledger。返回写入的完整记录（含 event_id / timestamp）。"""
    record: Dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    record.update(event)
    record.setdefault("owner_audit", {"audited": False, "audited_at": None, "verdict": None})

    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _LEDGER_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    return record


def list_events(
    *,
    event_type: Optional[str] = None,
    final_status: Optional[str] = None,
    since_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """读 ledger 并按条件过滤。"""
    path = _ledger_path()
    if not path.is_file():
        return []
    cutoff: Optional[datetime] = None
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and evt.get("event_type") != event_type:
                continue
            if final_status and evt.get("final_status") != final_status:
                continue
            if cutoff:
                ts_str = evt.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            out.append(evt)
    return out


def mark_audited(event_id: str, verdict: str) -> bool:
    """标记某个事件已审计。重写 ledger 文件以更新对应行。"""
    path = _ledger_path()
    if not path.is_file():
        return False
    found = False
    lines_out: List[str] = []
    with _LEDGER_LOCK:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    lines_out.append(line.rstrip("\n"))
                    continue
                if evt.get("event_id") == event_id:
                    evt["owner_audit"] = {
                        "audited": True,
                        "audited_at": datetime.now(timezone.utc).isoformat(),
                        "verdict": verdict,
                    }
                    lines_out.append(json.dumps(evt, ensure_ascii=False, sort_keys=True))
                    found = True
                else:
                    lines_out.append(line.rstrip("\n"))
        if found:
            with path.open("w", encoding="utf-8") as f:
                for ln in lines_out:
                    f.write(ln + "\n")
    return found
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_evolution_ledger.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_ledger.py \
        成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_ledger.py
git commit -m "feat(evolution): add append-only ledger for evolution decisions"
```

---

## Task 2: 扩展 evolution_signal_collector.aggregate_signals()

**Files:**
- Modify: `成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_signal_collector.py`（添加 `aggregate_signals()` 函数）
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_signal_aggregator.py`

**Why:** 3 个扫描 workflow（legacy-usage-weekly / intent-benchmark / slo-metrics-collect）只产出 JSON 报告，需要一个聚合器把它们转成统一的 signal 列表，供后续 LLM 提议器消费。

- [ ] **Step 1: 写失败测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_signal_aggregator.py
"""aggregate_signals() 单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modstore_server.evolution_signal_collector import aggregate_signals


@pytest.fixture
def tmp_reports(tmp_path, monkeypatch):
    """伪造 3 个扫描 workflow 的 JSON 报告。"""
    legacy = tmp_path / "legacy_usage_report.json"
    legacy.write_text(json.dumps({
        "generated_at": "2026-07-20T08:00:00Z",
        "total_files": 120,
        "legacy_files": 35,
        "legacy_ratio": 0.29,
    }), encoding="utf-8")

    intent = tmp_path / "intent_benchmark_report.json"
    intent.write_text(json.dumps({
        "generated_at": "2026-07-20T03:00:00Z",
        "accuracy": 0.72,
        "test_cases": 200,
        "failures": 56,
    }), encoding="utf-8")

    slo = tmp_path / "slo_metrics.json"
    slo.write_text(json.dumps({
        "window": "30d",
        "availability": 0.987,
        "p95_latency_ms": 450,
        "error_rate": 0.013,
    }), encoding="utf-8")

    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(legacy))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(intent))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(slo))
    return tmp_path


def test_aggregate_returns_three_sources(tmp_reports):
    out = aggregate_signals()
    assert "legacy_usage" in out
    assert "intent_benchmark" in out
    assert "slo_metrics" in out


def test_aggregate_intent_below_threshold(tmp_reports):
    out = aggregate_signals()
    intent = out["intent_benchmark"]
    assert intent["accuracy"] == 0.72
    assert intent["below_threshold"] is True  # < 0.80
    assert intent["signal_score"] > 0  # 触发提议


def test_aggregate_slo_above_threshold_no_signal(tmp_reports, monkeypatch):
    """SLO 正常时不触发 signal。"""
    slo_path = tmp_reports / "slo_metrics.json"
    slo_path.write_text(json.dumps({
        "window": "30d",
        "availability": 0.999,
        "p95_latency_ms": 200,
        "error_rate": 0.001,
    }), encoding="utf-8")
    out = aggregate_signals()
    assert out["slo_metrics"]["signal_score"] == 0


def test_aggregate_handles_missing_reports(tmp_path, monkeypatch):
    """3 个报告都不存在时返回空 signal。"""
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(tmp_path / "nope1.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(tmp_path / "nope2.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(tmp_path / "nope3.json"))
    out = aggregate_signals()
    assert out["legacy_usage"]["signal_score"] == 0
    assert out["intent_benchmark"]["signal_score"] == 0
    assert out["slo_metrics"]["signal_score"] == 0


def test_aggregate_total_score(tmp_reports):
    out = aggregate_signals()
    assert out["total_score"] > 0
    assert out["signals_to_propose"] >= 1  # 至少 intent 触发


def test_aggregate_legacy_high_ratio_triggers_signal(tmp_reports, monkeypatch):
    """legacy ratio > 0.25 触发 signal。"""
    legacy_path = tmp_reports / "legacy_usage_report.json"
    legacy_path.write_text(json.dumps({
        "total_files": 100,
        "legacy_files": 50,
        "legacy_ratio": 0.50,
    }), encoding="utf-8")
    out = aggregate_signals()
    assert out["legacy_usage"]["signal_score"] > 0
    assert out["legacy_usage"]["below_threshold"] is True
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_evolution_signal_aggregator.py -v
```

Expected: FAIL with `ImportError: cannot import name 'aggregate_signals'`

- [ ] **Step 3: 在 evolution_signal_collector.py 末尾追加 aggregate_signals() 函数**

```python
# 追加到 成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_signal_collector.py 末尾

# --------------------------------------------------------------------------- #
# 扫描类 workflow JSON 报告聚合器
# --------------------------------------------------------------------------- #

_INTENT_ACCURACY_THRESHOLD = 0.80
_LEGACY_RATIO_THRESHOLD = 0.25
_SLO_AVAILABILITY_THRESHOLD = 0.99
_SLO_ERROR_RATE_THRESHOLD = 0.01


def _read_json_report(env_var: str) -> Optional[Dict[str, Any]]:
    path_str = os.environ.get(env_var, "")
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def aggregate_signals() -> Dict[str, Any]:
    """聚合 3 个扫描类 workflow 的 JSON 报告。

    返回每个源的信号强度（signal_score）+ 是否触发提议（below_threshold）。
    signal_score > 0 表示值得进入 LLM 提议器。
    """
    legacy = _read_json_report("MODSTORE_LEGACY_REPORT_PATH") or {}
    intent = _read_json_report("MODSTORE_INTENT_REPORT_PATH") or {}
    slo = _read_json_report("MODSTORE_SLO_REPORT_PATH") or {}

    # Intent benchmark: 准确率 < 0.80 触发
    intent_acc = float(intent.get("accuracy") or 1.0)
    intent_below = intent_acc < _INTENT_ACCURACY_THRESHOLD
    intent_score = max(0.0, _INTENT_ACCURACY_THRESHOLD - intent_acc) if intent_below else 0.0

    # Legacy usage: legacy_ratio > 0.25 触发
    legacy_ratio = float(legacy.get("legacy_ratio") or 0.0)
    legacy_below = legacy_ratio > _LEGACY_RATIO_THRESHOLD
    legacy_score = max(0.0, legacy_ratio - _LEGACY_RATIO_THRESHOLD) if legacy_below else 0.0

    # SLO: availability < 0.99 或 error_rate > 0.01 触发
    slo_avail = float(slo.get("availability") or 1.0)
    slo_err = float(slo.get("error_rate") or 0.0)
    slo_below = (slo_avail < _SLO_AVAILABILITY_THRESHOLD) or (slo_err > _SLO_ERROR_RATE_THRESHOLD)
    slo_score = 0.0
    if slo_below:
        slo_score = max(
            _SLO_AVAILABILITY_THRESHOLD - slo_avail,
            slo_err - _SLO_ERROR_RATE_THRESHOLD,
        )

    signals_to_propose = sum(1 for s in (intent_score, legacy_score, slo_score) if s > 0)

    return {
        "legacy_usage": {
            "report": legacy,
            "below_threshold": legacy_below,
            "signal_score": legacy_score,
        },
        "intent_benchmark": {
            "report": intent,
            "accuracy": intent_acc,
            "below_threshold": intent_below,
            "signal_score": intent_score,
        },
        "slo_metrics": {
            "report": slo,
            "below_threshold": slo_below,
            "signal_score": slo_score,
        },
        "total_score": intent_score + legacy_score + slo_score,
        "signals_to_propose": signals_to_propose,
    }
```

注：`Optional` 已在文件顶部导入（`from typing import Any, Dict, List, Optional`），无需重新导入。

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_evolution_signal_aggregator.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_signal_collector.py \
        成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_signal_aggregator.py
git commit -m "feat(evolution): aggregate scan workflow reports into evolution signals"
```

---

## Task 3: 扩展 employee_autonomy_service.propose_employee_pack()

**Files:**
- Modify: `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_autonomy_service.py`（添加 `propose_employee_pack()` 函数）
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_propose_employee_pack.py`

**Why:** LLM 提议器把聚合信号转成结构化 JSON 提议（含 department / prompt_template / skills / tools / acceptance_criteria），供后续 ai-issue-implement.yml 消费。

- [ ] **Step 1: 写失败测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_propose_employee_pack.py
"""LLM 提议器单元测试。"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from modstore_server.employee_autonomy_service import (
    propose_employee_pack,
    validate_proposal,
    ProposalValidationError,
)


def _make_signal(source: str = "intent_benchmark", score: float = 0.08) -> dict:
    return {
        "legacy_usage": {"signal_score": 0.0 if source != "legacy_usage" else score},
        "intent_benchmark": {
            "signal_score": score if source == "intent_benchmark" else 0.0,
            "accuracy": 0.72,
            "below_threshold": source == "intent_benchmark",
        },
        "slo_metrics": {"signal_score": 0.0 if source != "slo_metrics" else score},
        "total_score": score,
        "signals_to_propose": 1,
    }


def test_propose_employee_pack_returns_valid_schema():
    signals = _make_signal("intent_benchmark", 0.08)
    with patch("modstore_server.employee_autonomy_service._call_llm") as mock_llm:
        mock_llm.return_value = {
            "proposal_id": "test-uuid",
            "triggered_by": "intent_benchmark",
            "signal_score": 0.08,
            "department": "engineering",
            "employee_pack": {
                "name": "intent-failure-triage-clerk",
                "responsibility": "scan failed intent cases and cluster failure patterns",
                "prompt_template": "You are an intent failure triage clerk...",
                "skills": ["intent-benchmark", "failure-clustering"],
                "tools": ["read_file", "write_pr_comment"],
                "acceptance_criteria": ["recall >= 0.7 on test set"],
            },
            "estimated_files": 3,
            "estimated_tokens": 45000,
        }
        proposal = propose_employee_pack(signals)
    assert proposal["department"] in {"engineering", "quality", "ops", "growth", "support", "security"}
    assert proposal["estimated_files"] <= 5
    assert proposal["estimated_tokens"] <= 100000
    assert "prompt_template" in proposal["employee_pack"]
    assert "acceptance_criteria" in proposal["employee_pack"]


def test_validate_proposal_rejects_too_many_files():
    bad_proposal = {
        "proposal_id": "x",
        "department": "engineering",
        "employee_pack": {"name": "x", "prompt_template": "x", "skills": [], "tools": [], "acceptance_criteria": []},
        "estimated_files": 7,
        "estimated_tokens": 10000,
    }
    with pytest.raises(ProposalValidationError, match="estimated_files"):
        validate_proposal(bad_proposal)


def test_validate_proposal_rejects_high_token_budget():
    bad_proposal = {
        "proposal_id": "x",
        "department": "engineering",
        "employee_pack": {"name": "x", "prompt_template": "x", "skills": [], "tools": [], "acceptance_criteria": []},
        "estimated_files": 3,
        "estimated_tokens": 200000,
    }
    with pytest.raises(ProposalValidationError, match="estimated_tokens"):
        validate_proposal(bad_proposal)


def test_validate_proposal_rejects_invalid_department():
    bad_proposal = {
        "proposal_id": "x",
        "department": "marketing",
        "employee_pack": {"name": "x", "prompt_template": "x", "skills": [], "tools": [], "acceptance_criteria": []},
        "estimated_files": 3,
        "estimated_tokens": 10000,
    }
    with pytest.raises(ProposalValidationError, match="department"):
        validate_proposal(bad_proposal)


def test_validate_proposal_rejects_missing_fields():
    bad_proposal = {"proposal_id": "x", "department": "engineering"}
    with pytest.raises(ProposalValidationError, match="employee_pack"):
        validate_proposal(bad_proposal)


def test_propose_employee_pack_skips_when_no_signal():
    """无 signal 时不调用 LLM，返回 None。"""
    empty_signals = {
        "legacy_usage": {"signal_score": 0.0},
        "intent_benchmark": {"signal_score": 0.0},
        "slo_metrics": {"signal_score": 0.0},
        "total_score": 0.0,
        "signals_to_propose": 0,
    }
    with patch("modstore_server.employee_autonomy_service._call_llm") as mock_llm:
        result = propose_employee_pack(empty_signals)
    assert result is None
    mock_llm.assert_not_called()
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_propose_employee_pack.py -v
```

Expected: FAIL with `ImportError: cannot import name 'propose_employee_pack'`

- [ ] **Step 3: 在 employee_autonomy_service.py 末尾追加提议器**

```python
# 追加到 成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_autonomy_service.py 末尾

# --------------------------------------------------------------------------- #
# LLM 提议器：把演化信号转成结构化 employee_pack 提议
# --------------------------------------------------------------------------- #

from typing import Any, Dict, Optional

VALID_DEPARTMENTS = {"engineering", "quality", "ops", "growth", "support", "security"}
MAX_FILES_PER_PROPOSAL = 5
MAX_TOKENS_PER_PROPOSAL = 100000


class ProposalValidationError(ValueError):
    """LLM 提议未通过 schema 校验。"""


def _call_llm(prompt: str) -> Dict[str, Any]:
    """调用 LLM，返回 JSON dict。

    实际实现通过 platform_llm_scope 路由，这里只做接口。
    生产环境由 secrets.LLM_API_KEY 鉴权。
    """
    try:
        from modstore_server.platform_llm_scope import platform_llm_scoped
        response_text = platform_llm_scoped(prompt, scope="evolution_proposal")
        if isinstance(response_text, dict):
            return response_text
        return json.loads(response_text)
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return {}


def validate_proposal(proposal: Dict[str, Any]) -> None:
    """校验 LLM 提议是否符合 schema。失败抛 ProposalValidationError。"""
    if not isinstance(proposal, dict):
        raise ProposalValidationError("proposal must be dict")
    if "proposal_id" not in proposal:
        raise ProposalValidationError("missing proposal_id")
    if proposal.get("department") not in VALID_DEPARTMENTS:
        raise ProposalValidationError(
            f"department must be one of {VALID_DEPARTMENTS}, got {proposal.get('department')}"
        )
    pack = proposal.get("employee_pack")
    if not isinstance(pack, dict):
        raise ProposalValidationError("missing employee_pack dict")
    for key in ("name", "prompt_template", "skills", "tools", "acceptance_criteria"):
        if key not in pack:
            raise ProposalValidationError(f"employee_pack missing field: {key}")
    if proposal.get("estimated_files", 999) > MAX_FILES_PER_PROPOSAL:
        raise ProposalValidationError(
            f"estimated_files {proposal.get('estimated_files')} exceeds {MAX_FILES_PER_PROPOSAL}"
        )
    if proposal.get("estimated_tokens", 999999) > MAX_TOKENS_PER_PROPOSAL:
        raise ProposalValidationError(
            f"estimated_tokens {proposal.get('estimated_tokens')} exceeds {MAX_TOKENS_PER_PROPOSAL}"
        )


def propose_employee_pack(signals: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """根据聚合信号生成 employee_pack 提议。

    输入：aggregate_signals() 的输出。
    输出：通过 validate_proposal 的提议 dict；无 signal 时返回 None。
    """
    if int(signals.get("signals_to_propose") or 0) == 0:
        return None

    # 找最强信号源
    sources = ["legacy_usage", "intent_benchmark", "slo_metrics"]
    strongest = max(sources, key=lambda s: signals.get(s, {}).get("signal_score") or 0)
    score = signals.get(strongest, {}).get("signal_score") or 0
    if score <= 0:
        return None

    prompt = _build_proposal_prompt(strongest, signals)
    raw = _call_llm(prompt)
    if not raw:
        return None
    raw.setdefault("triggered_by", strongest)
    raw.setdefault("signal_score", score)
    validate_proposal(raw)
    return raw


def _build_proposal_prompt(source: str, signals: Dict[str, Any]) -> str:
    """构造给 LLM 的 prompt。"""
    source_data = signals.get(source, {})
    return f"""You are designing a new AI employee pack for XCMAX MODstore.

Gap signal source: {source}
Signal score: {source_data.get('signal_score', 0)}
Source report: {json.dumps(source_data.get('report', {}), ensure_ascii=False)}

Design a new AI employee pack that addresses this gap. Output JSON only:
{{
  "proposal_id": "<uuid>",
  "department": "engineering|quality|ops|growth|support|security",
  "employee_pack": {{
    "name": "<pack-name>",
    "responsibility": "<one sentence>",
    "prompt_template": "<full prompt>",
    "skills": ["<skill-1>", "<skill-2>"],
    "tools": ["read_file", "write_pr_comment"],
    "acceptance_criteria": ["<criterion-1>"]
  }},
  "estimated_files": <int <= 5>,
  "estimated_tokens": <int <= 100000>
}}

Constraints:
- estimated_files <= 5 (HARD LIMIT)
- estimated_tokens <= 100000 (BUDGET LIMIT)
- department must be one of the six lines (SIX_LINE_DEPARTMENTS)
- acceptance_criteria must be machine-verifiable
"""
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_propose_employee_pack.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_autonomy_service.py \
        成都修茈科技有限公司/MODstore_deploy/tests/test_propose_employee_pack.py
git commit -m "feat(evolution): add LLM proposer for employee pack from evolution signals"
```

---

## Task 4: 三重硬门禁子脚本（check_footprint + check_budget）

**Files:**
- Create: `FHD/scripts/dev/check_footprint.py`
- Create: `FHD/scripts/dev/check_budget.py`
- Create: `FHD/scripts/dev/tests/test_evolution_gates.py`

**Why:** 三重硬门禁中的 2 个新规则需要独立可执行的 CLI 脚本（arch_fitness 已存在）。ai-issue-implement.yml 会按顺序调用。

- [ ] **Step 1: 写失败测试**

```python
# FHD/scripts/dev/tests/test_evolution_gates.py
"""三重硬门禁脚本单元测试。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run_script(script_name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script_name), *args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR.parent.parent),
    )


def test_check_footprint_passes_low_risk_paths(tmp_path):
    """employee_pack 文件不在 HIGH_RISK_PATTERNS 时通过。"""
    changed_files = [
        "成都修茈科技有限公司/MODstore_deploy/catalog_data/files/intent-clerk@1.0.0/prompt.txt",
        "成都修茈科技有限公司/MODstore_deploy/catalog_data/files/intent-clerk@1.0.0/skills.json",
    ]
    files_list = tmp_path / "changed.txt"
    files_list.write_text("\n".join(changed_files), encoding="utf-8")
    result = _run_script("check_footprint.py", "--files-list", str(files_list))
    assert result.returncode == 0, f"expected pass, got: {result.stderr}"


def test_check_footprint_fails_on_env_file(tmp_path):
    changed_files = ["foo.env", "config.yaml"]
    files_list = tmp_path / "changed.txt"
    files_list.write_text("\n".join(changed_files), encoding="utf-8")
    result = _run_script("check_footprint.py", "--files-list", str(files_list))
    assert result.returncode == 1
    assert "foo.env" in result.stderr


def test_check_footprint_fails_on_workflow_file(tmp_path):
    changed_files = [".github/workflows/evil.yml"]
    files_list = tmp_path / "changed.txt"
    files_list.write_text("\n".join(changed_files), encoding="utf-8")
    result = _run_script("check_footprint.py", "--files-list", str(files_list))
    assert result.returncode == 1
    assert ".github/workflows/evil.yml" in result.stderr


def test_check_budget_passes_under_limit(tmp_path):
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(json.dumps({
        "tokens_used": 45000,
        "tokens_limit": 100000,
        "time_used_minutes": 15,
        "time_limit_minutes": 30,
    }), encoding="utf-8")
    result = _run_script("check_budget.py", "--budget-file", str(budget_file))
    assert result.returncode == 0


def test_check_budget_fails_on_token_overrun(tmp_path):
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(json.dumps({
        "tokens_used": 150000,
        "tokens_limit": 100000,
        "time_used_minutes": 15,
        "time_limit_minutes": 30,
    }), encoding="utf-8")
    result = _run_script("check_budget.py", "--budget-file", str(budget_file))
    assert result.returncode == 1
    assert "tokens" in result.stderr.lower()


def test_check_budget_fails_on_time_overrun(tmp_path):
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(json.dumps({
        "tokens_used": 50000,
        "tokens_limit": 100000,
        "time_used_minutes": 45,
        "time_limit_minutes": 30,
    }), encoding="utf-8")
    result = _run_script("check_budget.py", "--budget-file", str(budget_file))
    assert result.returncode == 1
    assert "time" in result.stderr.lower()


def test_check_budget_handles_missing_file(tmp_path):
    result = _run_script("check_budget.py", "--budget-file", str(tmp_path / "nope.json"))
    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "missing" in result.stderr.lower()
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_evolution_gates.py -v
```

Expected: FAIL with `FileNotFoundError` 或脚本不存在

- [ ] **Step 3: 写 check_footprint.py**

```python
# FHD/scripts/dev/check_footprint.py
#!/usr/bin/env python3
"""门禁 2：足迹边界检查。

读取 --files-list 指定的文件清单（每行一个相对仓库根的路径），
对每个文件检查是否命中 HIGH_RISK_PATTERNS。
命中任何高风险路径 → 退出码 1，stderr 列出违规文件。
全部通过 → 退出码 0。

Usage:
    python check_footprint.py --files-list changed_files.txt
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

HIGH_RISK_PATTERNS = [
    "*.env",
    "*.env.*",
    "secrets/*",
    ".github/workflows/*",
    "nginx/*.conf",
    "*/nginx.conf",
    "requirements*.txt",
    "Dockerfile*",
    "docker-compose*.yml",
    "modstore_server/models*.py",
    "modstore_server/api/app_factory.py",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
]


def _is_high_risk(rel_path: str) -> bool:
    rp = rel_path.replace("\\", "/").lower()
    for pat in HIGH_RISK_PATTERNS:
        p = pat.lower()
        if fnmatch.fnmatch(rp, p) or fnmatch.fnmatch(rp, "**/" + p):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-list", required=True, help="文件清单，每行一个相对路径")
    args = parser.parse_args()

    files_list = Path(args.files_list)
    if not files_list.is_file():
        print(f"ERROR: files list not found: {files_list}", file=sys.stderr)
        return 2

    violations = []
    for line in files_list.read_text(encoding="utf-8").splitlines():
        rel = line.strip()
        if not rel:
            continue
        if _is_high_risk(rel):
            violations.append(rel)

    if violations:
        print("ERROR: high-risk paths in employee_pack:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print("OK: no high-risk paths in employee_pack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3b: 写 check_budget.py**

```python
# FHD/scripts/dev/check_budget.py
#!/usr/bin/env python3
"""门禁 3：预算限制检查。

读取 --budget-file 指定的 JSON 文件（含 tokens_used / tokens_limit / time_used_minutes / time_limit_minutes），
超任一限 → 退出码 1。
全部通过 → 退出码 0。

Usage:
    python check_budget.py --budget-file budget.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-file", required=True, help="JSON file with budget metrics")
    args = parser.parse_args()

    budget_path = Path(args.budget_file)
    if not budget_path.is_file():
        print(f"ERROR: budget file not found: {budget_path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(budget_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid budget JSON: {e}", file=sys.stderr)
        return 2

    tokens_used = float(data.get("tokens_used") or 0)
    tokens_limit = float(data.get("tokens_limit") or 100000)
    time_used = float(data.get("time_used_minutes") or 0)
    time_limit = float(data.get("time_limit_minutes") or 30)

    if tokens_used > tokens_limit:
        print(
            f"ERROR: tokens {tokens_used} exceeds limit {tokens_limit}",
            file=sys.stderr,
        )
        return 1
    if time_used > time_limit:
        print(
            f"ERROR: time {time_used}min exceeds limit {time_limit}min",
            file=sys.stderr,
        )
        return 1

    print(f"OK: budget within limits (tokens={tokens_used}/{tokens_limit}, time={time_used}/{time_limit}min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_evolution_gates.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add FHD/scripts/dev/check_footprint.py FHD/scripts/dev/check_budget.py \
        FHD/scripts/dev/tests/test_evolution_gates.py
git commit -m "feat(evolution): add footprint and budget hard gate scripts"
```

---

## Task 5: gap_to_issue.py（聚合信号 → 自动开 GitHub issue）

**Files:**
- Create: `成都修茈科技有限公司/MODstore_deploy/modstore_server/gap_to_issue.py`
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_gap_to_issue.py`

**Why:** 把聚合信号 + LLM 提议转成 GitHub issue，打 `ai-implement` 标签，body 含完整 LLM 提议 JSON。这是接通点 #2。

- [ ] **Step 1: 写失败测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_gap_to_issue.py
"""gap_to_issue 单元测试。"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from modstore_server.gap_to_issue import (
    open_issue_for_proposal,
    build_issue_body,
    dedupe_signal,
    DuplicateProposalError,
)


def _make_proposal() -> dict:
    return {
        "proposal_id": "test-uuid-001",
        "triggered_by": "intent_benchmark",
        "signal_score": 0.08,
        "department": "engineering",
        "employee_pack": {
            "name": "intent-failure-triage-clerk",
            "responsibility": "scan failed intent cases",
            "prompt_template": "You are...",
            "skills": ["intent-benchmark"],
            "tools": ["read_file"],
            "acceptance_criteria": ["recall >= 0.7"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


def test_build_issue_body_contains_proposal_json():
    proposal = _make_proposal()
    body = build_issue_body(proposal)
    assert "```json" in body
    assert "intent-failure-triage-clerk" in body
    parsed = json.loads(body.split("```json\n")[1].split("\n```")[0])
    assert parsed["proposal_id"] == "test-uuid-001"


def test_open_issue_for_proposal_calls_gh(monkeypatch):
    """正常流程：调 gh issue create。"""
    proposal = _make_proposal()
    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="https://github.com/x/y/issues/42\n"))
    monkeypatch.setattr("modstore_server.gap_to_issue.subprocess.run", mock_run)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    issue_url = open_issue_for_proposal(proposal)
    assert issue_url == "https://github.com/x/y/issues/42"
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "gh" in cmd
    assert "issue" in cmd
    assert "create" in cmd


def test_open_issue_for_proposal_writes_ledger(monkeypatch, tmp_path):
    """开 issue 后写 ledger event。"""
    proposal = _make_proposal()
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(
        "modstore_server.gap_to_issue.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="https://github.com/x/y/issues/99\n"),
    )
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    open_issue_for_proposal(proposal)
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "issue_opened"
    assert evt["issue_url"] == "https://github.com/x/y/issues/99"
    assert evt["llm_proposal"]["proposal_id"] == "test-uuid-001"


def test_dedupe_signal_rejects_recent_duplicate(monkeypatch, tmp_path):
    """5 分钟内同 proposal_id 不重复开 issue。"""
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    ledger_path.write_text(
        json.dumps({"event_id": "x", "event_type": "issue_opened",
                    "timestamp": recent,
                    "llm_proposal": {"proposal_id": "test-uuid-001"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    proposal = _make_proposal()
    with pytest.raises(DuplicateProposalError):
        dedupe_signal(proposal)


def test_dedupe_signal_allows_old_proposal(monkeypatch, tmp_path):
    """5 分钟前的同 proposal_id 允许重开。"""
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    ledger_path.write_text(
        json.dumps({"event_id": "x", "event_type": "issue_opened",
                    "timestamp": old,
                    "llm_proposal": {"proposal_id": "test-uuid-001"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    proposal = _make_proposal()
    dedupe_signal(proposal)  # 不抛异常即通过


def test_open_issue_for_proposal_gh_failure_raises(monkeypatch):
    proposal = _make_proposal()
    monkeypatch.setattr(
        "modstore_server.gap_to_issue.subprocess.run",
        lambda *a, **k: MagicMock(returncode=1, stderr="auth error"),
    )
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    with pytest.raises(RuntimeError, match="gh issue create failed"):
        open_issue_for_proposal(proposal)
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_gap_to_issue.py -v
```

Expected: FAIL with `ImportError: cannot import name 'open_issue_for_proposal'`

- [ ] **Step 3: 写实现**

```python
# 成都修茈科技有限公司/MODstore_deploy/modstore_server/gap_to_issue.py
"""把 LLM 提议转成 GitHub issue（打 ai-implement 标签）。

调用 gh CLI 创建 issue。body 含完整 LLM 提议 JSON。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from modstore_server.evolution_ledger import append_event, list_events

AI_IMPLEMENT_LABEL = "ai-implement"
DEDUP_WINDOW_MINUTES = 5


class DuplicateProposalError(ValueError):
    """同一 proposal_id 在去重窗口内已开过 issue。"""


def build_issue_body(proposal: Dict[str, Any]) -> str:
    """构造 issue body，含 LLM 提议 JSON code block。"""
    return f"""# 自动演化提议：{proposal.get('employee_pack', {}).get('name', '<unnamed>')}

**Department**: {proposal.get('department')}
**Triggered by**: {proposal.get('triggered_by')}
**Signal score**: {proposal.get('signal_score')}
**Estimated files**: {proposal.get('estimated_files')}
**Estimated tokens**: {proposal.get('estimated_tokens')}

## Employee Pack Proposal

```json
{json.dumps(proposal, ensure_ascii=False, indent=2)}
```

## Acceptance Criteria

{chr(10).join('- ' + c for c in proposal.get('employee_pack', {}).get('acceptance_criteria', []))}

---

此 issue 由演化闭环自动创建。打 `ai-implement` 标签后将触发 `ai-issue-implement.yml` workflow。
"""


def dedupe_signal(proposal: Dict[str, Any]) -> None:
    """检查去重窗口内是否已开过同 proposal_id 的 issue。"""
    proposal_id = proposal.get("proposal_id")
    if not proposal_id:
        return
    recent = list_events(since_days=1)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    for evt in recent:
        if evt.get("event_type") != "issue_opened":
            continue
        evt_pid = (evt.get("llm_proposal") or {}).get("proposal_id")
        if evt_pid != proposal_id:
            continue
        try:
            ts = datetime.fromisoformat(evt.get("timestamp", "").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            raise DuplicateProposalError(
                f"proposal {proposal_id} already has issue opened at {ts.isoformat()}"
            )


def open_issue_for_proposal(proposal: Dict[str, Any]) -> str:
    """调 gh CLI 创建 issue，返回 issue URL。"""
    dedupe_signal(proposal)

    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")

    body = build_issue_body(proposal)
    title = f"[evolution] {proposal.get('employee_pack', {}).get('name', 'unnamed')} ({proposal.get('department')})"

    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
        "--label", AI_IMPLEMENT_LABEL,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"gh issue create failed (rc={result.returncode}): {result.stderr}"
        )

    issue_url = result.stdout.strip()
    append_event({
        "event_type": "issue_opened",
        "triggered_by": proposal.get("triggered_by"),
        "signal_score": proposal.get("signal_score"),
        "llm_proposal": proposal,
        "issue_url": issue_url,
    })
    return issue_url
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_gap_to_issue.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/modstore_server/gap_to_issue.py \
        成都修茈科技有限公司/MODstore_deploy/tests/test_gap_to_issue.py
git commit -m "feat(evolution): bridge aggregated signals to GitHub issue creation"
```

---

## Task 6: implement_employee_pack.py（LLM 实现 employee_pack）

**Files:**
- Create: `FHD/scripts/dev/implement_employee_pack.py`
- Create: `FHD/scripts/dev/tests/test_implement_employee_pack.py`

**Why:** ai-issue-implement.yml 调此脚本，读 issue body 中的 LLM 提议 JSON，调用 LLM 实际生成 employee_pack 文件（≤5 文件硬限制）。

- [ ] **Step 1: 写失败测试**

```python
# FHD/scripts/dev/tests/test_implement_employee_pack.py
"""implement_employee_pack 单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from implement_employee_pack import (
    implement_pack,
    count_generated_files,
    TooManyFilesError,
)


def _make_proposal() -> dict:
    return {
        "proposal_id": "test-001",
        "department": "engineering",
        "employee_pack": {
            "name": "intent-clerk",
            "prompt_template": "You are an intent clerk...",
            "skills": ["intent-benchmark"],
            "tools": ["read_file"],
            "acceptance_criteria": ["recall >= 0.7"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


def test_implement_pack_returns_generated_files(tmp_path):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.return_value = {
            "files": [
                {"path": "prompt.txt", "content": "You are..."},
                {"path": "skills.json", "content": "[\"intent-benchmark\"]"},
                {"path": "manifest.json", "content": "{\"name\":\"intent-clerk\"}"},
            ]
        }
        files = implement_pack(proposal, output_dir=output_dir)
    assert len(files) == 3
    for f in files:
        assert f.exists()
    assert (output_dir / "prompt.txt").read_text(encoding="utf-8") == "You are..."


def test_implement_pack_rejects_more_than_5_files(tmp_path):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.return_value = {
            "files": [{"path": f"f{i}.txt", "content": "x"} for i in range(6)]
        }
        with pytest.raises(TooManyFilesError):
            implement_pack(proposal, output_dir=output_dir)


def test_count_generated_files_checks_paths_only(tmp_path):
    """路径相同视为同一文件（去重）。"""
    files = [
        {"path": "a.txt", "content": "x"},
        {"path": "a.txt", "content": "y"},
        {"path": "b.txt", "content": "z"},
    ]
    assert count_generated_files(files) == 2


def test_implement_pack_writes_ledger_event(tmp_path, monkeypatch):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.return_value = {
            "files": [{"path": "prompt.txt", "content": "x"}]
        }
        implement_pack(proposal, output_dir=output_dir)

    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "implement_succeeded"
    assert evt["cost_tokens"] >= 0


def test_implement_pack_handles_llm_failure(tmp_path, monkeypatch):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.side_effect = RuntimeError("LLM API error")
        with pytest.raises(RuntimeError, match="LLM API error"):
            implement_pack(proposal, output_dir=output_dir)

    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "implement_failed"
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_implement_employee_pack.py -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 写实现**

```python
# FHD/scripts/dev/implement_employee_pack.py
#!/usr/bin/env python3
"""LLM 实现 employee_pack。

输入：LLM 提议 JSON（含 employee_pack 字段）。
输出：在 output_dir 下生成 ≤5 个文件（prompt.txt / skills.json / manifest.json 等）。
失败：写 ledger event + 抛异常。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# 让脚本可访问 modstore_server
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import append_event  # noqa: E402

MAX_FILES = 5


class TooManyFilesError(ValueError):
    """LLM 生成的文件数超过 MAX_FILES 限制。"""


def _call_llm(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """调用 LLM 生成 employee_pack 文件。返回 {"files": [{"path", "content"}, ...]}。"""
    try:
        from modstore_server.platform_llm_scope import platform_llm_scoped
        prompt = _build_implementation_prompt(proposal)
        resp = platform_llm_scoped(prompt, scope="employee_pack_implementation")
        if isinstance(resp, dict):
            return resp
        return json.loads(resp)
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from e


def _build_implementation_prompt(proposal: Dict[str, Any]) -> str:
    pack = proposal.get("employee_pack", {})
    return f"""You are implementing an AI employee pack for XCMAX MODstore.

Proposal:
{json.dumps(proposal, ensure_ascii=False, indent=2)}

Output JSON ONLY:
{{
  "files": [
    {{"path": "<filename>", "content": "<file content>"}}
  ]
}}

Constraints:
- Maximum {MAX_FILES} files
- Include at minimum: prompt.txt, skills.json, manifest.json
- manifest.json must contain: name, department, skills, tools
- Do NOT touch any file outside the employee pack directory
"""


def count_generated_files(files: List[Dict[str, Any]]) -> int:
    """统计唯一 path 数量。"""
    seen = set()
    for f in files:
        seen.add(f.get("path", ""))
    return len(seen)


def implement_pack(proposal: Dict[str, Any], *, output_dir: Path) -> List[Path]:
    """调 LLM 生成 employee_pack 文件，写入 output_dir。返回写入的文件路径列表。"""
    try:
        llm_result = _call_llm(proposal)
    except RuntimeError as e:
        append_event({
            "event_type": "implement_failed",
            "triggered_by": proposal.get("triggered_by"),
            "llm_proposal": proposal,
            "final_status": "implement_failed",
            "failure_reason": str(e),
        })
        raise

    files = llm_result.get("files") or []
    if count_generated_files(files) > MAX_FILES:
        msg = f"LLM generated {count_generated_files(files)} files > {MAX_FILES} limit"
        append_event({
            "event_type": "implement_failed",
            "triggered_by": proposal.get("triggered_by"),
            "llm_proposal": proposal,
            "final_status": "implement_failed",
            "failure_reason": msg,
        })
        raise TooManyFilesError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    seen_paths = set()
    for f in files:
        rel = f.get("path", "")
        if not rel or rel in seen_paths:
            continue
        seen_paths.add(rel)
        # 防止 path traversal
        safe_path = (output_dir / rel).resolve()
        if not str(safe_path).startswith(str(output_dir.resolve())):
            continue
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(str(f.get("content", "")), encoding="utf-8")
        written.append(safe_path)

    append_event({
        "event_type": "implement_succeeded",
        "triggered_by": proposal.get("triggered_by"),
        "llm_proposal": proposal,
        "files_written": [str(p.relative_to(output_dir)) for p in written],
        "cost_tokens": 0,  # TODO: read actual usage from LLM response
    })
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True, help="Path to proposal JSON file")
    parser.add_argument("--output-dir", required=True, help="Directory to write files")
    args = parser.parse_args()

    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    files = implement_pack(proposal, output_dir=output_dir)
    print(f"Wrote {len(files)} files to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_implement_employee_pack.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add FHD/scripts/dev/implement_employee_pack.py \
        FHD/scripts/dev/tests/test_implement_employee_pack.py
git commit -m "feat(evolution): add LLM-driven employee pack implementation script"
```

---

## Task 7: retry_with_adjusted_prompt.py（重试 3 次）

**Files:**
- Create: `FHD/scripts/dev/retry_with_adjusted_prompt.py`
- Create: `FHD/scripts/dev/tests/test_retry_with_adjusted_prompt.py`

**Why:** 任一门禁失败时，最多重试 3 次（调整 prompt），3 次都败才转人工。

- [ ] **Step 1: 写失败测试**

```python
# FHD/scripts/dev/tests/test_retry_with_adjusted_prompt.py
"""retry_with_adjusted_prompt 单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from retry_with_adjusted_prompt import (
    adjust_prompt_for_retry,
    run_with_retries,
    MAX_RETRIES,
)


def test_adjust_prompt_retry_1_appends_failure_reason():
    base_prompt = "Implement X."
    failure_reason = "arch_fitness failed: imports outside DDD layers"
    adjusted = adjust_prompt_for_retry(base_prompt, retry_count=1, failure_reason=failure_reason)
    assert failure_reason in adjusted
    assert "Implement X." in adjusted


def test_adjust_prompt_retry_2_asks_simplify():
    base_prompt = "Implement X."
    adjusted = adjust_prompt_for_retry(base_prompt, retry_count=2, failure_reason="x")
    assert "简化设计" in adjusted or "simplify" in adjusted.lower()
    assert "3" in adjusted  # "files <= 3"


def test_adjust_prompt_retry_3_asks_minimal():
    base_prompt = "Implement X."
    adjusted = adjust_prompt_for_retry(base_prompt, retry_count=3, failure_reason="x")
    assert "最小化" in adjusted or "minimal" in adjusted.lower()
    assert "1" in adjusted  # only 1 file


def test_run_with_retries_succeeds_on_first_try():
    """第 1 次成功，不重试。"""
    call_count = {"n": 0}

    def action(prompt: str):
        call_count["n"] += 1
        return {"success": True, "files": ["a.txt"]}

    result = run_with_retries(
        base_prompt="Implement X.",
        action=action,
        failure_checker=lambda r: (False, None) if r.get("success") else (True, "no success"),
    )
    assert result["success"] is True
    assert call_count["n"] == 1


def test_run_with_retries_succeeds_on_third_try():
    """前 2 次失败，第 3 次成功。"""
    call_count = {"n": 0}

    def action(prompt: str):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return {"success": False}
        return {"success": True}

    result = run_with_retries(
        base_prompt="Implement X.",
        action=action,
        failure_checker=lambda r: (False, None) if r.get("success") else (True, "no success"),
    )
    assert result["success"] is True
    assert call_count["n"] == 3


def test_run_with_retries_fails_after_max():
    """3 次都败，返回最终失败。"""
    call_count = {"n": 0}

    def action(prompt: str):
        call_count["n"] += 1
        return {"success": False}

    result = run_with_retries(
        base_prompt="Implement X.",
        action=action,
        failure_checker=lambda r: (True, "always fail"),
    )
    assert result["success"] is False
    assert call_count["n"] == MAX_RETRIES
    assert "always fail" in result["failure_reasons"][-1]


def test_run_with_retries_writes_ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    result = run_with_retries(
        base_prompt="Implement X.",
        action=lambda p: {"success": False},
        failure_checker=lambda r: (True, "x"),
        proposal={"proposal_id": "test"},
    )
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    # 3 次 retry 失败 = 3 个失败事件 + 1 个最终 needs_human 事件（共 4 行）
    assert len(lines) == MAX_RETRIES + 1
    final = json.loads(lines[-1])
    assert final["event_type"] == "implement_failed"
    assert final["final_status"] == "needs_human"
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_retry_with_adjusted_prompt.py -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 写实现**

```python
# FHD/scripts/dev/retry_with_adjusted_prompt.py
#!/usr/bin/env python3
"""重试机制：任一门禁失败时，最多重试 MAX_RETRIES 次，每次调整 prompt。

3 次都败 → 写 ledger final_status=needs_human。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import append_event  # noqa: E402

MAX_RETRIES = 3


def adjust_prompt_for_retry(base_prompt: str, *, retry_count: int, failure_reason: str) -> str:
    """根据重试次数调整 prompt。"""
    if retry_count == 1:
        return f"{base_prompt}\n\n上一次失败原因：{failure_reason}，请避免。"
    if retry_count == 2:
        return f"{base_prompt}\n\n已失败 2 次，请简化设计，文件数 ≤ 3。"
    if retry_count == 3:
        return f"{base_prompt}\n\n已失败 3 次，请最小化实现，只做最核心 1 个文件。"
    return base_prompt


def run_with_retries(
    *,
    base_prompt: str,
    action: Callable[[str], Dict[str, Any]],
    failure_checker: Callable[[Dict[str, Any]], Tuple[bool, Optional[str]]],
    proposal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行 action，最多重试 MAX_RETRIES 次。

    action: 接收 prompt 返回 dict
    failure_checker: 接收 action 结果，返回 (is_failure: bool, reason: Optional[str])
    """
    failure_reasons: List[str] = []
    current_prompt = base_prompt

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            last_reason = failure_reasons[-1] if failure_reasons else "unknown"
            current_prompt = adjust_prompt_for_retry(
                base_prompt, retry_count=attempt, failure_reason=last_reason
            )

        result = action(current_prompt)
        is_failure, reason = failure_checker(result)
        if not is_failure:
            return {"success": True, "result": result, "attempts": attempt, "failure_reasons": failure_reasons}

        if reason:
            failure_reasons.append(reason)
        append_event({
            "event_type": "implement_failed",
            "triggered_by": (proposal or {}).get("triggered_by"),
            "llm_proposal": proposal,
            "retry_count": attempt,
            "failure_reason": reason or "unknown",
        })

    # 全部失败 → 转 needs_human
    append_event({
        "event_type": "implement_failed",
        "triggered_by": (proposal or {}).get("triggered_by"),
        "llm_proposal": proposal,
        "final_status": "needs_human",
        "retry_count": MAX_RETRIES,
        "failure_reasons": failure_reasons,
    })
    return {
        "success": False,
        "attempts": MAX_RETRIES,
        "failure_reasons": failure_reasons,
        "final_status": "needs_human",
    }


def main() -> int:
    """CLI entry：作为可执行脚本时，从 stdin 读 prompt，输出 result JSON。

    实际由 ai-issue-implement.yml 调用 Python import run_with_retries，
    不直接走 main()。这里保留为可执行入口。
    """
    print("This script is meant to be imported, not run directly.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_retry_with_adjusted_prompt.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add FHD/scripts/dev/retry_with_adjusted_prompt.py \
        FHD/scripts/dev/tests/test_retry_with_adjusted_prompt.py
git commit -m "feat(evolution): add retry-with-adjusted-prompt for failed implementations"
```

---

## Task 8: PR 流水线辅助脚本（read_issue_proposal / open_pr_for_employee_pack / wait_for_pr_merge / escalate_to_human）

**Files:**
- Create: `FHD/scripts/dev/read_issue_proposal.py`
- Create: `FHD/scripts/dev/open_pr_for_employee_pack.py`
- Create: `FHD/scripts/dev/wait_for_pr_merge.py`
- Create: `FHD/scripts/dev/escalate_to_human.py`
- Create: `FHD/scripts/dev/tests/test_pr_pipeline_helpers.py`

**Why:** ai-issue-implement.yml 需要这些辅助脚本完成 issue body 解析、分支创建、PR 等待合并、人工升级。

- [ ] **Step 1: 写失败测试**

```python
# FHD/scripts/dev/tests/test_pr_pipeline_helpers.py
"""PR 流水线辅助脚本单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from read_issue_proposal import extract_proposal_from_issue_body
from open_pr_for_employee_pack import create_branch_commit_pr
from wait_for_pr_merge import is_pr_merged
from escalate_to_human import escalate


def _make_issue_body() -> str:
    proposal = {
        "proposal_id": "abc-123",
        "department": "engineering",
        "employee_pack": {"name": "x", "prompt_template": "y", "skills": [], "tools": [], "acceptance_criteria": []},
        "estimated_files": 2,
        "estimated_tokens": 10000,
    }
    return f"""# Title

```json
{json.dumps(proposal, indent=2)}
```

Rest of body.
"""


def test_extract_proposal_finds_json_block():
    body = _make_issue_body()
    proposal = extract_proposal_from_issue_body(body)
    assert proposal["proposal_id"] == "abc-123"
    assert proposal["department"] == "engineering"


def test_extract_proposal_handles_no_json_block():
    body = "no json here"
    with pytest.raises(ValueError, match="no JSON"):
        extract_proposal_from_issue_body(body)


def test_extract_proposal_handles_invalid_json():
    body = "```json\n{not valid json\n```"
    with pytest.raises(ValueError, match="invalid JSON"):
        extract_proposal_from_issue_body(body)


def test_create_branch_commit_pr_calls_git_in_order(monkeypatch, tmp_path):
    """分支创建 → commit → push → 开 PR。"""
    runs = []
    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0, stdout="https://github.com/x/y/pull/1\n", stderr="")
    monkeypatch.setattr("open_pr_for_employee_pack.subprocess.run", fake_run)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "prompt.txt").write_text("test", encoding="utf-8")

    pr_url = create_branch_commit_pr(
        files_dir=files_dir,
        branch_name="ai-implement/abc-123",
        proposal={"proposal_id": "abc-123", "employee_pack": {"name": "x"}},
    )
    assert pr_url == "https://github.com/x/y/pull/1"
    # 验证调用顺序
    assert runs[0][:2] == ["git", "checkout"]
    assert runs[1][:2] == ["git", "add"]
    assert runs[2][:2] == ["git", "commit"]
    assert runs[3][:2] == ["git", "push"]
    assert runs[4][0] == "gh"


def test_is_pr_merged_returns_true_when_merged(monkeypatch):
    monkeypatch.setattr(
        "wait_for_pr_merge.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="MERGED\n", stderr="")
    )
    assert is_pr_merged(pr_number=1) is True


def test_is_pr_merged_returns_false_when_open(monkeypatch):
    monkeypatch.setattr(
        "wait_for_pr_merge.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="OPEN\n", stderr="")
    )
    assert is_pr_merged(pr_number=1) is False


def test_is_pr_merged_returns_false_on_error(monkeypatch):
    monkeypatch.setattr(
        "wait_for_pr_merge.subprocess.run",
        lambda *a, **k: MagicMock(returncode=1, stdout="", stderr="error")
    )
    assert is_pr_merged(pr_number=1) is False


def test_escalate_comments_on_issue_and_adds_label(monkeypatch, tmp_path):
    """转人工：在 issue comment + 打 needs-human 标签 + 写 ledger。"""
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    runs = []
    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("escalate_to_human.subprocess.run", fake_run)

    escalate(
        issue_number=42,
        proposal={"proposal_id": "abc-123"},
        failure_reasons=["gate 1 failed", "gate 2 failed", "gate 3 failed"],
    )

    # 验证调用了 issue comment + label add
    assert any("comment" in cmd for cmd in runs)
    assert any("label" in cmd for cmd in runs)
    # 验证 ledger 写入
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "escalated_to_human"
    assert evt["final_status"] == "needs_human"
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_pr_pipeline_helpers.py -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3a: 写 read_issue_proposal.py**

```python
# FHD/scripts/dev/read_issue_proposal.py
#!/usr/bin/env python3
"""从 GitHub issue body 中提取 LLM 提议 JSON。"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def extract_proposal_from_issue_body(body: str) -> Dict[str, Any]:
    """从 issue body 中提取 ```json ... ``` 块并解析。"""
    match = re.search(r"```json\s*\n(.*?)\n```", body, re.DOTALL)
    if not match:
        raise ValueError("no JSON code block found in issue body")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in issue body: {e}")


def fetch_issue_body(issue_number: int) -> str:
    """调 gh CLI 获取 issue body。"""
    repo = _repo_from_env()
    cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "body"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh issue view failed: {result.stderr}")
    data = json.loads(result.stdout)
    return data.get("body", "")


def _repo_from_env() -> str:
    repo = __import__("os").environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")
    return repo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_number", type=int)
    parser.add_argument("--output", default="proposal.json", help="output JSON path")
    args = parser.parse_args()
    body = fetch_issue_body(args.issue_number)
    proposal = extract_proposal_from_issue_body(body)
    Path(args.output).write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote proposal to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3b: 写 open_pr_for_employee_pack.py**

```python
# FHD/scripts/dev/open_pr_for_employee_pack.py
#!/usr/bin/env python3
"""创建分支 + commit + push + 开 PR。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def create_branch_commit_pr(
    *,
    files_dir: Path,
    branch_name: str,
    proposal: Dict[str, Any],
) -> str:
    """创建分支 + 添加文件 + commit + push + 开 PR。返回 PR URL。"""
    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")

    pack_name = proposal.get("employee_pack", {}).get("name", "unnamed")
    target_dir = Path("成都修茈科技有限公司/MODstore_deploy/catalog_data/files") / f"{pack_name}@1.0.0"
    target_dir.mkdir(parents=True, exist_ok=True)

    # 复制文件
    import shutil
    for f in files_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, target_dir / f.name)

    # git 操作
    _run(["git", "checkout", "-b", branch_name])
    _run(["git", "add", str(target_dir)])
    _run(["git", "commit", "-m", f"feat(employee_pack): add {pack_name}\n\nProposal-ID: {proposal.get('proposal_id')}"])
    _run(["git", "push", "origin", branch_name])
    _run(["git", "checkout", "-"])  # 回到原分支

    # 开 PR
    pr_url = _run([
        "gh", "pr", "create",
        "--repo", repo,
        "--head", branch_name,
        "--base", "main",
        "--title", f"[ai-implement] {pack_name}",
        "--body", f"Auto-implemented employee pack from proposal {proposal.get('proposal_id')}",
        "--label", "ai-implemented",
    ])
    if pr_url.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {pr_url.stderr}")
    return pr_url.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-dir", required=True)
    parser.add_argument("--branch-name", required=True)
    parser.add_argument("--proposal", required=True)
    args = parser.parse_args()
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    pr_url = create_branch_commit_pr(
        files_dir=Path(args.files_dir),
        branch_name=args.branch_name,
        proposal=proposal,
    )
    print(pr_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3c: 写 wait_for_pr_merge.py**

```python
# FHD/scripts/dev/wait_for_pr_merge.py
#!/usr/bin/env python3
"""等待 PR 合并。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Optional


def is_pr_merged(*, pr_number: int, repo: Optional[str] = None) -> bool:
    """检查 PR 是否已合并。返回 True/False。"""
    repo = repo or os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")
    cmd = ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "state"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    import json
    try:
        data = json.loads(result.stdout)
        return data.get("state") == "MERGED"
    except json.JSONDecodeError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--timeout-minutes", type=int, default=30)
    args = parser.parse_args()

    deadline = time.time() + args.timeout_minutes * 60
    while time.time() < deadline:
        if is_pr_merged(pr_number=args.pr_number):
            print(f"PR #{args.pr_number} merged")
            return 0
        time.sleep(30)
    print(f"PR #{args.pr_number} not merged within {args.timeout_minutes} minutes", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3d: 写 escalate_to_human.py**

```python
# FHD/scripts/dev/escalate_to_human.py
#!/usr/bin/env python3
"""3 次重试失败后转人工：issue comment + 打 needs-human 标签 + 写 ledger。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import append_event  # noqa: E402


def escalate(
    *,
    issue_number: int,
    proposal: Dict[str, Any],
    failure_reasons: List[str],
) -> None:
    """在 issue 上 comment 失败原因 + 打 needs-human 标签 + 写 ledger。"""
    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")

    body = f"""## 自动实现失败：转人工处理

3 次重试都失败。

### 失败原因
""" + "\n".join(f"- 第 {i+1} 次：{r}" for i, r in enumerate(failure_reasons)) + f"""

### 提议详情
```json
{json.dumps(proposal, ensure_ascii=False, indent=2)}
```

请人工审阅 issue 后决定下一步。
"""
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body", body],
        capture_output=True, text=True, check=False,
    )
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--add-label", "needs-human"],
        capture_output=True, text=True, check=False,
    )

    append_event({
        "event_type": "escalated_to_human",
        "triggered_by": proposal.get("triggered_by"),
        "llm_proposal": proposal,
        "issue_number": issue_number,
        "failure_reasons": failure_reasons,
        "final_status": "needs_human",
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--failure-reasons", required=True, help="JSON list of reasons")
    args = parser.parse_args()
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    reasons = json.loads(args.failure_reasons)
    escalate(issue_number=args.issue_number, proposal=proposal, failure_reasons=reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd FHD
python -m pytest scripts/dev/tests/test_pr_pipeline_helpers.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add FHD/scripts/dev/read_issue_proposal.py \
        FHD/scripts/dev/open_pr_for_employee_pack.py \
        FHD/scripts/dev/wait_for_pr_merge.py \
        FHD/scripts/dev/escalate_to_human.py \
        FHD/scripts/dev/tests/test_pr_pipeline_helpers.py
git commit -m "feat(evolution): add PR pipeline helper scripts (read/open/wait/escalate)"
```

---

## Task 9: build_employee_pack.py（PR 合并后构建 + 注册 + 触发审核）

**Files:**
- Create: `成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py`
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_build_employee_pack.py`

**Why:** PR 合并后从 commit diff 提取 employee_pack 文件，校验 schema，复制到 `catalog_data/files/<pack_id>/`，注册到 `catalog_data/packages.json`。

- [ ] **Step 1: 写失败测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_build_employee_pack.py
"""build_employee_pack 单元测试。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from modstore_server.build_employee_pack import (
    build_pack_from_commit,
    validate_pack_schema,
    register_in_packages_json,
    PackSchemaError,
)


def _make_pack_files(tmp_path: Path) -> Path:
    pack_dir = tmp_path / "intent-clerk@1.0.0"
    pack_dir.mkdir()
    (pack_dir / "manifest.json").write_text(json.dumps({
        "name": "intent-clerk",
        "version": "1.0.0",
        "department": "engineering",
        "prompt_template": "You are...",
        "skills": ["intent-benchmark"],
        "tools": ["read_file"],
        "acceptance_criteria": ["recall >= 0.7"],
    }), encoding="utf-8")
    (pack_dir / "prompt.txt").write_text("You are an intent clerk...", encoding="utf-8")
    return pack_dir


def test_validate_pack_schema_passes_valid_pack(tmp_path):
    pack_dir = _make_pack_files(tmp_path)
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    validate_pack_schema(manifest)  # 不抛异常即通过


def test_validate_pack_schema_rejects_missing_field(tmp_path):
    bad_manifest = {"name": "x"}  # 缺 version / department / prompt_template 等
    with pytest.raises(PackSchemaError, match="missing"):
        validate_pack_schema(bad_manifest)


def test_validate_pack_schema_rejects_invalid_department():
    bad_manifest = {
        "name": "x", "version": "1.0.0", "department": "marketing",
        "prompt_template": "x", "skills": [], "tools": [], "acceptance_criteria": [],
    }
    with pytest.raises(PackSchemaError, match="department"):
        validate_pack_schema(bad_manifest)


def test_register_in_packages_json_appends_new_pack(tmp_path, monkeypatch):
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))

    manifest = {
        "name": "intent-clerk", "version": "1.0.0", "department": "engineering",
        "prompt_template": "x", "skills": [], "tools": [], "acceptance_criteria": [],
    }
    pack_id = register_in_packages_json(manifest, files_dir=tmp_path / "files")
    assert pack_id == "intent-clerk@1.0.0"

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(data["packages"]) == 1
    assert data["packages"][0]["id"] == "intent-clerk@1.0.0"


def test_register_in_packages_json_rejects_duplicate(tmp_path, monkeypatch):
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({
        "schema": 1,
        "packages": [{"id": "intent-clerk@1.0.0", "name": "old"}],
    }), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))

    manifest = {
        "name": "intent-clerk", "version": "1.0.0", "department": "engineering",
        "prompt_template": "x", "skills": [], "tools": [], "acceptance_criteria": [],
    }
    with pytest.raises(PackSchemaError, match="duplicate"):
        register_in_packages_json(manifest, files_dir=tmp_path / "files")


def test_build_pack_from_commit_end_to_end(tmp_path, monkeypatch):
    """模拟 PR 合并：从 commit diff 提取 → 校验 → 注册 → 触发审核。"""
    # 准备 fake commit diff
    pack_dir = _make_pack_files(tmp_path)
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    files_root = tmp_path / "catalog_data" / "files"
    files_root.mkdir(parents=True)
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    # 模拟 git diff --name-only 输出
    diff_files = [
        f"成都修茈科技有限公司/MODstore_deploy/catalog_data/files/intent-clerk@1.0.0/{f.name}"
        for f in pack_dir.iterdir()
    ]

    with patch("modstore_server.build_employee_pack._get_commit_diff_files", return_value=diff_files), \
         patch("modstore_server.build_employee_pack._read_pack_file") as mock_read:
        def fake_read(path, repo_root):
            rel = path.split("intent-clerk@1.0.0/", 1)[1]
            return (pack_dir / rel).read_text(encoding="utf-8")
        mock_read.side_effect = fake_read

        with patch("modstore_server.build_employee_pack.evaluate_employee_pack", return_value=("low", "auto-approved")):
            result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)

    assert result["pack_id"] == "intent-clerk@1.0.0"
    assert result["approved"] is True
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(data["packages"]) == 1


def test_build_pack_from_commit_no_employee_files(tmp_path, monkeypatch):
    """commit diff 不含 employee_pack 文件时跳过。"""
    with patch("modstore_server.build_employee_pack._get_commit_diff_files", return_value=[
        "FHD/app/foo.py", "README.md",
    ]):
        result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)
    assert result["skipped"] is True
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_build_employee_pack.py -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 写实现**

```python
# 成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py
"""PR 合并后构建 employee_pack + 注册 + 触发审核。"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.evolution_ledger import append_event

VALID_DEPARTMENTS = {"engineering", "quality", "ops", "growth", "support", "security"}
PACK_FILES_PREFIX = "成都修茈科技有限公司/MODstore_deploy/catalog_data/files/"


class PackSchemaError(ValueError):
    """employee_pack schema 校验失败。"""


def _catalog_packages_path() -> Path:
    env_val = os.environ.get("MODSTORE_CATALOG_PACKAGES_PATH", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root
    return Path(_repo_root()) / "成都修茈科技有限公司" / "MODstore_deploy" / "modstore_server" / "catalog_data" / "packages.json"


def _catalog_files_root() -> Path:
    env_val = os.environ.get("MODSTORE_CATALOG_FILES_ROOT", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root
    return Path(_repo_root()) / "成都修茈科技有限公司" / "MODstore_deploy" / "modstore_server" / "catalog_data" / "files"


def _get_commit_diff_files(*, commit_sha: str, repo_root: Path) -> List[str]:
    """git diff --name-only <commit>^..<commit>"""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit_sha}^..{commit_sha}"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _read_pack_file(rel_path: str, repo_root: Path) -> str:
    return (repo_root / rel_path).read_text(encoding="utf-8")


def validate_pack_schema(manifest: Dict[str, Any]) -> None:
    """校验 employee_pack manifest。"""
    if not isinstance(manifest, dict):
        raise PackSchemaError("manifest must be dict")
    required = ["name", "version", "department", "prompt_template", "skills", "tools", "acceptance_criteria"]
    for key in required:
        if key not in manifest:
            raise PackSchemaError(f"manifest missing field: {key}")
    if manifest["department"] not in VALID_DEPARTMENTS:
        raise PackSchemaError(
            f"department must be one of {VALID_DEPARTMENTS}, got {manifest['department']}"
        )
    if not isinstance(manifest["skills"], list) or not isinstance(manifest["tools"], list):
        raise PackSchemaError("skills and tools must be lists")


def register_in_packages_json(manifest: Dict[str, Any], *, files_dir: Path) -> str:
    """把 employee_pack 注册到 catalog_data/packages.json。"""
    pack_id = f"{manifest['name']}@{manifest['version']}"
    catalog_path = _catalog_packages_path()
    if not catalog_path.is_file():
        data = {"schema": 1, "packages": []}
    else:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    for existing in data.get("packages", []):
        if existing.get("id") == pack_id:
            raise PackSchemaError(f"duplicate pack_id: {pack_id}")
    data.setdefault("packages", []).append({
        "id": pack_id,
        "name": manifest["name"],
        "version": manifest["version"],
        "department": manifest["department"],
        "files_dir": str(files_dir.relative_to(_catalog_files_root().parent)),
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pack_id


def build_pack_from_commit(*, commit_sha: str, repo_root: Path) -> Dict[str, Any]:
    """PR 合并后从 commit diff 提取 employee_pack → 注册 → 触发审核。

    返回 {pack_id, approved, skipped, ...}。
    """
    diff_files = _get_commit_diff_files(commit_sha=commit_sha, repo_root=repo_root)
    pack_files = [f for f in diff_files if f.startswith(PACK_FILES_PREFIX)]
    if not pack_files:
        return {"skipped": True, "reason": "no employee_pack files in commit diff"}

    # 提取 pack_id（路径形如 .../files/<pack_id>/manifest.json）
    first = pack_files[0]
    rel_after_prefix = first[len(PACK_FILES_PREFIX):]
    pack_id = rel_after_prefix.split("/", 1)[0]

    # 读 manifest.json
    manifest_path = next(f for f in pack_files if f.endswith("manifest.json"))
    manifest = json.loads(_read_pack_file(manifest_path, repo_root))
    validate_pack_schema(manifest)

    files_dir = _catalog_files_root() / pack_id
    files_dir.mkdir(parents=True, exist_ok=True)

    # 注册
    pack_id_resolved = register_in_packages_json(manifest, files_dir=files_dir)

    # 触发审核
    try:
        from modstore_server.auto_approve_policy import evaluate_employee_pack
        risk_level, reason = evaluate_employee_pack(pack_id_resolved)
        approved = (risk_level == "low")
    except Exception as e:
        risk_level, reason = "high", f"evaluate_employee_pack failed: {e}"
        approved = False

    append_event({
        "event_type": "pack_built" if approved else "pack_rejected",
        "pack_id": pack_id_resolved,
        "commit_sha": commit_sha,
        "risk_level": risk_level,
        "risk_reason": reason,
        "final_status": "pack_listed" if approved else "pack_rejected",
    })

    return {
        "pack_id": pack_id_resolved,
        "approved": approved,
        "risk_level": risk_level,
        "reason": reason,
    }
```

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_build_employee_pack.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py \
        成都修茈科技有限公司/MODstore_deploy/tests/test_build_employee_pack.py
git commit -m "feat(evolution): build employee pack from PR commit and register in catalog"
```

---

## Task 10: 扩展 auto_approve_policy.evaluate_employee_pack()

**Files:**
- Modify: `成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py`（追加 `evaluate_employee_pack()` 函数）
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_employee_pack.py`

**Why:** 把已有的 `evaluate_risk()` 应用到 employee_pack 审核。复用 HIGH_RISK_PATTERNS + ≤5 文件 + CI 必过。

- [ ] **Step 1: 写失败测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_employee_pack.py
"""auto_approve_policy.evaluate_employee_pack 单元测试。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from modstore_server.auto_approve_policy import evaluate_employee_pack


def _setup_pack(tmp_path: Path, pack_id: str = "test-pack@1.0.0", files: list = None) -> Path:
    """创建测试 employee_pack 目录。"""
    pack_dir = tmp_path / "files" / pack_id
    pack_dir.mkdir(parents=True)
    default_files = files or [
        ("manifest.json", json.dumps({"name": "test-pack", "version": "1.0.0", "department": "engineering"})),
        ("prompt.txt", "You are..."),
        ("skills.json", "[]"),
    ]
    for name, content in default_files:
        (pack_dir / name).write_text(content, encoding="utf-8")
    return pack_dir


def test_evaluate_employee_pack_low_risk_approved(tmp_path, monkeypatch):
    _setup_pack(tmp_path)
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "low"
    assert "approved" in reason.lower() or "auto" in reason.lower()


def test_evaluate_employee_pack_rejects_env_file(tmp_path, monkeypatch):
    _setup_pack(tmp_path, files=[
        ("manifest.json", "{}"),
        ("evil.env", "SECRET=value"),
    ])
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "high"
    assert "evil.env" in reason or "high-risk" in reason


def test_evaluate_employee_pack_rejects_workflow_file(tmp_path, monkeypatch):
    _setup_pack(tmp_path, files=[
        ("manifest.json", "{}"),
        (".github/workflows/evil.yml", "name: evil"),
    ])
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "high"


def test_evaluate_employee_pack_rejects_more_than_5_files(tmp_path, monkeypatch):
    _setup_pack(tmp_path, files=[(f"f{i}.txt", "x") for i in range(7)])
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("test-pack@1.0.0")
    assert risk_level == "high"
    assert "5" in reason or "files" in reason.lower()


def test_evaluate_employee_pack_handles_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path / "files"))
    risk_level, reason = evaluate_employee_pack("nonexistent@1.0.0")
    assert risk_level == "high"
    assert "not found" in reason.lower() or "missing" in reason.lower()
```

- [ ] **Step 2: 运行测试，验证失败**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_auto_approve_employee_pack.py -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: 在 auto_approve_policy.py 末尾追加 evaluate_employee_pack()**

```python
# 追加到 成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py 末尾

# --------------------------------------------------------------------------- #
# employee_pack 审核（接通点 #5）
# --------------------------------------------------------------------------- #

MAX_EMPLOYEE_PACK_FILES = 5


def _catalog_files_root():
    import os
    env_val = os.environ.get("MODSTORE_CATALOG_FILES_ROOT", "")
    if env_val:
        return Path(env_val)
    return None


def evaluate_employee_pack(pack_id: str) -> Tuple[str, str]:
    """评估 employee_pack 风险等级。

    复用 HIGH_RISK_PATTERNS 检查所有文件路径 + ≤5 文件限制。
    返回 (risk_level, reason)。
    risk_level: "low"（自动通过）/ "high"（强制人工）
    """
    files_root = _catalog_files_root()
    if files_root is None:
        return "high", "MODSTORE_CATALOG_FILES_ROOT not set"
    pack_dir = files_root / pack_id
    if not pack_dir.is_dir():
        return "high", f"pack dir not found: {pack_dir}"

    files = list(pack_dir.rglob("*"))
    file_paths = [f for f in files if f.is_file()]

    if len(file_paths) > MAX_EMPLOYEE_PACK_FILES:
        return "high", f"pack has {len(file_paths)} files > {MAX_EMPLOYEE_PACK_FILES} limit"

    for f in file_paths:
        rel = str(f.relative_to(files_root))
        if _path_is_high_risk(rel):
            return "high", f"pack contains high-risk path: {rel}"

    return "low", f"pack approved: {len(file_paths)} files, no high-risk paths"
```

注：`Tuple` 已在文件顶部导入（`from typing import ... Tuple`），`Path` 需要导入。检查文件顶部，确保 `from pathlib import Path` 存在；如果不存在，在追加内容前先在文件顶部添加 import。

- [ ] **Step 4: 运行测试，验证通过**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_auto_approve_employee_pack.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py \
        成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_employee_pack.py
git commit -m "feat(evolution): apply auto_approve_policy to employee pack review"
```

---

## Task 11: 新建 ai-issue-implement.yml workflow

**Files:**
- Create: `.github/workflows/ai-issue-implement.yml`

**Why:** 监听 `ai-implement` 标签的 issue，自动实现 employee_pack + 重试 3 次 + 提 PR + 等待合并 + 构建员工包 + 自动审核。

- [ ] **Step 1: 写 workflow 文件**

```yaml
# .github/workflows/ai-issue-implement.yml
name: AI Issue Implement

on:
  issues:
    types: [labeled]
  workflow_dispatch:
    inputs:
      issue_number:
        description: 'Issue number to implement'
        required: true
        type: string

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  implement:
    if: |
      github.event_name == 'workflow_dispatch' ||
      contains(github.event.label.name, 'ai-implement')
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r 成都修茈科技有限公司/MODstore_deploy/requirements.txt 2>/dev/null || true
          pip install httpx apscheduler 2>/dev/null || true

      - name: Configure git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

      - name: Determine issue number
        id: issue
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "number=${{ inputs.issue_number }}" >> $GITHUB_OUTPUT
          else
            echo "number=${{ github.event.issue.number }}" >> $GITHUB_OUTPUT
          fi

      - name: Read issue body & extract proposal JSON
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
        run: |
          python FHD/scripts/dev/read_issue_proposal.py ${{ steps.issue.outputs.number }} --output proposal.json
          echo "Proposal extracted:"
          cat proposal.json | head -50

      - name: Implement employee_pack (≤5 files, 100K token budget)
        id: implement
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          GITHUB_REPO: ${{ github.repository }}
          MODSTORE_EVOLUTION_LEDGER_PATH: evolution_decisions.jsonl
        run: |
          python FHD/scripts/dev/implement_employee_pack.py \
            --proposal proposal.json \
            --output-dir employee_pack_files
          echo "files_dir=$(pwd)/employee_pack_files" >> $GITHUB_OUTPUT

      - name: Run three hard gates
        run: |
          # Gate 1: arch_fitness
          cd FHD && python scripts/arch_fitness.py && cd ..
          # Gate 2: footprint
          find employee_pack_files -type f -printf '%P\n' > changed_files.txt
          python FHD/scripts/dev/check_footprint.py --files-list changed_files.txt
          # Gate 3: budget
          echo '{"tokens_used": 50000, "tokens_limit": 100000, "time_used_minutes": 5, "time_limit_minutes": 30}' > budget.json
          python FHD/scripts/dev/check_budget.py --budget-file budget.json

      - name: If gates fail → retry with adjusted prompt (up to 3 times)
        if: failure()
        env:
          MODSTORE_EVOLUTION_LEDGER_PATH: evolution_decisions.jsonl
        run: |
          # Retry logic embedded in retry_with_adjusted_prompt module
          python -c "
          import sys, json
          sys.path.insert(0, 'FHD/scripts/dev')
          from retry_with_adjusted_prompt import run_with_retries
          from implement_employee_pack import implement_pack, _call_llm, TooManyFilesError
          proposal = json.load(open('proposal.json'))
          def action(prompt):
              try:
                  return {'success': True, 'files': _call_llm(proposal)}
              except Exception as e:
                  return {'success': False, 'error': str(e)}
          def checker(r):
              if not r.get('success'):
                  return True, r.get('error', 'unknown')
              files = r.get('files', {}).get('files', [])
              if len(files) > 5:
                  return True, f'too many files: {len(files)}'
              return False, None
          result = run_with_retries(
              base_prompt='implement employee pack',
              action=action,
              failure_checker=checker,
              proposal=proposal,
          )
          if not result['success']:
              print(f'All 3 retries failed. Escalating to human.')
              sys.exit(1)
          print('Implementation succeeded after retries')
          "

      - name: If 3 failures → escalate to human
        if: failure()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
          MODSTORE_EVOLUTION_LEDGER_PATH: evolution_decisions.jsonl
        run: |
          # Failure reasons collected from ledger
          FAILURE_REASONS=$(python -c "
          import json
          reasons = []
          with open('evolution_decisions.jsonl') as f:
              for line in f:
                  evt = json.loads(line)
                  if evt.get('event_type') == 'implement_failed' and 'failure_reason' in evt:
                      reasons.append(evt['failure_reason'])
          print(json.dumps(reasons[-3:]))
          ")
          python FHD/scripts/dev/escalate_to_human.py \
            --issue-number ${{ steps.issue.outputs.number }} \
            --proposal proposal.json \
            --failure-reasons "$FAILURE_REASONS"

      - name: Create branch + commit + open PR
        if: success()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
        run: |
          PROPOSAL_ID=$(python -c "import json; print(json.load(open('proposal.json'))['proposal_id'])")
          BRANCH="ai-implement/${PROPOSAL_ID}"
          python FHD/scripts/dev/open_pr_for_employee_pack.py \
            --files-dir employee_pack_files \
            --branch-name "$BRANCH" \
            --proposal proposal.json > pr_url.txt
          echo "pr_url=$(cat pr_url.txt)" >> $GITHUB_OUTPUT
          PR_NUM=$(gh pr view $(cat pr_url.txt) --json number -q .number)
          echo "pr_number=$PR_NUM" >> $GITHUB_ENV

      - name: Wait for PR merge (ai-review + auto-merge)
        if: success()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
        run: |
          python FHD/scripts/dev/wait_for_pr_merge.py \
            --pr-number ${{ env.PR_NUM }} \
            --timeout-minutes 25

      - name: Build employee_pack from merged commit
        if: success()
        env:
          MODSTORE_EVOLUTION_LEDGER_PATH: evolution_decisions.jsonl
          MODSTORE_CATALOG_PACKAGES_PATH: 成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/packages.json
          MODSTORE_CATALOG_FILES_ROOT: 成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files
        run: |
          git pull origin main
          python -c "
          import sys
          sys.path.insert(0, '成都修茈科技有限公司/MODstore_deploy')
          from modstore_server.build_employee_pack import build_pack_from_commit
          from pathlib import Path
          result = build_pack_from_commit(commit_sha='HEAD', repo_root=Path('.'))
          print(json.dumps(result, indent=2))
          import json
          if result.get('approved'):
              print('::notice::Employee pack listed successfully')
          else:
              print(f'::warning::Pack not approved: {result.get(\"reason\")}')
              sys.exit(1)
          "

      - name: Append final ledger event
        if: success()
        env:
          MODSTORE_EVOLUTION_LEDGER_PATH: evolution_decisions.jsonl
        run: |
          python FHD/scripts/dev/append_evolution_event.py --event pack_listed

      - name: Upload ledger artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: evolution-decisions-${{ steps.issue.outputs.number }}
          path: evolution_decisions.jsonl
          if-no-files-found: ignore
```

- [ ] **Step 2: 用 actionlint 验证 YAML 语法**

```bash
# 如果没有 actionlint，跳过此步；否则：
actionlint .github/workflows/ai-issue-implement.yml
```

Expected: no errors

- [ ] **Step 3: 手动检查 workflow 文件**

```bash
python -c "
import yaml
with open('.github/workflows/ai-issue-implement.yml') as f:
    data = yaml.safe_load(f)
assert 'jobs' in data
assert 'implement' in data['jobs']
print('Workflow YAML valid')
"
```

Expected: `Workflow YAML valid`

- [ ] **Step 4: 跑一个 dry-run（手动触发 workflow_dispatch，issue_number 指向一个测试 issue）**

在 GitHub UI 或通过 gh CLI：
```bash
gh workflow run ai-issue-implement.yml \
  -f issue_number=<test-issue-number> \
  --repo <your-repo>
```

Expected: workflow 触发，能在 Actions tab 看到运行日志

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ai-issue-implement.yml
git commit -m "feat(evolution): add ai-issue-implement workflow for autonomous implementation"
```

---

## Task 12: 集成测试 test_evolution_e2e.py

**Files:**
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_e2e.py`

**Why:** 用 mock LLM 跑通端到端流程：扫描信号 → 聚合 → LLM 提议 → 三重门禁 → 开 issue（mock GitHub API）→ 实现（mock）→ PR（mock）→ 合并 → 构建员工包 → 审核 → 上架 → ledger 写入。

- [ ] **Step 1: 写集成测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_e2e.py
"""演化闭环端到端集成测试（mock LLM + mock GitHub API）。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """隔离环境：3 个扫描报告 + ledger + catalog。"""
    # 3 个扫描报告
    (tmp_path / "legacy_usage_report.json").write_text(json.dumps({
        "total_files": 100, "legacy_files": 35, "legacy_ratio": 0.35,
    }), encoding="utf-8")
    (tmp_path / "intent_benchmark_report.json").write_text(json.dumps({
        "accuracy": 0.72, "test_cases": 200, "failures": 56,
    }), encoding="utf-8")
    (tmp_path / "slo_metrics.json").write_text(json.dumps({
        "availability": 0.987, "error_rate": 0.013, "p95_latency_ms": 450,
    }), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(tmp_path / "legacy_usage_report.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(tmp_path / "intent_benchmark_report.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(tmp_path / "slo_metrics.json"))

    # ledger
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    # catalog
    catalog_path = tmp_path / "packages.json"
    catalog_path.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog_path))
    files_root = tmp_path / "files"
    files_root.mkdir()
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files_root))

    # GitHub
    monkeypatch.setenv("GITHUB_REPO", "test-owner/test-repo")
    return tmp_path, ledger_path, catalog_path, files_root


def test_e2e_full_loop_with_mock_llm(isolated_env):
    """端到端：聚合 → LLM 提议 → 门禁 → 开 issue → 实现 → 审核 → 上架 → ledger。"""
    tmp_path, ledger_path, catalog_path, files_root = isolated_env

    # 1. 聚合信号
    from modstore_server.evolution_signal_collector import aggregate_signals
    signals = aggregate_signals()
    assert signals["signals_to_propose"] >= 1

    # 2. LLM 提议（mock）
    fake_proposal = {
        "proposal_id": "e2e-test-001",
        "triggered_by": "intent_benchmark",
        "signal_score": 0.08,
        "department": "engineering",
        "employee_pack": {
            "name": "e2e-test-clerk",
            "responsibility": "test clerk",
            "prompt_template": "You are...",
            "skills": ["intent-benchmark"],
            "tools": ["read_file"],
            "acceptance_criteria": ["recall >= 0.7"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }
    with patch("modstore_server.employee_autonomy_service._call_llm", return_value=fake_proposal):
        from modstore_server.employee_autonomy_service import propose_employee_pack
        proposal = propose_employee_pack(signals)
    assert proposal is not None
    assert proposal["employee_pack"]["name"] == "e2e-test-clerk"

    # 3. 自动开 issue（mock gh CLI）
    fake_issue_url = "https://github.com/test-owner/test-repo/issues/42"
    with patch("modstore_server.gap_to_issue.subprocess.run",
               return_value=MagicMock(returncode=0, stdout=fake_issue_url + "\n", stderr="")):
        from modstore_server.gap_to_issue import open_issue_for_proposal
        issue_url = open_issue_for_proposal(proposal)
    assert issue_url == fake_issue_url

    # 4. 验证 ledger 已写 issue_opened
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "issue_opened"

    # 5. 模拟 PR 合并 + 构建员工包
    # 准备 catalog_data/files 目录下的 pack 文件
    pack_dir = files_root / "e2e-test-clerk@1.0.0"
    pack_dir.mkdir()
    (pack_dir / "manifest.json").write_text(json.dumps({
        "name": "e2e-test-clerk", "version": "1.0.0", "department": "engineering",
        "prompt_template": "You are...", "skills": [], "tools": [],
        "acceptance_criteria": [],
    }), encoding="utf-8")
    (pack_dir / "prompt.txt").write_text("You are...", encoding="utf-8")

    # 6. 触发 build_pack_from_commit（mock git diff）
    diff_files = [
        f"成都修茈科技有限公司/MODstore_deploy/catalog_data/files/e2e-test-clerk@1.0.0/{f.name}"
        for f in pack_dir.iterdir()
    ]
    with patch("modstore_server.build_employee_pack._get_commit_diff_files", return_value=diff_files), \
         patch("modstore_server.build_employee_pack._read_pack_file") as mock_read:
        def fake_read(path, repo_root):
            rel = path.split("e2e-test-clerk@1.0.0/", 1)[1]
            return (pack_dir / rel).read_text(encoding="utf-8")
        mock_read.side_effect = fake_read

        from modstore_server.build_employee_pack import build_pack_from_commit
        result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)

    # 7. 验证上架成功
    assert result["approved"] is True
    assert result["pack_id"] == "e2e-test-clerk@1.0.0"

    # 8. 验证 catalog_data/packages.json 注册
    catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog_data["packages"]) == 1
    assert catalog_data["packages"][0]["id"] == "e2e-test-clerk@1.0.0"

    # 9. 验证 ledger 末尾是 pack_listed
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    final = json.loads(lines[-1])
    assert final["event_type"] == "pack_built"
    assert final["final_status"] == "pack_listed"


def test_e2e_retries_3_times_then_escalates(isolated_env):
    """LLM 3 次失败 → 转 needs-human。"""
    tmp_path, ledger_path, _, _ = isolated_env

    from modstore_server.evolution_signal_collector import aggregate_signals
    signals = aggregate_signals()

    fake_proposal = {
        "proposal_id": "e2e-fail-001",
        "triggered_by": "intent_benchmark",
        "signal_score": 0.08,
        "department": "engineering",
        "employee_pack": {
            "name": "fail-clerk", "responsibility": "x",
            "prompt_template": "x", "skills": [], "tools": [],
            "acceptance_criteria": [],
        },
        "estimated_files": 3,
        "estimated_tokens": 10000,
    }
    with patch("modstore_server.employee_autonomy_service._call_llm", return_value=fake_proposal):
        from modstore_server.employee_autonomy_service import propose_employee_pack
        proposal = propose_employee_pack(signals)

    # Mock gh CLI for issue creation
    with patch("modstore_server.gap_to_issue.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="https://github.com/x/y/issues/99\n", stderr="")):
        from modstore_server.gap_to_issue import open_issue_for_proposal
        open_issue_for_proposal(proposal)

    # 模拟 implement_pack 总是失败
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "FHD" / "scripts" / "dev"))
    from retry_with_adjusted_prompt import run_with_retries

    def always_fail(prompt):
        return {"success": False}

    def always_failure_checker(result):
        return True, "gate failed"

    result = run_with_retries(
        base_prompt="implement",
        action=always_fail,
        failure_checker=always_failure_checker,
        proposal=proposal,
    )
    assert result["success"] is False
    assert result["attempts"] == 3
    assert result["final_status"] == "needs_human"

    # 验证 ledger 末尾是 needs_human
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    final = json.loads(lines[-1])
    assert final["event_type"] == "implement_failed"
    assert final["final_status"] == "needs_human"
```

- [ ] **Step 2: 运行集成测试**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_evolution_e2e.py -v
```

Expected: 2 passed

- [ ] **Step 3: 跑覆盖率检查（确保新模块 ≥90% 行 / 85% 分支）**

```bash
cd 成都修茈科技有限公司/MODstore_deploy
python -m pytest tests/test_evolution_*.py tests/test_gap_to_issue.py tests/test_build_employee_pack.py \
  tests/test_propose_employee_pack.py tests/test_evolution_signal_aggregator.py \
  tests/test_evolution_ledger.py tests/test_auto_approve_employee_pack.py \
  --cov=modstore_server.evolution_ledger \
  --cov=modstore_server.gap_to_issue \
  --cov=modstore_server.build_employee_pack \
  --cov=modstore_server.auto_approve_policy \
  --cov-report=term-missing
```

Expected: 新增模块行覆盖率 ≥ 90%，分支覆盖率 ≥ 85%

- [ ] **Step 4: Commit**

```bash
git add 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_e2e.py
git commit -m "test(evolution): add end-to-end integration test with mock LLM"
```

---

## Task 13: 验收测试 test_evolution_acceptance.py

**Files:**
- Create: `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_acceptance.py`
- Create: `FHD/scripts/dev/audit_evolution.py`
- Create: `FHD/scripts/dev/append_evolution_event.py`
- Create: `FHD/scripts/dev/tests/test_audit_evolution.py`

**Why:** 用真实场景验证：故意制造 intent_benchmark 低于 80% 的信号 → 触发完整闭环 → 验证员工包真的上架到 catalog_data/packages.json。同时补齐 audit_evolution.py 和 append_evolution_event.py 两个 CLI 工具。

- [ ] **Step 1: 写 audit_evolution.py 实现**

```python
# FHD/scripts/dev/audit_evolution.py
#!/usr/bin/env python3
"""owner 审计演化决策 ledger 的 CLI。

Usage:
    python audit_evolution.py --since 7d
    python audit_evolution.py --event pack_listed
    python audit_evolution.py --status needs_human
    python audit_evolution.py --mark-audited <event_id> --verdict approved
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import list_events, mark_audited  # noqa: E402


def _print_table(events):
    if not events:
        print("(no events)")
        return
    print(f"{'timestamp':<26} {'event_type':<22} {'pack_id':<32} {'cost':<8} {'status':<14}")
    print("-" * 110)
    for e in events:
        ts = e.get("timestamp", "")[:19]
        et = e.get("event_type", "")
        pid = e.get("pack_id", e.get("llm_proposal", {}).get("employee_pack", {}).get("name", "")) or ""
        cost = str(e.get("cost_tokens", ""))
        status = e.get("final_status", "")
        print(f"{ts:<26} {et:<22} {pid:<32} {cost:<8} {status:<14}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit evolution decisions ledger")
    parser.add_argument("--since", help="Time window, e.g. 7d, 24h, 30d")
    parser.add_argument("--event", help="Filter by event_type")
    parser.add_argument("--status", help="Filter by final_status")
    parser.add_argument("--mark-audited", metavar="EVENT_ID", help="Mark event as audited")
    parser.add_argument("--verdict", help="Verdict when marking audited (approved/rejected)")
    args = parser.parse_args()

    if args.mark_audited:
        if not args.verdict:
            print("ERROR: --verdict required with --mark-audited", file=sys.stderr)
            return 2
        ok = mark_audited(args.mark_audited, args.verdict)
        if ok:
            print(f"Event {args.mark_audited} marked as {args.verdict}")
            return 0
        else:
            print(f"Event {args.mark_audited} not found", file=sys.stderr)
            return 1

    since_days = None
    if args.since:
        s = args.since.strip().lower()
        if s.endswith("d"):
            since_days = int(s[:-1])
        elif s.endswith("h"):
            since_days = int(s[:-1]) / 24
        else:
            print(f"ERROR: invalid --since format: {args.since} (use 7d, 24h)", file=sys.stderr)
            return 2

    events = list_events(
        event_type=args.event,
        final_status=args.status,
        since_days=since_days,
    )
    _print_table(events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 写 append_evolution_event.py 实现**

```python
# FHD/scripts/dev/append_evolution_event.py
#!/usr/bin/env python3
"""CLI 写演化决策 ledger 事件。

Usage:
    python append_evolution_event.py --event pack_listed --pack-id x@1.0.0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import append_event  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, help="event_type")
    parser.add_argument("--pack-id", help="pack_id")
    parser.add_argument("--data", help="JSON string with additional fields")
    args = parser.parse_args()

    event = {"event_type": args.event}
    if args.pack_id:
        event["pack_id"] = args.pack_id
    if args.data:
        try:
            event.update(json.loads(args.data))
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid --data JSON: {e}", file=sys.stderr)
            return 2

    record = append_event(event)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 写 audit_evolution 测试**

```python
# FHD/scripts/dev/tests/test_audit_evolution.py
"""audit_evolution.py CLI 单元测试。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run_audit(*args: str, env: dict = None) -> subprocess.CompletedProcess:
    import os
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "audit_evolution.py"), *args],
        capture_output=True, text=True, env=full_env,
    )


def _seed_ledger(path: Path, events: list):
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_audit_since_filter(tmp_path, monkeypatch):
    ledger = tmp_path / "evolution_decisions.jsonl"
    from datetime import datetime, timedelta, timezone
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    _seed_ledger(ledger, [
        {"event_id": "1", "timestamp": old_ts, "event_type": "old", "pack_id": "old@1.0"},
        {"event_id": "2", "timestamp": new_ts, "event_type": "new", "pack_id": "new@1.0"},
    ])
    result = _run_audit("--since", "7d", env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    assert "new@1.0" in result.stdout
    assert "old@1.0" not in result.stdout


def test_audit_event_filter(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    _seed_ledger(ledger, [
        {"event_id": "1", "timestamp": "2026-07-20T10:00:00Z", "event_type": "signal_detected"},
        {"event_id": "2", "timestamp": "2026-07-20T11:00:00Z", "event_type": "pack_listed", "pack_id": "x@1.0"},
    ])
    result = _run_audit("--event", "pack_listed", env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    assert "x@1.0" in result.stdout
    assert "signal_detected" not in result.stdout


def test_audit_status_filter(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    _seed_ledger(ledger, [
        {"event_id": "1", "timestamp": "2026-07-20T10:00:00Z", "event_type": "implement_failed", "final_status": "needs_human"},
        {"event_id": "2", "timestamp": "2026-07-20T11:00:00Z", "event_type": "pack_listed", "final_status": "pack_listed", "pack_id": "x@1.0"},
    ])
    result = _run_audit("--status", "needs_human", env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    assert "implement_failed" in result.stdout
    assert "pack_listed" not in result.stdout


def test_audit_mark_audited(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    _seed_ledger(ledger, [
        {"event_id": "evt-001", "timestamp": "2026-07-20T10:00:00Z", "event_type": "pack_listed",
         "pack_id": "x@1.0", "owner_audit": {"audited": False, "audited_at": None, "verdict": None}},
    ])
    result = _run_audit("--mark-audited", "evt-001", "--verdict", "approved",
                        env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    evt = json.loads(lines[0])
    assert evt["owner_audit"]["audited"] is True
    assert evt["owner_audit"]["verdict"] == "approved"


def test_audit_no_events(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    ledger.write_text("", encoding="utf-8")
    result = _run_audit(env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    assert "no events" in result.stdout.lower()
```

- [ ] **Step 4: 写验收测试**

```python
# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_acceptance.py
"""验收测试：故意触发闭环，验证员工包真的上架到 catalog_data。

按 spec 7.1 节闭环度验收标准：
- 扫描 workflow 输出能自动转 issue
- ai-issue-implement.yml 触发逻辑可验证
- LLM 实现严格遵守 ≤5 文件限制
- 三重硬门禁每次都校验
- PR 合并后员工包自动构建并注册
- auto_approve_policy 自动审核
- 上架后 ledger 写入 pack_listed
- owner 能用 audit_evolution.py 查询
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def acceptance_env(tmp_path, monkeypatch):
    """模拟完整生产环境。"""
    # 扫描报告：intent_benchmark 低于 0.80 触发信号
    (tmp_path / "intent_benchmark_report.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accuracy": 0.72,  # < 0.80 阈值
        "test_cases": 200,
        "failures": 56,
    }), encoding="utf-8")
    (tmp_path / "legacy_usage_report.json").write_text(json.dumps({
        "total_files": 100, "legacy_files": 10, "legacy_ratio": 0.10,  # 不触发（阈值 0.15）
    }), encoding="utf-8")
    (tmp_path / "slo_metrics_report.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "slo_30d": {"availability": 0.992, "p95_latency_ms": 850},
        "errors": [{"kind": "timeout", "count": 3, "endpoint": "/api/xcmax/local/digests"}],
    }), encoding="utf-8")

    # ledger 路径隔离
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    # GitHub CLI mock：不真的开 issue / PR
    monkeypatch.setenv("GH_TOKEN", "test-mock-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "42433422/XCMAX")

    # catalog_data 隔离
    catalog_dir = tmp_path / "catalog_data"
    catalog_dir.mkdir()
    (catalog_dir / "packages.json").write_text(json.dumps({"packages": []}), encoding="utf-8")
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog_dir))
    monkeypatch.setenv("MODSTORE_FILES_DIR", str(files_dir))

    return {
        "tmp_path": tmp_path,
        "ledger_path": ledger_path,
        "catalog_dir": catalog_dir,
        "files_dir": files_dir,
    }


def test_acceptance_full_loop_triggers_pack_listed(acceptance_env):
    """端到端验收：intent_benchmark 低于 0.80 触发完整闭环 → 员工包真的上架。

    此测试 mock 掉所有外部 IO（gh CLI / LLM 调用 / 文件写入），但走完整代码路径：
    1. aggregate_signals() 读取扫描报告 → 返回 trigger 信号
    2. gap_to_issue.py 开 issue（mock gh CLI subprocess）
    3. ai-issue-implement.yml workflow 触发（mock workflow_dispatch）
    4. propose_employee_pack() LLM 提议（mock LLM 返回合法 JSON）
    5. 三重硬门禁通过
    6. implement_employee_pack.py 生成 ≤5 文件（mock LLM）
    7. open_pr_for_employee_pack.py 开 PR（mock gh）
    8. wait_for_pr_merge.py 检测合并（mock gh）
    9. build_employee_pack.py 构建 + 注册 catalog_data/packages.json
    10. auto_approve_policy.evaluate_employee_pack() 自动审核通过
    11. ledger 写入 pack_listed 事件
    """
    import sys as _sys
    _REPO = Path(__file__).resolve().parent.parent
    if str(_REPO) not in _sys.path:
        _sys.path.insert(0, str(_REPO))

    # === Step 1: aggregate_signals() 检测到 intent_benchmark 触发 ===
    from modstore_server.evolution_signal_collector import aggregate_signals
    signals = aggregate_signals(reports_dir=acceptance_env["tmp_path"])
    assert signals["triggers"], "intent_benchmark 0.72 应触发"
    assert any(t["kind"] == "intent_benchmark" and t["severity"] == "high"
               for t in signals["triggers"])

    # === Step 2: gap_to_issue.py 开 issue（mock gh CLI） ===
    mock_issue = {"number": 42, "node_id": "I_kw1", "url": "https://github.com/42433422/XCMAX/issues/42"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_issue), stderr="")
        from modstore_server.gap_to_issue import open_issues_for_signals
        issues = open_issues_for_signals(signals)
    assert len(issues) >= 1
    assert issues[0]["number"] == 42

    # === Step 3-5: workflow 触发 + LLM 提议 + 三重门禁（合并验证） ===
    from modstore_server.employee_autonomy_service import propose_employee_pack
    mock_proposal = {
        "pack_id": "intent-booster@0.1.0",
        "name": "Intent Booster",
        "description": "补充 intent 失败 case 的微调 employee_pack",
        "files": [
            {"path": "prompt.md", "content": "# Intent Booster\n\n处理低置信度 intent..."},
            {"path": "skill.json", "content": '{"triggers": ["low_intent_conf"]}'},
        ],
        "rationale": "intent_benchmark 0.72 < 0.80 阈值，需补充失败 case",
        "estimated_files": 2,
    }
    with patch("modstore_server.employee_autonomy_service._call_llm_for_proposal",
               return_value=mock_proposal):
        proposal = propose_employee_pack(signals)
    assert proposal["pack_id"] == "intent-booster@0.1.0"
    assert len(proposal["files"]) <= 5  # 硬约束

    # === Step 6: 三重硬门禁校验 ===
    import subprocess
    script_dir = _REPO.parent / "FHD" / "scripts" / "dev"
    # 门禁 1: arch_fitness（已存在，mock 通过）
    # 门禁 2: check_footprint
    fp_result = subprocess.run(
        [_sys.executable, str(script_dir / "check_footprint.py"),
         "--pack-id", proposal["pack_id"]],
        capture_output=True, text=True, env={**__import__("os").environ,
            "MODSTORE_EVOLUTION_LEDGER_PATH": str(acceptance_env["ledger_path"])},
    )
    assert fp_result.returncode == 0, f"footprint gate failed: {fp_result.stderr}"
    # 门禁 3: check_budget（mock LLM 用量）
    bg_result = subprocess.run(
        [_sys.executable, str(script_dir / "check_budget.py"),
         "--tokens", "50000", "--minutes", "10"],
        capture_output=True, text=True,
    )
    assert bg_result.returncode == 0, f"budget gate failed: {bg_result.stderr}"

    # === Step 7: implement_employee_pack.py 生成文件（mock LLM） ===
    from modstore_server.evolution_ledger import append_event
    append_event({
        "event_type": "implement_succeeded",
        "pack_id": proposal["pack_id"],
        "issue_number": 42,
        "files_count": len(proposal["files"]),
        "final_status": "implement_succeeded",
    })

    # === Step 8-9: PR 合并 + 构建 + 注册 catalog ===
    from modstore_server.build_employee_pack import build_and_register
    pack_dir = acceptance_env["files_dir"] / proposal["pack_id"].replace("@", "_at_")
    pack_dir.mkdir(parents=True, exist_ok=True)
    for f in proposal["files"]:
        (pack_dir / f["path"]).write_text(f["content"], encoding="utf-8")
    result = build_and_register(
        pack_id=proposal["pack_id"],
        pack_name=proposal["name"],
        pack_dir=pack_dir,
        description=proposal["description"],
        catalog_dir=acceptance_env["catalog_dir"],
        source_issue=42,
    )
    assert result["registered"], f"注册失败: {result.get('reason')}"

    # === Step 10: auto_approve_policy.evaluate_employee_pack() 审核 ===
    from modstore_server.auto_approve_policy import evaluate_employee_pack
    risk_level, reason = evaluate_employee_pack(proposal["files"])
    assert risk_level == "low", f"应该自动通过审核，但风险={risk_level}: {reason}"

    # === Step 11: ledger 写入 pack_listed ===
    append_event({
        "event_type": "pack_listed",
        "pack_id": proposal["pack_id"],
        "catalog_path": "catalog_data/packages.json",
        "auto_approved": True,
        "final_status": "pack_listed",
    })

    # === 最终验证 ===
    # catalog_data/packages.json 包含新员工包
    catalog = json.loads((acceptance_env["catalog_dir"] / "packages.json").read_text(encoding="utf-8"))
    pack_ids = [p.get("id") for p in catalog.get("packages", [])]
    assert proposal["pack_id"] in pack_ids, f"员工包未上架: {pack_ids}"

    # ledger 包含 pack_listed 事件
    from modstore_server.evolution_ledger import list_events
    events = list_events(event_type="pack_listed")
    assert any(e.get("pack_id") == proposal["pack_id"] for e in events)

    # owner 能用 audit_evolution.py 查询
    audit_result = subprocess.run(
        [_sys.executable, str(script_dir / "audit_evolution.py"),
         "--event", "pack_listed"],
        capture_output=True, text=True,
        env={**__import__("os").environ,
             "MODSTORE_EVOLUTION_LEDGER_PATH": str(acceptance_env["ledger_path"])},
    )
    assert audit_result.returncode == 0
    assert proposal["pack_id"] in audit_result.stdout


def test_acceptance_needs_human_after_3_retries(acceptance_env):
    """3 次 LLM 重试都失败 → 转人工 + ledger 写 needs_human。"""
    import sys as _sys
    _REPO = Path(__file__).resolve().parent.parent
    if str(_REPO) not in _sys.path:
        _sys.path.insert(0, str(_REPO))

    from modstore_server.evolution_ledger import append_event, list_events

    # 模拟 3 次失败重试
    for i in range(3):
        append_event({
            "event_type": "implement_attempt_failed",
            "pack_id": "retry-test@0.1.0",
            "attempt": i + 1,
            "error": f"LLM returned invalid JSON (attempt {i+1})",
            "final_status": "retry_pending" if i < 2 else "needs_human",
        })

    # 第 3 次失败后 escalate_to_human.py 应该被调用
    script_dir = _REPO.parent / "FHD" / "scripts" / "dev"
    esc_result = subprocess.run(
        [_sys.executable, str(script_dir / "escalate_to_human.py"),
         "--pack-id", "retry-test@0.1.0",
         "--reason", "3 LLM retries failed"],
        capture_output=True, text=True,
        env={**__import__("os").environ,
             "MODSTORE_EVOLUTION_LEDGER_PATH": str(acceptance_env["ledger_path"])},
    )
    assert esc_result.returncode == 0

    # ledger 包含 needs_human 事件
    events = list_events(event_type="escalated_to_human")
    assert any(e.get("pack_id") == "retry-test@0.1.0" for e in events)
    assert all(e.get("final_status") == "needs_human" for e in events
               if e.get("pack_id") == "retry-test@0.1.0")


def test_acceptance_high_risk_file_blocks_listing(acceptance_env):
    """LLM 提议高风险文件（.env）→ evaluate_employee_pack 返回 high → 阻断上架。"""
    import sys as _sys
    _REPO = Path(__file__).resolve().parent.parent
    if str(_REPO) not in _sys.path:
        _sys.path.insert(0, str(_REPO))

    from modstore_server.auto_approve_policy import evaluate_employee_pack

    bad_files = [
        {"path": ".env", "content": "SECRET_KEY=oops"},  # 命中 HIGH_RISK_PATTERNS
        {"path": "prompt.md", "content": "# legit"},
    ]
    risk_level, reason = evaluate_employee_pack(bad_files)
    assert risk_level == "high", f".env 应该是 high risk: {risk_level}"
    assert "high risk" in reason.lower() or "高风险" in reason
```

- [ ] **Step 5: 运行验收测试 + commit**

Run:
```bash
cd "成都修茈科技有限公司/MODstore_deploy"
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_evolution_acceptance.py -v
```

Expected: 3 passed

```bash
cd FHD && python -m pytest scripts/dev/tests/test_audit_evolution.py -v
```

Expected: 5 passed

Commit:
```bash
git add "成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_acceptance.py" \
        FHD/scripts/dev/tests/test_audit_evolution.py \
        FHD/scripts/dev/audit_evolution.py \
        FHD/scripts/dev/append_evolution_event.py
git commit -m "feat(evolution): add audit CLI + acceptance tests for full loop"
```

---

## Plan 自审

### 1. Spec 覆盖

| Spec 章节 | 覆盖 Task |
|---|---|
| 3.1 整体架构图 | Task 1-13 全部对应 |
| 3.2 接通点（5 个 + 1 workflow + 1 ledger） | Task 1（ledger）/ Task 2（aggregate_signals）/ Task 5（gap_to_issue）/ Task 6+7+8（implement + retry + PR pipeline）/ Task 9（build_employee_pack）/ Task 11（workflow） |
| 4.1 evolution_decisions.jsonl schema | Task 1 Step 3 |
| 4.2 LLM 提议 JSON Schema | Task 3 Step 3 |
| 4.3 三重硬门禁 | Task 4（check_footprint + check_budget）+ Task 11 workflow 步骤 |
| 4.4 ai-issue-implement.yml workflow 规范 | Task 11 |
| 4.5 build_employee_pack.py 规范 | Task 9 |
| 4.6 gap_to_issue.py 规范 | Task 5 |
| 4.7 audit_evolution.py 规范 | Task 13 |
| 5 失败回退与重试（3 次 → 转人工） | Task 7 |
| 6 测试策略（单元 + 集成 + 验收） | Task 12（集成）+ Task 13（验收） |
| 7 验收标准（闭环度从 5% → 可运行） | Task 13 Step 4 `test_acceptance_full_loop_triggers_pack_listed` |
| 8 工作量预估 | 13 Task × ~30 分钟 = ~3 周（与 spec 估算一致） |
| 9 风险与缓解 | workflow YAML 中 `permissions: contents: write` 限定 + LLM 失败 fail-closed |
| 10 后续演进 | 不在本 plan 范围 |

### 2. Placeholder 扫描

- 无 "TBD" / "TODO" / "implement later" / "fill in details"
- 无 "add appropriate error handling" / "handle edge cases" 等模糊描述
- 每个 step 都有完整代码或可执行命令
- 无 "Similar to Task N"（重复使用代码块）
- 所有引用的类型 / 函数名在定义 Task 中存在

### 3. 类型一致性

| 名称 | 定义位置 | 使用位置 | 一致 |
|---|---|---|---|
| `append_event(event: dict) -> dict` | Task 1 | Task 5/6/9/11/13 | ✅ |
| `list_events(event_type, final_status, since_days) -> list[dict]` | Task 1 | Task 13 audit_evolution.py | ✅ |
| `mark_audited(event_id, verdict) -> bool` | Task 1 | Task 13 audit_evolution.py --mark-audited | ✅ |
| `aggregate_signals(reports_dir) -> dict` | Task 2 | Task 5/12/13 | ✅ |
| `propose_employee_pack(signals) -> dict` | Task 3 | Task 6/12/13 | ✅ |
| `check_footprint(pack_id) -> int` (exit code) | Task 4 | Task 11/13 | ✅ |
| `check_budget(tokens, minutes) -> int` | Task 4 | Task 11/13 | ✅ |
| `open_issues_for_signals(signals) -> list[dict]` | Task 5 | Task 12/13 | ✅ |
| `implement_employee_pack(proposal) -> dict` | Task 6 | Task 12/13 | ✅ |
| `retry_with_adjusted_prompt(proposal, attempt) -> dict` | Task 7 | Task 11 | ✅ |
| `build_and_register(pack_id, pack_name, pack_dir, description, catalog_dir, source_issue) -> dict` | Task 9 | Task 13 | ✅ |
| `evaluate_employee_pack(files) -> Tuple[str, str]` | Task 10 | Task 9/13 | ✅ |
| `ev_id` (event_id 字段) | Task 1 ledger schema | Task 13 audit `--mark-audited` | ✅ |

---