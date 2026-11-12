# skill-provider-failover-advice

职责：当主 provider 不可用或运营策略要求切换时，从平台统一模型目录选择目标，探活后直接切换平台 AI 员工运行时路由。

## 适用场景

- 主 provider 失效（key 失效 / 欠费 / 服务中断）。
- 主 provider 限流严重，影响业务 SLA。
- 主 provider 区域性故障（如海外 provider 国内访问异常）。

## 标准流程

1. 调 `test_llm_key_health` 确认主 provider 当前状态。
2. 调 `list_platform_llm_models` 查平台统一模型目录，再参考预设 failover 链：

   | 主 provider | 备 1              | 备 2     | 兜底         |
   | ----------- | ----------------- | -------- | ------------ |
   | deepseek    | tongyi            | zhipu    | ollama-local |
   | openai      | openrouter        | deepseek | ollama-local |
   | claude      | deepseek-reasoner | tongyi   | ollama-local |

3. 对备选链逐一调 `test_llm_key_health` 确认可用性。
4. 评估切换影响：
   - 模型能力差距（如 Claude → DeepSeek-Reasoner 推理质量下降）。
   - 延迟差距。
   - 成本差距。
5. 调 `switch_platform_llm_route` 执行切换，工具会再次检查目录归属、平台密钥和真实模型响应。
6. 调 `get_platform_llm_route` 确认生效；若质量、延迟或错误率恶化，调 `rollback_platform_llm_route` 回滚。
7. 输出切换回执：

```json
{
  "status": "failover_switched",
  "summary": "deepseek 失效，已切换至 dashscope/qwen-plus，对下一次平台 AI 员工调用生效",
  "from": { "provider": "deepseek", "reason": "key_invalid" },
  "to": { "provider": "tongyi", "model": "qwen-plus", "fallback_chain": ["zhipu", "ollama-local"] },
  "impact": { "quality_delta": -0.5, "latency_delta_ms": -400, "cost_delta_pct": -50 },
  "audit": { "revision": "...", "actor": "employee:llm-ops-engineer" },
  "rollback_available": true,
  "requires_human": false
}
```

## 切换原则

- 优先切到能力最接近的备选 provider，而不是最便宜的。
- 兜底用 Ollama 本地模型，即使质量下降也要保证业务可用。
- 切换前必须确认备选 key 健康且模型属于平台目录。
- 切换对「平台出资的 AI 员工调用」生效，不改动用户 BYOK 与用户个人默认模型。

## 禁止事项

- 直接修改 `.env` 或 `llm_key_resolver.py` 来切换路由。
- 使用 `force` 绕过模型目录或健康检查。
- 切到已失效的备选 provider。
- 在切换建议中遗漏模型能力差距评估。

## 输出契约

- summary：切换结论。
- evidence：主 provider 失效证据 + 备选链健康检查结果。
- risks：质量下降、延迟变化、成本变化。
- next_actions：切换后监控、必要时回滚、key 轮换同步。
- requires_human：常规目录内切换为 false；密钥变更、强制绕过仍为 true。
