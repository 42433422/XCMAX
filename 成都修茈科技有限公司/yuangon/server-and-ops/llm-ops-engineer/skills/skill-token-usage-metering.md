# skill-token-usage-metering

职责：统计各员工/各模型/各时段的 token 消耗与成本，识别烧钱大户与异常突增。

## 适用场景

- 日常巡检：每天拉 24h token Top-N。
- 月度成本报告：按员工/模型/任务类型聚合。
- 异常告警：某员工单日 token 占比 > 30% 触发调查。

## 标准流程

1. 调 `query_local_token_usage` 从本地 `llm_billing` 表拉数据：
   - 维度：`employee_id`、`model_name`、`provider`、`task_type`、`period`。
   - 聚合：`total_input_tokens`、`total_output_tokens`、`total_cost_cny`。
2. 调 `query_provider_usage` 拉 provider 侧对账数据，与本地计量比对：
   - 偏差 > 5% 标红，需 `dbops-engineer` 协同核对。
3. 调 `query_cursor_usage` / `query_codex_usage` / `query_trae_usage` 拉第三方 IDE 类调用统计（如果走 IDE 渠道）。
4. 识别异常：
   - 单日 token 占比 > 30% 的员工 → 标红，需进一步分析 prompt 是否过长 / 死循环 / 误用强模型。
   - 单次调用 token > 50k → 标红，检查是否有上下文膨胀。
   - 成本环比增长 > 20% → 标红，出降本建议。
5. 输出结构化报告：

```json
{
  "status": "ok|warn",
  "summary": "24h 内共消耗 12.3M tokens，成本 ¥123.45，Top1: employee-xxx 占 35%",
  "items": [
    {"employee_id": "xxx", "model": "deepseek-chat", "tokens": 4300000, "cost_cny": 43.00, "pct": 35.0}
  ],
  "warnings": ["employee-xxx 单日 token 占比 35% 超阈值 30%"],
  "meta": {"period": "24h", "checked_at": "..."}
}
```

## 计费口径

- 价格表以 `skill-model-cost-comparison` 维护的为准。
- 输入/输出 token 分别计费。
- 国产 provider 用 CNY，海外 provider 用 USD（按当日汇率折算）。
- 精度：0.0001 CNY / 0.0001 USD。

## 禁止事项

- 用估算代替真实账单数据。
- 把第三方 IDE 调用与平台 API 调用混计。
- 在月度报告中遗漏任一在岗员工。

## 输出契约

- summary：总体消耗与异常摘要。
- evidence：本地计量、provider 对账、IDE 渠道统计的原始数据。
- risks：异常突增、对账偏差、配额耗尽风险。
- next_actions：是否需要调整模型路由、是否需要限流、是否需要 admin 介入。
- requires_human：模型路由策略调整需人工确认。
