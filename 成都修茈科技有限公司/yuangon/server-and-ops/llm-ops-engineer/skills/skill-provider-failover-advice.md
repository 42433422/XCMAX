# skill-provider-failover-advice

职责：当主 provider 不可用时，按预设优先级推荐备选 provider 与切换方案。

## 适用场景

- 主 provider 失效（key 失效 / 欠费 / 服务中断）。
- 主 provider 限流严重，影响业务 SLA。
- 主 provider 区域性故障（如海外 provider 国内访问异常）。

## 标准流程

1. 调 `test_llm_key_health` 确认主 provider 当前状态。
2. 查 `llm_key_resolver.py` 中的预设 failover 链：

   | 主 provider | 备 1 | 备 2 | 兜底 |
   |---|---|---|---|
   | deepseek | tongyi | zhipu | ollama-local |
   | openai | openrouter | deepseek | ollama-local |
   | claude | deepseek-reasoner | tongyi | ollama-local |

3. 对备选链逐一调 `test_llm_key_health` 确认可用性。
4. 评估切换影响：
   - 模型能力差距（如 Claude → DeepSeek-Reasoner 推理质量下降）。
   - 延迟差距。
   - 成本差距。
5. 输出切换建议：

```json
{
  "status": "failover_recommended",
  "summary": "deepseek 失效，建议切 tongyi-qwen-plus，质量差距 0.5，延迟更优",
  "from": {"provider": "deepseek", "reason": "key_invalid"},
  "to": {"provider": "tongyi", "model": "qwen-plus", "fallback_chain": ["zhipu", "ollama-local"]},
  "impact": {"quality_delta": -0.5, "latency_delta_ms": -400, "cost_delta_pct": -50},
  "required_changes": [
    {"file": "MODstore_deploy/modstore_server/llm_key_resolver.py", "change": "default_provider: deepseek → tongyi"}
  ],
  "requires_human": true
}
```

## 切换原则

- 优先切到能力最接近的备选 provider，而不是最便宜的。
- 兜底用 Ollama 本地模型，即使质量下降也要保证业务可用。
- 切换前必须确认备选 key 健康。

## 禁止事项

- 未经 admin 审批直接改 `llm_key_resolver.py` 中的路由配置。
- 切到已失效的备选 provider。
- 在切换建议中遗漏模型能力差距评估。

## 输出契约

- summary：切换结论。
- evidence：主 provider 失效证据 + 备选链健康检查结果。
- risks：质量下降、延迟变化、成本变化。
- next_actions：路由变更 PR、key 轮换同步、admin 审批。
- requires_human：路由变更必须人工确认。
