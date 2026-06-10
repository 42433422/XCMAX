# ESkill：工作流引擎维护（skill-workflow-engine-update）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-workflow-engine-update` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | vibe-coding 工作流引擎正确性与性能维护 |
| 版本 | 1.0.0 |

---

## 1. 静态阶段

**触发条件**：`workflow_engine.py`、`workflow_conditions.py`、`workflow_models.py`、`workflow_factory.py` 变更，或定时巡检触发。

**工作目录**：仓库根下 `vibe-coding/`（以下路径均相对于该目录）。

**执行逻辑**：

```
py_compile src/vibe_coding/workflow_engine.py src/vibe_coding/workflow_conditions.py \
  src/vibe_coding/workflow_models.py src/vibe_coding/workflow_factory.py
→ python -m pytest tests/test_workflow_engine.py tests/test_workflow_engine_p1.py \
  tests/test_workflow_factory.py tests/test_workflow_conditions.py -q --tb=short
（或等价：python -m pytest tests/test_workflow_*.py -q --tb=short）
→ python -m pytest tests/agent/test_advanced_workflow.py -q --tb=short
→ 检查 workflow_conditions.py 条件表达式的安全沙箱（无 eval/exec/任意属性访问）
→ 运行性能基准：生成 10 节点 workflow + execute（记录耗时）
→ 输出报告
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "tests_passed": 0,
  "tests_failed": 0,
  "condition_safety": "pass | fail",
  "perf_10node_ms": 0,
  "perf_baseline_ms": 0,
  "perf_regression": false,
  "syntax_errors": []
}
```

**工具绑定**：
- `python -m py_compile` — 语法检查
- `python -m pytest tests/test_workflow_*.py tests/test_workflow_conditions.py` — 工作流测试（`tests/test_workflow_conditions.py` 含条件沙箱用例）
- `python -m pytest tests/agent/test_advanced_workflow.py` — 高级工作流测试
- `time python -c "..."` — 性能基准

---

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 执行报错 | SyntaxError / ImportError | 即触发 |
| 结果不达标 | `tests_failed > 0` 或 `condition_safety == "fail"` | 即触发 |
| 性能回归 | `perf_10node_ms > perf_baseline_ms * 1.5` | 即触发 |

---

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：5000
- 最大步数：6

**允许改动的模块白名单**：
- `vibe-coding/src/vibe_coding/workflow_engine.py`
- `vibe-coding/src/vibe_coding/workflow_conditions.py`
- `vibe-coding/src/vibe_coding/workflow_models.py`
- `vibe-coding/src/vibe_coding/workflow_factory.py`
- `vibe-coding/tests/test_workflow_engine.py`
- `vibe-coding/tests/test_workflow_engine_p1.py`
- `vibe-coding/tests/test_workflow_factory.py`
- `vibe-coding/tests/test_workflow_conditions.py`
- `vibe-coding/tests/agent/test_advanced_workflow.py`

**LLM 任务**：分析失败 test traceback → 定位 workflow 引擎 bug → 生成最小修复 diff → 验证条件表达式安全性 → 补充缺失测试 case。

---

## 4. 固化

**验收标准**：
- `tests_failed == 0`
- `condition_safety == "pass"`
- `perf_regression == false`
- 接口签名无 break

---

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| 工作流测试通过率 | 100% |
| 条件表达式安全性 | pass |
| 性能回归率 | 0% |
| 静态路径成功率 | ≥ 95% |
