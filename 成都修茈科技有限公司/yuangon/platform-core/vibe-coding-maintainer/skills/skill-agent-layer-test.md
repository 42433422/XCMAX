# ESkill：Agent 层测试与修复（skill-agent-layer-test）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-agent-layer-test` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | vibe-coding agent 子包质量维护 |
| 版本 | 1.0.0 |

---

## 1. 静态阶段

**工作目录**：仓库根下 `vibe-coding/`（以下 pytest 路径均相对于该目录）。

**触发条件**：`vibe-coding/src/vibe_coding/agent/` 下任意文件变更，或定时巡检触发。

**执行逻辑**：

```
python -m compileall -q src/vibe_coding/agent
→ python -m pytest tests/agent/ -q --tb=short
→ python -m pytest tests/agent/ --cov=src/vibe_coding/agent --cov-report=term-missing -q
→ 输出报告
```

**说明**：`tests/agent/marketplace/` 含技能包发布相关单测，包含在 `tests/agent/` 内，无需单独列出。
**输出 schema**：
```json
{
  "status": "ok | error",
  "tests_passed": 0,
  "tests_failed": 0,
  "coverage_pct": 0.0,
  "syntax_errors": [],
  "failed_modules": []
}
```

**工具绑定**：
- `python -m py_compile` — 语法检查
- `python -m pytest tests/agent/` — 测试运行
- `python -m pytest --cov` — 覆盖率检查

---

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 执行报错 | SyntaxError / ImportError | 即触发 |
| 结果不达标 | `tests_failed > 0` 或 `coverage_pct < 85` | 即触发 |

---

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：5000
- 最大步数：6

**允许改动的模块白名单**：
- `vibe-coding/src/vibe_coding/agent/**`
- `vibe-coding/tests/agent/**`

**LLM 任务**：分析失败 test traceback → 定位 agent 层 bug → 生成最小修复 diff → 补充缺失测试 case。

---

## 4. 固化

**验收标准**：
- `tests_failed == 0`
- `coverage_pct ≥ 85`
- agent 层公开接口签名无 break
- 无新增 SyntaxError / ImportError

---

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| agent 层测试通过率 | 100% |
| agent 层覆盖率 | ≥ 85% |
| 静态路径成功率 | ≥ 95% |
| 平均延迟 | < 30s（含测试运行） |
