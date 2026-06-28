# skill-model-cost-comparison

职责：维护主流 LLM 价格表，按任务类型推荐性价比方案，含国产便宜/免费 LLM 调研。

## 适用场景

- 新员工入职：根据其任务复杂度推荐默认模型。
- 模型选型评审：当某员工 token 成本异常时，重审其模型路由。
- 国产 LLM 调研：定期调研 DeepSeek/通义/智谱/硅基流动免费层与价格变化。

## 标准流程

1. 调 `compare_model_prices` 拉本地价格表（来源：`MODstore_deploy/modstore_server/llm_price_table.json` 或同类配置）。
2. 检查价格表新鲜度：
   - `updated_at` 超过 7 天 → 重新调研主流 provider 公开价格页。
3. 按任务类型分类推荐：
   - **简单任务**（分类、抽取、翻译、格式化）：DeepSeek-Chat、通义 qwen-turbo、智谱 glm-4-flash、硅基流动免费层。
   - **中等推理**（多轮对话、工具调用、RAG）：DeepSeek-Reasoner、通义 qwen-plus、智谱 glm-4。
   - **复杂推理**（代码生成、数学证明、长链推理）：DeepSeek-Reasoner-R1、Claude Sonnet、GPT-4o。
   - **离线场景**（隐私/无网络）：Ollama 本地模型（qwen2.5、deepseek-r1 蒸馏版）。
4. 输出四维度对比：

```json
{
  "task_type": "中等推理",
  "recommendations": [
    {
      "model": "deepseek-reasoner",
      "price_input_cny_per_mtok": 4.0,
      "price_output_cny_per_mtok": 16.0,
      "latency_p50_ms": 2200,
      "quality_score": 8.5,
      "free_quota_per_day": 0
    },
    {
      "model": "qwen-plus",
      "price_input_cny_per_mtok": 0.8,
      "price_output_cny_per_mtok": 2.0,
      "latency_p50_ms": 1800,
      "quality_score": 8.0,
      "free_quota_per_day": 100000
    }
  ],
  "pick": "qwen-plus",
  "rationale": "免费额度内零成本，质量差距 0.5 可接受，延迟更优"
}
```

## 优先级原则

按以下顺序推荐：

1. 国产便宜/免费 LLM（DeepSeek / 通义 / 智谱 / 硅基流动免费层）。
2. OpenAI 兼容渠道（如 OpenRouter 中转的便宜模型）。
3. 才考虑昂贵模型（Claude / GPT-4o 原生 API）。

## 禁止事项

- 用过期价格表给出推荐。
- 隐瞒免费额度信息。
- 在月度成本报告中漏算汇率折算。

## 输出契约

- summary：推荐结论与理由。
- evidence：四维度对比表 + 价格表 `updated_at`。
- risks：免费额度耗尽风险、模型下线风险、价格变动风险。
- next_actions：是否更新 `llm_key_resolver.py` 中的路由策略、是否需要 admin 审批。
- requires_human：路由策略变更需人工确认。
