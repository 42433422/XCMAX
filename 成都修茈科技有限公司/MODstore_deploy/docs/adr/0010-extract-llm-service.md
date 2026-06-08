# ADR 0010：抽出独立 LLM 服务评估

## 状态

提议

## 背景

`LlmChatClient` / `services/llm.py` 已为进程内默认实现；随着调用量与模型供应商增多，需评估拆出独立 LLM 微服务。

## 决策（草案）

- **表面 API**：保留 `LlmChatRequest` / `LlmChatResponse` 与 `chat` / `chat_stream`；HTTP 实现映射到 `/v1/chat` 等价端点。
- **配置**：`MODSTORE_LLM_SERVICE_URL` + mTLS 或静态 Bearer；超时与重试对齐 `llm_chat_proxy`。
- **HttpLlmChatClient**：在 `services/llm.py` 旁新增 `services/llm_http.py`，通过 `set_default_llm_client` 切换。
- **回滚**：环境变量关闭 HTTP 客户端即回退 `InProcessLlmChatClient`。
- **灰度**：按 `user_id` 百分比或租户维度路由到 HTTP 实现；配合 `services/_circuit_breaker.py` 熔断。

## 后果

- 需同步发布配额 / BYOK 解析策略（可暂由 BFF 代理）。
