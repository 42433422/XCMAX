# skill-model-routing-strategy

职责：按员工任务复杂度建议模型分配——简单任务用便宜模型，复杂推理用强模型，离线场景用 Ollama。

## 适用场景

- 新员工入职：根据其 `domain` 与 `capabilities` 推荐默认模型路由。
- 周度复盘：根据上周 token 用量与质量评分重新调整路由。
- 异常处置：当某员工成本/质量失衡时，重审其模型路由。

## 标准流程

1. 拉取员工清单与任务画像：
   - `employee_id` / `domain` / `capabilities` / `task_type_distribution`。
2. 按任务类型分类路由：

   | 任务类型 | 推荐模型 | 备选 | 兜底 |
   |---|---|---|---|
   | 文档解析 / 格式化 | deepseek-chat | qwen-turbo | glm-4-flash |
   | 多轮对话 / 工具调用 | deepseek-chat | qwen-plus | glm-4 |
   | 代码生成 / 审查 | deepseek-reasoner | qwen-coder | claude-sonnet（仅关键审查） |
   | 长链推理 / 数学 | deepseek-reasoner-r1 | qwen-max | ollama:qwen2.5 |
   | 离线 / 隐私场景 | ollama:qwen2.5 | ollama:deepseek-r1-distill | （无） |

3. 输出路由策略表：

```json
{
  "employee_id": "employee-xxx",
  "routing": {
    "default_model": "deepseek-chat",
    "by_task_type": {
      "code_review": {"model": "deepseek-reasoner", "rationale": "需更强推理"},
      "translation": {"model": "qwen-turbo", "rationale": "简单任务用便宜模型"}
    },
    "fallback": "ollama:qwen2.5"
  },
  "estimated_monthly_cost_cny": 12.5,
  "compared_to_current": -45.0
}
```

4. 提交到 `modstore-backend-api` 在 `llm_key_resolver.py` 中落地：
   - 生成 PR 草稿，不直接合并。
   - 由 `change-request-auditor` 评审。

## 调整原则

- 简单任务（输入 < 2k tokens，输出 < 500 tokens）默认用最便宜的可用模型。
- 复杂推理任务才用 reasoning 模型，且必须有用例支撑。
- 同一员工不同任务类型可以走不同模型，按 `task_type` 字段路由。
- 国产模型优先，海外模型仅作为复杂推理的备选。

## 禁止事项

- 把所有员工都路由到同一个强模型（成本失控）。
- 把代码审查类任务路由到非代码模型（如纯对话模型）。
- 未经 admin 审批直接改 `llm_key_resolver.py`。

## 输出契约

- summary：路由策略结论。
- evidence：员工任务画像、模型价格表、上周用量数据。
- risks：质量下降风险、成本增长风险、模型下线风险。
- next_actions：路由变更 PR、admin 审批、上线后跟踪 7 天质量。
- requires_human：路由变更必须人工确认。
