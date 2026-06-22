# NeuroBus 升级批次 2 实施计划：NN 路由训练闭环

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** 完成 NN 路由训练闭环（LLM 交叉评审标注 + 离线预训练 + 在线 Bandit 微调 + 影子/灰度部署）。

**Architecture:** 三模型盲标 + LLM-D 仲裁 → 训练 RoutingMLP → 影子模式 → 灰度 → 全量。在线用 MLP 推理保延迟，Bandit 微调保持续优化。

**Tech Stack:** Python 3.11 / PyTorch / OpenAI SDK / DeepSeek SDK / pytest

**Spec:** `docs/superpowers/specs/2026-06-19-neurobus-upgrade-design.md` 第 2 节

---

## Task 1: routing_log 扩展字段

**Files:**
- Modify: `FHD/app/neuro_bus/routing/routing_log.py`
- Test: `FHD/tests/test_neuro_bus/test_routing_log.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_neuro_bus/test_routing_log.py
"""routing_log 扩展字段测试。"""
import json
from pathlib import Path


def test_append_routing_decision_with_sla_fields(tmp_path, monkeypatch):
    """扩展 sla_hit/success/latency_ms 字段。"""
    log_path = tmp_path / "routing.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    from app.neuro_bus.routing.routing_log import append_routing_decision

    append_routing_decision(
        trace_id="t1",
        features=[0.1] * 16,
        action="reflex",
        latency_ms=0.5,
        outcome="policy_selected",
        reward=0.8,
        sla_hit=True,
        success=True,
        extra={"source": "policy_mlp"},
    )

    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["sla_hit"] is True
    assert row["success"] is True
    assert row["reward"] == 0.8
    assert row["latency_ms"] == 0.5


def test_append_routing_decision_backward_compatible(tmp_path, monkeypatch):
    """旧调用（不传 sla_hit/success）仍可工作。"""
    log_path = tmp_path / "routing.jsonl"
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))

    from app.neuro_bus.routing.routing_log import append_routing_decision

    append_routing_decision(
        trace_id="t2",
        features=[0.2] * 16,
        action="conscious",
        latency_ms=100.0,
        outcome="rule_selected",
    )

    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["sla_hit"] is None
    assert row["success"] is None
```

- [ ] **Step 2: 运行验证失败**

Run: `cd FHD && source .venv/bin/activate && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_neuro_bus/test_routing_log.py -v`
Expected: FAIL（`sla_hit` 参数不存在）

- [ ] **Step 3: 修改 routing_log.py**

```python
def append_routing_decision(
    trace_id: str | None,
    features: list[float],
    action: str,
    latency_ms: float,
    outcome: str,
    reward: float | None = None,
    sla_hit: bool | None = None,
    success: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    row = {
        "ts": time.time(),
        "trace_id": trace_id,
        "features": features,
        "action": action,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "reward": reward,
        "sla_hit": sla_hit,
        "success": success,
        "extra": extra or {},
    }
    # ... 其余不变
```

- [ ] **Step 4: 验证通过 + commit**

---

## Task 2: policy_nn 改 softmax

**Files:**
- Modify: `FHD/app/neuro_bus/routing/policy_nn.py`

- [ ] **Step 1: 新增 predict_with_confidence 函数**

```python
def predict_with_confidence(features: list[float], mask: list[bool] | None = None) -> tuple[int, float]:
    """返回 (action_index, confidence)，confidence 来自 softmax。"""
    pol = get_policy()
    if pol is None or torch is None:
        return -1, 0.0
    x = torch.tensor([features], dtype=torch.float32, device=_policy_device)
    with torch.no_grad():
        logits = pol(x)[0]
        if mask is not None and len(mask) == NUM_ACTIONS:
            for i, m in enumerate(mask):
                if not m:
                    logits = logits.clone()
                    logits[i] = float("-inf")
        probs = torch.softmax(logits, dim=0)
        idx = int(torch.argmax(probs).item())
        conf = float(probs[idx].item())
        return idx, conf
```

- [ ] **Step 2: commit**

---

## Task 3: policy_router 影子模式 + 灰度 + reward 记录

**Files:**
- Modify: `FHD/app/neuro_bus/routing/policy_router.py`

- [ ] **Step 1: 改造 decide_processor_with_policy**

```python
import random

def decide_processor_with_policy(
    text: str,
    event: NeuroEvent | None = None,
    *,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> RoutingDecision | None:
    raw = (os.environ.get("XCAGI_ROUTING_POLICY_ENABLED") or "").strip().lower()
    if raw not in {"1", "true", "yes", "on", "shadow"}:
        return None

    is_shadow = raw == "shadow"
    t0 = time.perf_counter()
    feats = build_routing_features(text, event, extra)
    idx, conf = predict_with_confidence(feats)
    if idx < 0 or idx >= len(_ACTION_ORDER):
        return None

    proc = _ACTION_ORDER[idx]
    latency_ms = (time.perf_counter() - t0) * 1000
    tid = trace_id or (event.metadata.trace_id if event else None)

    # 灰度比例控制
    if not is_shadow and raw in {"1", "true", "yes", "on"}:
        canary = float(os.environ.get("XCAGI_ROUTING_POLICY_CANARY_RATIO", "1.0") or "1.0")
        if random.random() > canary:
            return None  # 灰度未命中，回退规则路由

    append_routing_decision(
        trace_id=tid,
        features=feats,
        action=proc.value,
        latency_ms=latency_ms,
        outcome="shadow_selected" if is_shadow else "policy_selected",
        reward=None,
        sla_hit=None,
        success=None,
        extra={"source": "policy_mlp", "confidence": conf, "shadow": is_shadow},
    )

    if is_shadow:
        return None  # 影子模式不实际路由

    return RoutingDecision(
        processor_type=proc,
        confidence=conf,
        reason=f"routing_policy_mlp:{idx}",
    )
```

- [ ] **Step 2: commit**

---

## Task 4: LLM 交叉评审标注脚本

**Files:**
- Create: `FHD/scripts/dev/llm_label_ensemble.py`
- Create: `FHD/scripts/dev/llm_label_arbitrate.py`
- Create: `FHD/scripts/dev/analyze_label_consensus.py`

- [ ] **Step 1: 实现 llm_label_ensemble.py**（三模型并行标注）

- [ ] **Step 2: 实现 llm_label_arbitrate.py**（争议样本 LLM-D 仲裁）

- [ ] **Step 3: 实现 analyze_label_consensus.py**（一致性分析 + 偏差检测）

- [ ] **Step 4: commit**

---

## Task 5: 训练脚本

**Files:**
- Create: `FHD/scripts/dev/train_routing_policy.py`

- [ ] **Step 1: 实现离线训练脚本**（读标注数据 → 训练 MLP → 保存 policy_vN.pt + manifest）

- [ ] **Step 2: commit**

---

## Task 6: 评估脚本

**Files:**
- Create: `FHD/scripts/dev/eval_routing_policy.py`

- [ ] **Step 1: 实现评估脚本**（准确率 / SLA 提升 / 推理延迟）

- [ ] **Step 2: commit**

---

## Task 7: 在线微调器

**Files:**
- Create: `FHD/app/neuro_bus/routing/online_learner.py`

- [ ] **Step 1: 实现 OnlineLearner**（滑动窗口 + ε-greedy + off-policy 修正 + 增量更新）

- [ ] **Step 2: commit**

---

## Task 8: 测试 + 回归

- [ ] **Step 1: 写测试**
- [ ] **Step 2: 全量回归**
- [ ] **Step 3: lint + mypy**
