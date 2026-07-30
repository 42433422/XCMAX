# 认知全栈补齐报告（2026-07-29）

## 已解决

1. **因果**：订单履约 SCM lite + 反事实探针，区分因果边与相关边。
2. **跨域/开放意图**：`skill_contracts.json` 技能契约；unk 走候选技能或 `open.*` 提案。
3. **持续学习**：user_correction / task_outcome / sla_hit → `routing_decisions.jsonl`；明确不在线改意图分类器。
4. **自主规划**：硬阈值降级为软约束代价；多步 PlanGraph 强制 JSONL。
5. **自我反思**：白名单补丁环 + `evolution.reflect`；架构变更拒绝自动晋升。

## 测试

`tests/test_neuro_bus/test_cognitive_full_stack.py`
