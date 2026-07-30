# 认知全栈补齐（2026-07-29）

针对五项缺口的工程落地（非 AGI 宣称）：

| 缺口 | 落地 | 关键路径 |
|------|------|----------|
| 无因果推理 | SCM lite + 反事实探针 | `app/domain/neuro/cognition/causal_graph.py` / `counterfactual.py` |
| 绑死业务意图 | 技能契约 + 开放世界提案 | `skill_contract.py` + `resources/neuro/skill_contracts.json` |
| 无持续学习 | 三类反馈 → 路由策略通道 | `evolution/learning_feedback.py`（不在线改分类器） |
| 硬编码阈值 | 软约束代价函数 | `plan_constraints.py` + `soft_constraints.json` |
| 无自我反思 | 白名单 critique→shadow→canary→promote | `evolution/self_reflection.py` + `evolution.reflect` |

## 安全边界

- **可自动晋升**：routing_policy / skill_description / slot_schema / soft_constraints / prompt_template / attention_weights
- **禁止自改**：processor_topology / permission_boundary / payment|inventory side_effect / source_code / cognitive_architecture（仅 RFC）

## 接线

- `IntentConfirmationService`：unk → 技能候选或开放提案
- `ConsciousLLMHandler`：注入因果叙事与技能契约
- `CognitiveRouter`：软约束路径建议 + 软 SLA
- `WorkflowPlanner`：多步 PlanGraph JSONL 落盘；校验失败触发 prompt 反思提案
- `EvolutionHandler`：新增 `evolution.reflect`

## 战略规划（自治层，非阈值机）

- `StrategicPlanner`：LLM 拆解「这个季度做哪三个功能」+ `reflect_and_revise`
- `adaptive_thresholds`：`CRASH_THRESHOLD` 等硬常量 → floor/ceiling 软约束
- API：`POST /api/xcmax/ops/strategic-plan`；CLI：`scripts/autonomy/strategic_quarterly_planner.py`
- Impact LLM 顾问轨：`scripts/autonomy/impact_advisor.py`（`XCAGI_IMPACT_LLM=1`）

## 验收

```bash
cd FHD && python -m pytest tests/test_neuro_bus/test_cognitive_full_stack.py tests/test_autonomy/test_strategic_planner.py -q
```
