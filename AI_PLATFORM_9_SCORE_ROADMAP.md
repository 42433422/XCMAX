# XCMAX AI Platform 9-Point Roadmap

本文目标：把当前「chat + 意图路由 + 业务工具」升级为可对标 Dify/Coze 一代能力的 Agent 平台内核。路线图按当前代码模块映射改造任务、验收标准、预计工作量和风险点，避免继续堆业务路由、兼容垫片和展示层。

## 0. 当前判断

当前 AI 能力不是空白，已有 workflow planner、员工运行时、工具执行、轻量 RAG/向量、OCR、NeuroBus、Mod/员工商店和 Token 钱包。但这些能力分散在应用服务、路由、Mod SDK、工具注册和前端编排中，还没有形成统一 Agent Runtime。

当前更准确的定位：

| 维度 | 当前状态 | 主要问题 |
|---|---|---|
| Chat/LLM | 可用，支持 OpenAI-compatible/DeepSeek/Ollama 路径 | 主入口多，模型/路由/错误恢复不统一 |
| Planner | 有 PlanGraph、LLM 规划、tool probe、critic repair、fallback | 偏一次性生成计划，缺少可恢复 Run 状态机 |
| Tools | 有 workflow tools、employee tools、business_db 受控读写 | 工具 schema、权限、计费、审计、测试夹具不统一 |
| Agent | 有 employee agent loop 和 function calling | 还不是平台级 agent runtime，后台任务、暂停恢复、观察修复不足 |
| Memory | 有 user memory、vector memory、Memory v2 生命周期和来源治理 | 仍缺真实历史数据上的大规模误用/过期评测 |
| RAG | 有轻量 chunk/retrieve/citation、JSON 持久化 Dataset 文档问答、tenant/version/filter/rerank、版本 diff/回滚、受治理 rebuild queue、RBAC tenant scope、SQLite vector backend、pgvector backend 基础闭环 | 缺少更大规模评测 |
| Multimodal | 有 OCR、Excel 解析、文档模板识别 | OCR artifact 已可自主进入 Dataset/RAG 查询，Excel artifact 已可进入确认后业务入库；PDF/Office artifact 已可进入确认后 Office 导出；PDF 到业务写入、低置信字段校验 UI 仍未统一 |
| Observability/Eval | 有部分日志、metrics、NeuroBus 事件 | 缺少 AI 质量基准、trace、成本、任务完成率等硬指标 |
| Commercialization | 有 Mod/员工商店、Token 钱包、支付/权益 | 没有深入绑定每次模型/工具/员工调用 |

目标分数：从约 5.5-6/10 提升到 9/10。9 分不是功能列表堆满，而是做到：同一 Agent 内核能稳定规划、执行、观察、修复、记忆、检索、计费、审计，并且可被自动评测。

## 0.1 当前落地进度

截至 2026-06-19，已开始执行第一个可交付切片：

| 项目 | 状态 | 当前证据 |
|---|---|---|
| XCauto 平台模型配置 | 已完成基础接入 | `XCAUTO_API_KEY` / `XCAUTO_BASE_URL` / OpenAI SDK 风格 `OPENAI_BASE_URL=https://xiu-ci.com/v1` 均可解析到 `xcauto-account`；`LLM_PROVIDER=xcauto` / `LLM_ROUTING_ORDER=xcauto` 已映射到 `openai_compatible` 执行器 |
| AgentRun 数据结构 | 已完成内存版 | 新增 `FHD/app/application/agent_orchestrator/run_models.py` 和 `run_repository.py` |
| AgentOrchestrator v1 | 已完成最小闭环 | 新增 `FHD/app/application/agent_orchestrator/orchestrator.py`，支持 planner -> step -> tool event |
| 低风险工具自动执行 | 已完成最小闭环 | `business_db.read` / 低风险幂等节点可自动执行并写入 run events |
| 中风险工具确认门 | 已完成最小闭环 | `business_db.write` 等中风险节点进入 `waiting_user`，不直接执行副作用 |
| Observe/Repair/Retry 底座 | 已完成基础接入 | `AgentRun` step 已记录 `attempt_count/observations/repair_history`；低风险幂等步骤失败后可先按 plan/runtime `repair_overrides` 应用 deterministic 参数修复，必要时调用受控 LLM repair advisor 生成 `params_patch`，经 ToolSpec 校验、模型用量账本和钱包门禁后重试；多步 run 中后置步骤失败修复后会保留前置节点输出并继续完成，事件包含 `observation.recorded`、`step.llm_repair_requested`、`llm.completed`、`billing.recorded`、`step.repair_applied`、`step.retry_scheduled` |
| HTTP Run API | 已完成最小闭环 | 新增 `/api/agent/runs` 创建、列表、详情；已接入 `RouteRegistry` 和 `domain_registry.py` |
| AgentRun 持久化 | 已完成基础接入 | 新增 SQLAlchemy `agent_runs` 表和 repository；完整 run payload 可跨 repository 实例恢复 |
| Run Events API | 已完成基础接入 | 新增 `/api/agent/runs/{run_id}/events`，支持 `after_event_id` 增量读取 |
| 前端 Run Events 消费 | 已完成基础接入 | 新增 `agentRunsApi` 与 `useAgentRunEvents`；chat payload 带 `run_id` 时会拉取 events 并同步右侧任务面板 |
| 旧 Chat/SSE `run_id` 追踪 | 已完成基础接入 | 兼容 chat、batch、SSE `done.result` 和 `/api/ai/chat-unified*` alias 会写入 `AgentRun` 并返回 `run_id`；前端现有任务面板可继续按 run events 同步 |
| AIOPEN/Qclaw 外部 AI 网关追踪 | 已完成基础接入 | `/api/aiopen/openclaw/chat` 与旧 `/api/ai/qclaw/openclaw/chat` 已从裸代理升级为 `attach_chat_trace_run` observed AgentRun，成功/失败 payload 均会补 `run_id/agent_run_id`，并记录 `external_openclaw_chat` intent、source/channel/runtime_context |
| compat planner 前置 Run | 已完成基础接入 | `/api/ai/chat`、batch 和 SSE 主 planner 分支会在调用 legacy planner 前创建 `AgentRun`，把 `run_id/agent_run_id` 注入 runtime_context；planner 完成、超时、错误或等待 token 时收口同一个 run |
| Legacy `toolCall` 读工具接管 | 已完成低风险闭环 | 兼容 payload 里的 `products/customers/materials/shipment_records/business_db` 低风险幂等读动作会升级为真实 `AgentOrchestrator.start_run_from_plan`，记录 ToolCall、cost 和 tool events；中风险写入仍保留原确认/兼容路径 |
| Legacy planner 已执行工具审计 | 已完成基础接入 | `legacy_chat_adapter` 会记录本轮 function-calling 工具调用并随 `chat()` 返回；compat payload 跨 `asyncio.to_thread` 仍携带 `legacy_tool_records`，`chat_trace` 可转成 observed `AgentRun` ToolCall/events，不重复执行工具 |
| ToolSpecV2 核心执行契约 | 已完成基础接入 | 新增 `tool_spec.py`，从旧 registry 生成 schema/risk/permission/cost/output_schema/test_fixtures；`AgentToolExecutor` 执行前校验 input schema/拦截 raw SQL，并在工具返回后强制校验 output schema；`success=true` 的伪成功缺字段会被标记为 `output_schema_validation_failed`，`success=false` 的结构化失败保留原始错误，避免覆盖业务失败原因；`AgentOrchestrator` 以 ToolSpec 风险覆盖 planner 声明；`generate_office_document.execute`、`dataset_rag.ingest_document/query/diff_versions/rollback_version/rebuild_index/cancel_rebuild/delete_document`、`template_extract.extract` 和 AIOPEN MCP 工具已注册到统一 ToolSpecV2 schema/risk/cost/fixture 体系；所有 registry action 和 AIOPEN tool action 均可导出至少 1 个 fixture 并通过 input/output schema 校验，核心工具有业务化 output schema |
| ToolCall/cost 观测 | 已完成基础接入 | 新增 `ToolCall` run payload；每次 `AgentToolExecutor` 调用记录 `call_id/status/duration_ms/cost_units/permission`，run metadata/final_output 汇总 `tool_call_count` 与 `cost_units_total`，AIChat 响应同步返回 |
| AgentRun 预算门 | 已完成基础接入 | 新增 `agent_orchestrator/budget.py`；`AgentOrchestrator` 会从 plan/runtime 读取 `ai_cost_budget_units`，执行每个工具前按 ToolSpec `cost_units` 做 projected budget 判断，超预算直接生成 `budget.exceeded` 事件和可解释失败，不触发工具副作用 |
| LLM 调用 trace / 成本计量 | 已完成基础接入 | `AIConversationService.call_llm_api` 会在响应中附加 `_xcagi_trace`，记录 `provider_id/provider/model/prompt_tokens/completion_tokens/total_tokens/latency_ms/cost_units/billing_status`；普通 chat 响应同步返回 `llm_trace`，`chat_trace` 会把 trace 收口为 `AgentRun.llm_calls`、`llm.completed` 事件、`llm_cost_units_total` 与 `ai_cost_units_total`，NeuroBus roundtrip 使用真实 model 与 token_count |
| AI 用量账本 / 本地和市场钱包扣减 | 已完成基础接入 | `chat_trace` 会把 completed LLM call 写入 `infrastructure/billing/model_usage.py` 的 JSON usage ledger，按 `run_id/user_id/provider/model/tokens/cost_units` 形成幂等记录；已配置本地模型钱包时会真实扣减余额并产生 `billing.debited`，`MODEL_USAGE_WALLET_REQUIRED=1` 且余额不足时产生 `billing.insufficient_balance` 并让 run 可解释失败；`MODEL_USAGE_WALLET_BACKEND=market` 通过修茈市场 `/api/wallet/ai/preauthorize` + `/api/wallet/ai/settle` 完成真实预授权/结算，成功写 `market_wallet`，余额不足写 `billing.insufficient_balance`，市场扣款失败写 `billing.debit_failed`；已新增跨进程市场钱包样本，真实 uvicorn market 进程可完成工具失败场景下的 preauthorize/settle/refund 并验证市场流水；`/api/model-payment/usage` 可查询模型/工具/员工 usage entries、钱包快照和 `wallet_backend` |
| 工具/员工调用计费门 | 已完成基础接入 | `AgentOrchestrator` 在 ToolSpec 参数校验通过后、真正执行工具前调用 `record_tool_usage`，为 `ToolCall` 写入 `entry_type=tool_call`、`tool_id/action/call_id/permission/cost_units`、`usage_ledger` 和 `wallet_debit`；`employee.execute`、`business_db.write/read` 等工具会产生 `billing.recorded` 或 `billing.debited`，`MODEL_USAGE_WALLET_REQUIRED=1` 且余额不足时产生 `billing.insufficient_balance` 并阻断工具执行，不触发写库/员工副作用；已补 `refund_tool_usage`，工具执行失败后本地钱包会恢复余额并产生 `billing.refunded`，审计后端记录补偿，市场钱包会调用 `/api/wallet/ai/refund` 做已结算 hold 的幂等退款，失败时才记录 `billing.refund_pending` |
| 修茈市场 AI 钱包 Python 端点 | 已完成基础接入 | 市场 Python 支付模式新增 `/api/wallet/ai/preauthorize`、`/api/wallet/ai/settle`、`/api/wallet/ai/release`、`/api/wallet/ai/refund`，并为 `transactions` 补 `idempotency_key` 兼容列；`refund` 只允许对已结算 hold 退款，按 idempotency key 幂等，且拒绝超过已结算未退余额的重复退款；Java 支付模式仍由同路径 proxy 透传到 Java `WalletController` |
| RAG/citation trace | 已完成基础接入 | `chat_trace` 会把 chat payload 中的 `chunks/citations/rag_enabled` 收口为 `AgentRun.retrieval_calls` 和 `rag.retrieved` 事件，run metadata/final_output 汇总 `retrieval_call_count/retrieval_chunk_count/citation_count` |
| Dataset/RAG 文档生命周期 | 已完成 JSON + SQLite/pgvector vector 基础闭环 | 新增 `dataset_rag_app_service.py`；`knowledge_v1` 挂载 `/api/knowledge/v1/datasets/{dataset_id}/documents`、`query`、`status`、`delete`、`versions/diff`、`versions/rollback`、`index/rebuild`、rebuild job 查询和 cancel，生产 POST/DELETE route 已由 `dataset_rag.*` ToolSpecV2 工具进入 `AgentOrchestrator`，返回 `run_id/agent_run_id` 并记录 ToolCall/cost/permission；支持受控路径下文本/PDF/DOCX 入库、chunk、检索、deterministic answer 和 citation；PDF 入库使用 `pdfplumber`，DOCX 入库使用 `python-docx`，`file_path` 通过允许目录校验；支持 `tenant_id`、自动版本号/`version=latest`、metadata filter、lexical rerank、版本 diff、回滚生成新 latest 版本、embedding/index snapshot 和 rebuild job 元数据持久化；新增 `DatasetAccessContext`，service/route 可按 `dataset.read`、`dataset.write`、`dataset.admin` 强制 tenant scope，阻断跨租户 query/delete/rebuild job 访问和只读用户写入；rebuild 支持 queued/running/completed/failed/cancelled 状态、并发上限、queue position、queue summary、queued job cancel、失败重试和重载后 running job requeue；新增 `DatasetVectorSQLiteIndex` 和 `DatasetVectorPgIndex`，默认把 Dataset chunks/embeddings 同步到独立 SQLite vector backend，也可通过 `DATASET_RAG_VECTOR_BACKEND=pgvector` + `DATASET_RAG_PGVECTOR_DATABASE_URL` 切到 PostgreSQL/pgvector；query 优先从 vector backend 取 tenant/version/filter 候选，再用 Hybrid/Rerank 排序，status 暴露 backend path/chunk_count/sync_status/dimension；默认写入 app data 下 `dataset_rag/datasets.json` 和旁路 `*.vectors.sqlite`，也可用 `DATASET_RAG_STORE_PATH` / `XCAGI_DATASET_RAG_STORE_PATH` / `DATASET_RAG_VECTOR_INDEX_PATH` 指定，新的 service 实例可恢复 documents/chunks/index snapshot/rebuild jobs/vector index 并继续问答 |
| Memory reference trace | 已完成基础接入 | 新增 `MemoryReference` run payload；`chat_trace` 会把 `user_memory_rag_summary/user_memory_hits` 收口为 `AgentRun.memory_references` 和 `memory.recalled` 事件，run metadata/final_output 汇总 `memory_reference_count/memory_hit_count/memory_sources` |
| Memory v2 生命周期 | 已完成基础闭环 | `UserMemoryService` 新增 `memory_v2_records`，支持 `preference/entity/episodic` 三类记忆候选、pending -> active/rejected/deleted 状态、候选幂等、用户确认、纠错、删除、列表和摘要；确认 `preference` 记忆会同步旧 `preferences` API，纠错改 key 会清理旧 preference，删除/拒绝会撤销旧 preference，避免 planner/slot 填充使用污染记忆；候选写入新增 `source_policy/source_trust/governance_flags/requires_user_confirmation/eligible_for_planner`，可信来源进入 pending，未知缺证据来源降置信并标记 `needs_evidence`，`llm_guess/system_prompt/prompt_injection` 等阻断来源直接 rejected 且不能确认进入 planner；`/api/memory/v2*` 已提供 list/summary/candidates/confirm/reject/correct/delete，其中 mutation route 已由 `memory_v2.propose_candidate/confirm/reject/correct/delete` ToolSpecV2 工具进入 `AgentOrchestrator`，返回 `run_id/agent_run_id` 并记录 ToolCall/cost/permission；前端 `SettingsView` 已接入 Memory v2 确认台，可创建候选、筛选、确认、拒绝、修正和删除；已确认 active 记忆会格式化为 `MemoryV2` planner context，pending/rejected/deleted/blocked 不进入 prompt |
| AgentArtifact 基础接入 | 已完成基础接入 | 新增 `AgentArtifact` run payload；`AgentOrchestrator` 可从 `plan.metadata.artifacts` 和工具输出收集 artifact，`chat_trace` 可把显式 artifact、OCR、file_analysis、PDF/Office、Excel preview、生成文档下载 payload 标准化为 `artifact.attached` event；Excel/.db 导入和 `generate_office_document` run 会携带 artifact |
| Artifact -> Dataset/RAG 自动入库 | 已完成基础接入 | 新增 `agent_orchestrator/artifact_ingestion.py`；`chat_trace` 和 `AgentOrchestrator` 附加 artifact 后会 best-effort 写入 Dataset/RAG，支持 OCR 文本、PDF 文件、DOCX 文件、Excel preview/fields 等 inline text；成功写 `dataset.ingested` event、`dataset_ingests` metadata/final_output，失败写 `dataset.ingest_failed` 且不影响主 run；默认按 `dataset_id/rag_dataset_id` 入库，tenant 优先取 runtime/artifact 的 tenant/workspace，最后退到 `run.user_id` |
| AIOPEN REST/MCP/control route trace | 已完成基础接入 | `/api/aiopen/invoke` 已对每次真实工具调用创建 observed AgentRun，响应返回 `run_id/agent_run_id`，并以 `aiopen.<tool>` ToolCall 记录成本/权限；`/api/aiopen/mcp` 的 `tools/call` 在 JSON-RPC `result._meta` 暴露 run id，不破坏 MCP `content/isError` 协议结构；`/api/aiopen/keys|whitelist|config|control` 写入类控制路由已补 `aiopen_control_update` run，API key 只进响应、不进 AgentRun 明文 trace；旧 `/api/ai/qclaw/*` 控制面和 test-route smoke 已补 `qclaw_control_update/qclaw_route_smoke` run |
| 意图识别 AI route trace | 已完成基础接入 | `/api/ai/intent/test` 已补 observed AgentRun，保留原 `data.primary_intent/tool_key/slots` 响应结构，只新增顶层 `run_id/agent_run_id`，runtime_context 记录 `primary_intent/tool_key` |
| Excel 解析/分析 AI route trace | 已完成基础接入 | 旧 `/api/ai/parse-single`、`/api/ai/parse-products`、`/api/ai/analyze` 已补 observed AgentRun；响应只新增顶层 `run_id/agent_run_id`，不覆盖 legacy `data/items/chart_data` 结构，文件/文本分析会记录 `excel_data_analysis` runtime_context |
| 文件分析 AI route artifact trace | 已完成基础接入 | 旧 `/api/ai/file/analyze` route 已从裸 service 返回升级为 `attach_chat_trace_run` observed AgentRun，成功/失败分析结果都会补 `run_id/agent_run_id`；PDF/DOCX 等 `file_analysis` payload 会标准化为 AgentArtifact 并按 `dataset_id/tenant_id` 自动进入 Dataset/RAG |
| Kitten 报告/文档 AI route artifact trace | 已完成基础接入 | `/api/ai/kitten/financial/report` 已补 observed AgentRun 并在 JSON 响应返回 `run_id/agent_run_id`；`/api/ai/kitten/report/export`、`/api/ai/kitten/report/export-docx`、`/api/ai/kitten/document/generate` 保持下载 body 不变，通过 `X-Agent-Run-Id` 暴露 run，并把 Excel/Word 产物标准化为 `office_document` AgentArtifact |
| 审批 AI route decision trace | 已完成基础接入 | `/api/ai/config/approval` 保存、`/api/ai/approval/request`、`/api/ai/approval/approve`、`/api/ai/approval/reject` 已补 observed AgentRun，记录 `approval_route` channel、plan/request/node/tool/action runtime_context；只追踪写入/决策 route，避免 pending/config GET 轮询制造 run 噪音 |
| AI Assistant compat route trace | 已完成基础接入 | 旧 `ai_assistant.py` 的 `/api/generate`、`/api/purchase_units` 增删改、`/api/print/{filename}`、`/api/print/single_label`、`/api/tts` 已从裸副作用返回升级为 observed AgentRun；响应只新增顶层 `run_id/agent_run_id`，不改 nested `data` 契约，TTS 音频 base64 在 trace 中脱敏；`/api/ai/message/save` 会话写入也已补 `conversation_message_save` run |
| AIChat 显式低风险工具意图 | 已完成基础迁移 | `AIChatApplicationService` 中显式业务库 read 等低风险幂等 PlanGraph 已由 `AgentOrchestrator.start_run_from_plan` 接管执行并返回真实 `run_id` |
| Pro/普通动态工作流 AgentRun 接管 | 已完成基础迁移 | 非 agentic 且无审批要求的动态 PlanGraph 不再落回旧 `WorkflowEngine.run`：低风险幂等节点直接执行，中风险/非幂等节点进入同一个 `AgentRun` 等待确认，确认后继续并记录 ToolCall、cost 和 run events |
| Agentic Excel loop Run 追踪 | 已完成基础接入 | `WorkflowEngine` 的 agentic Excel loop 会先创建 `AgentRun` 并注入 `run_id/agent_run_id`，保留旧 LLM 单步决策能力，同时把执行结果转换为 AgentStep、ToolCall、Artifact 和 run events |
| 中风险确认继续 AgentRun | 已完成基础闭环 | `AgentOrchestrator.continue_run` 与 `/api/agent/runs/{run_id}/continue` 可将 `waiting_user` 步骤确认后继续执行；AIChat 中风险确认会返回同一个 `run_id` 并在用户回复“确认”后继续 |
| Excel/文件 deterministic workflow 接管 | 已完成真实 Run 闭环 | `.db` 文件导入与 Excel 规则入库已从直接写库升级为 `AgentOrchestrator.start_run_from_plan`：首轮返回 `waiting_user` + `run_id`，用户确认后同一个 run 执行 `unit_products_import.execute_import` / `excel_import.import_records`，并记录 tool events；旧 `/api/ai/sqlite/import_unit_products` route 已从直接 service 写库迁为中风险 AgentRun 确认门，确认前不触发导入副作用 |
| 员工 LLM 默认 XCauto | 已完成基础收敛 | `employee_runtime.agent_runner` 与 `mod_sdk.mod_employee_llm` 在无显式员工 provider 时使用统一 credentials；`XCAUTO_API_KEY` 会解析到 `xcauto/xcauto-account` 与 `https://xiu-ci.com/v1/chat/completions` |
| Eval Harness 最小基线 | 已完成基础接入 | 新增 `FHD/evals/agent_tasks.jsonl` 与 `FHD/evals/run_agent_eval.py`，离线覆盖工具自动执行/确认继续、usage ledger、钱包扣退、ToolSpecV2 output enforcement、XCauto trace、Dataset/RAG、Memory v2、多模态自主计划，以及 Excel vector/OCR/Business API/System maintenance/Dataset RAG/Memory v2/Products route/Products compat route/Customers route/Shipment records route/Shipment orders route/Print route/Materials route/Inventory route/Purchase route/Finance route/Tools execute/Template analyze/Excel skill/Label template/Document template route 的真实 AgentRun；`/api/templates/analyze` 样本会生成 `templates_analyze` run、执行 `template_extract.extract`、返回 `run_id` 并记录 `template_analysis` artifact；`/api/skills/analyze/excel`、`/api/skills/view/excel` 和 `/api/skills/generate-label-template` 样本会分别执行 `excel_analyzer.analyze`、`excel_toolkit.view`、`label_template_generator.execute` ToolCall；`/api/templates/create|update|delete` 样本会执行中风险 `document_template.create/update` 与高风险 `document_template.delete`，由 route 确认后继续；`/api/business/print/label|inventory/update|shipment/create` 样本会执行高风险 `business_event.print_label/inventory_update/shipment_create`，由 route 确认后继续；`/api/system/printer`、`/api/system/startup`、`/api/database/backup|restore` 和 `/api/performance/cache/*|optimize/reinitialize` 样本会执行 `system_maintenance.*`，由 route 确认后继续；`/api/knowledge/v1/datasets/*` 样本会执行 `dataset_rag.ingest_document/query/diff_versions/rollback_version/rebuild_index/cancel_rebuild/delete_document`，中高风险动作由 route 确认后继续；`/memory/v2/*` mutation 样本会执行 `memory_v2.propose_candidate/confirm/reject/correct/delete`，由 route 确认后继续；`/api/products/batch|{id}` 写入样本会执行 `products.*`，由 route 确认后继续；`/products/add|update|delete|batch-delete` 兼容写入样本会执行 `products.create/update/delete/batch_delete`，由 legacy compat route 确认后继续；`/customers` create/update/delete/batch-delete 样本会执行 `customers.*`，由 route 确认后继续；`/api/shipment/shipment-records/record` create/update/delete 样本会执行 `shipment_records.*`，由 route 确认后继续；`/api/shipment/generate|generate-batch|print` 样本会执行 `shipment_orders.generate/generate_batch/print`，由 route 确认后继续；`/api/shipment/orders/clear-shipment|set-sequence|reset-sequence|clear-all|{order_number}` 与 `/api/orders/set-sequence|reset-sequence|clear-all` 样本会执行 `shipment_orders.clear_shipment/set_sequence/reset_sequence/clear_all/delete`，由 route 确认后继续；`/api/print/printer-selection|document|label|test` 样本会执行 `print.save_printer_selection/print_document/print_label/test`，由 route 确认后继续；`/api/print/workflow/label-print/dispatch` 样本会执行 `print.workflow_label_dispatch`，由 route 确认后继续；`/api/materials` create/update/delete/batch-delete 样本会执行 `materials.create/update/delete/batch_delete`，由 route 确认后继续；`/api/inventory/*` 仓库/库位/入库/出库/调拨写入样本会执行 `inventory.*`，由 route 确认后继续；`/api/purchase/*` 供应商/订单/入库写入样本会执行 `purchase.*`，由 route 确认后继续；`/api/finance/transactions` create/update/delete 样本会执行 `finance.*`，由 route 确认后继续；runner 输出 `score/passed/failed/results`，当前 120/120 通过 |
| 回归测试 | 已完成针对性验证 | 已验证离线 Agent eval `120/120` 通过；新增多模态自主计划单测 `3` 项通过；ToolSpecV2 fixture/schema/runtime output 单测 `18` 项通过；Memory v2 route AgentRun 单测 `2` 项通过；Products route/compat AgentRun 单测 `2` 项通过（覆盖 8 个动作）；Customers route AgentRun 单测 `1` 项通过；Shipment records route AgentRun 单测 `1` 项通过；Shipment orders route AgentRun 单测 `1` 项通过（覆盖 8 个动作）；Print route AgentRun 单测 `2` 项通过（覆盖 5 个动作）；Materials route AgentRun 单测 `2` 项通过；Inventory route AgentRun 单测 `2` 项通过；Purchase route AgentRun 单测 `2` 项通过；Finance route AgentRun 单测 `1` 项通过；Memory v2 service + route 生命周期/旧 preference 同步/来源治理 `50` 项通过；Dataset RAG route AgentRun 单测 `7` 项通过；Dataset/RAG service + 旧 knowledge route 回归 `39` 项通过；Excel vector route AgentRun 单测 `2` 项通过，旧 Excel vector route 兼容回归 `15` 项通过；OCR route AgentRun 单测 `2` 项通过，Business API route AgentRun 单测 `4` 项通过，System maintenance route AgentRun 单测 `4` 项通过，Tools/Skills execute route AgentRun 单测 `3` 项通过，Template analyze route AgentRun 单测 `1` 项通过，Excel/Label skill route AgentRun 单测 `3` 项通过，Document template create/update/delete route AgentRun 单测 `3` 项通过，旧 product compat route 回归 `68` 项通过，旧 system maintenance/template 兼容回归 `38` 项通过，API smoke `12` 项通过；eval/multimodal/ToolSpec/Excel vector/OCR/Business API/System maintenance/Tools execute/Template analyze/Excel+Label skill/Document template route 聚焦组合 `44` 项通过；AIOPEN REST/MCP/OpenClaw/control/Qclaw compat + ToolSpecV2 组合 `40` 项通过；意图识别 route AgentRun 回归 `2` 项通过；legacy Excel SQLite import route + ToolSpec + AIChat 导入组合 `90` 项通过；Excel parse/analyze/file/import route AgentRun 组合 `22` 项通过；文件分析 route + PDF artifact Dataset/RAG 入库组合 `6` 项通过；Kitten 报告/文档 route AgentRun header/artifact 回归 `59` 项通过；审批写入/决策 route AgentRun 回归 `20` 项通过；AI Assistant compat + `/api/ai/message/save` route AgentRun 回归 `120` 项通过；customer service singleton/reset 兼容回归 `162` 项通过；Memory v2 前端 API 单测 `5` 项通过；Dataset/RAG service + SQLite/pgvector backend `15` 项通过；前端 `type-check:build` 和目标 ESLint 通过；`FHD/tests/test_application` + `FHD/tests/test_routes/test_agent_routes.py` 宽回归 `3374 passed, 6 skipped`；此前真实跨进程市场钱包扣退样本、Dataset/RAG service + knowledge route、旧 knowledge route/business mount/domain registry、FHD harness/chat trace/agent orchestrator/XCauto/model payment、route alias/AgentRun coverage、Memory v2 生命周期和旧 memory/vector 兼容组合均已通过；ruff 与 `git diff --check` 作为最终门禁 |

仍未完成：所有 AI route 强制进入 `AgentOrchestrator` 执行主链路、ToolSpecV2 全量迁移到每个工具的生产级 golden fixture/更细 cost policy、多模态 PDF 到业务写入/低置信字段校验 UI，以及工具/员工执行与权益钱包的更完整统一计费闭环。当前已迁移或可审计的关键路径包括 compat chat 前置 run、AIOPEN/Qclaw/意图识别/Excel parse/file/Kitten/审批/AI Assistant 兼容 route trace，`/api/excel/vector/ingest|query`、`/api/ocr/*`、`/api/business/ocr/recognize`、`/api/business/print/label`、`/api/business/inventory/update`、`/api/business/shipment/create`、`/api/system/printer`、`/api/system/startup`、`/api/database/backup|restore`、`/api/performance/cache/*|optimize/reinitialize`、`/api/tools/execute`、`/api/skills/execute`、`/api/templates/analyze`、`/api/templates/create|update|delete`、`/api/skills/analyze/excel`、`/api/skills/view/excel`、`/api/skills/generate-label-template`、`/api/knowledge/v1/datasets/*` POST/DELETE、`/memory/v2/*` mutation、`/api/products/batch|{id}` 写入、`/products/add|update|delete|batch-delete` 兼容写入、`/customers` create/update/delete/batch-delete、`/api/shipment/shipment-records/record` create/update/delete、`/api/shipment/generate|generate-batch|print`、`/api/shipment/orders/clear-shipment|set-sequence|reset-sequence|clear-all|{order_number}`、`/api/orders/set-sequence|reset-sequence|clear-all`、`/api/print/printer-selection|document|label|test`、`/api/print/workflow/label-print/dispatch`、`/api/materials` create/update/delete/batch-delete、`/api/inventory/*` 仓库/库位/库存流水写入、`/api/purchase/*` 供应商/订单/入库写入和 `/api/finance/transactions` create/update/delete 的真实 `AgentOrchestrator` 执行；其中模板分析已从 archive template analyzer 升级为 `template_extract.extract` ToolSpecV2 工具调用，模板创建/更新/删除已从 route 直连 compat CRUD 升级为 `document_template.create/update/delete` ToolSpecV2 工具调用并由显式 route 确认继续，业务 API 打印/库存/发货事件已从 route 直连 NeuroBus/domain 升级为高风险 `business_event.print_label/inventory_update/shipment_create` ToolSpecV2 工具调用并由内网业务 route 确认继续，系统维护/数据库/性能副作用 route 已从直连 service/cache/initializer 升级为 `system_maintenance.*` ToolSpecV2 工具调用并由显式维护 route 确认继续，Dataset/RAG 生产写入、查询、版本治理和索引维护 route 已从直连 service 升级为 `dataset_rag.*` ToolSpecV2 工具调用，Memory v2 记忆候选/确认/拒绝/修正/删除 route 已从直连 service 升级为 `memory_v2.*` ToolSpecV2 工具调用，产品批量创建/更新/删除 route 已从直连 service 升级为 `products.*` ToolSpecV2 工具调用，旧 products compat add/update/delete/batch-delete route 已从直连 PG/facade 写入升级为 `products.*` ToolSpecV2 工具调用，客户 create/update/delete/batch-delete route 已从直连 PG helper 升级为 `customers.*` ToolSpecV2 工具调用，出货记录 create/update/delete route 已从直连 service 升级为 `shipment_records.*` ToolSpecV2 工具调用，发货单生成/批量生成/打印和订单管理清空/序号/删除 route 已从直连 service 升级为 `shipment_orders.*` ToolSpecV2 工具调用，打印机选择/文档打印/标签打印/测试打印/工作流标签调度 route 已从直连 service 升级为 `print.*` ToolSpecV2 工具调用，原材料 create/update/delete/batch-delete route 已从直连 service 升级为 `materials.*` ToolSpecV2 工具调用，库存库位/仓库/入库/出库/调拨 route 已从直连 service 升级为 `inventory.*` ToolSpecV2 工具调用，采购供应商/订单/入库写入 route 已从直连 service 升级为 `purchase.*` ToolSpecV2 工具调用，财务交易凭证 create/update/delete route 已从直连 service 升级为 `finance.*` ToolSpecV2 工具调用，Excel/Label skill route 已从直接调用技能单例升级为 `excel_analyzer.analyze` / `excel_toolkit.view` / `label_template_generator.execute` ToolSpecV2 工具调用，均返回 `run_id` 并记录 ToolCall/cost。ToolSpecV2 体系已覆盖 `business_event.print_label/inventory_update/shipment_create`、`dataset_rag.ingest_document/query/diff_versions/rollback_version/rebuild_index/cancel_rebuild/delete_document`、`memory_v2.propose_candidate/confirm/reject/correct/delete`、`products.create/update/delete/batch_create/batch_delete`、`customers.create/update/delete/batch_delete`、`shipment_records.create/update/delete`、`shipment_orders.generate/generate_batch/print/clear_shipment/set_sequence/reset_sequence/clear_all/delete`、`print.print_document/print_label/test/save_printer_selection/workflow_label_dispatch`、`materials.create/update/delete/batch_delete`、`inventory.create_storage_location/update_storage_location/create_warehouse/update_warehouse/delete_warehouse/stock_in/stock_out/transfer`、`purchase.create_supplier/update_supplier/delete_supplier/create_order/update_order/approve_order/cancel_order/create_inbound`、`finance.create_transaction/update_transaction/delete_transaction`、`document_template.create/update/delete`、`system_maintenance.*`、`excel_analyzer.analyze`、`excel_toolkit.view/merged/styles/structure`、`label_template_generator.execute`、`excel_import.import_records`、`excel_vector_index.execute/query`、`generate_office_document.execute`、`ocr.request/recognize/extract/analyze/recognize_and_extract`、`template_extract.extract`、`unit_products_import.execute_import` 和 `aiopen.<tool>`；Eval Harness 目前 120 条最小离线样本，尚未覆盖模型漂移、更复杂的 LLM 多步 repair 和更多多模态入库误差样本；多模态自主计划目前覆盖 OCR artifact -> Dataset/RAG query、Excel artifact -> 业务入库、PDF artifact -> 确认后 Office 导出，尚未覆盖 PDF 到业务写入和低置信字段人工校验 UI。

## 1. 9 分定义

达到 9 分时，必须满足以下能力门槛：

1. 所有 AI 请求统一进入 `AgentOrchestrator`，而不是散落在 chat route、planner route、employee route、legacy compat route 中。
2. 每次任务生成 `AgentRun`，包含状态、步骤、工具调用、输入输出、失败原因、成本、审计事件。
3. 支持 `plan -> execute -> observe -> repair -> continue` 循环，失败后可恢复，不只是一次性 PlanGraph。
4. 工具注册表 v2 具备 JSON Schema、权限、风险级别、成本、超时、重试、审计、测试 fixture。
5. Memory v2 分为用户偏好、业务实体、任务过程三类，并能被 planner 显式引用。
6. Dataset/RAG 支持上传、解析、chunk、embedding、rerank、citation、版本、权限、删除/重建。
7. 多模态输入进入统一 ingestion pipeline：图片/PDF/Excel/Word/OCR 输出结构化 artifact，再交给 workflow。
8. 前端 Workflow 图与后端执行 DAG 同源，节点可查看输入输出、重试、跳过、等待人工确认。
9. Eval harness 至少覆盖意图、工具选择、任务完成率、幻觉率、人工接管率、成本/任务。
10. Token 钱包、员工商店、租户权限绑定每次模型调用、工具调用和员工运行。

## 2. 当前模块映射

| 能力区 | 当前模块 | 当前角色 | 主要缺口 |
|---|---|---|---|
| AI 入口/聊天 | `FHD/app/application/ai_chat_app_service.py`, `FHD/app/services/conversation/*`, `FHD/app/fastapi_routes/domains/conversation/*`, `FHD/frontend/src/composables/useChatOrchestration.ts` | Chat 主链路、动态 workflow 触发、SSE/前端聚合 | 入口分散，业务分支过多，run 状态不统一 |
| Planner/Workflow | `FHD/app/application/workflow/planner.py`, `engine.py`, `types.py`, `approval_gated_engine.py`, `risk_gate.py` | PlanGraph、LLM 规划、fallback、审批门 | 缺少持久化 run/node 状态机和持续 observe/repair |
| 工具执行 | `FHD/app/application/tools/workflow.py`, `FHD/app/services/tools_workflow_registered.py`, `FHD/app/services/tools_execution/registry.py`, `FHD/app/mod_sdk/planner_tools.py` | 业务工具和 Mod 工具调用 | schema/权限/计费/fixture/观测分散 |
| 员工运行时 | `FHD/app/application/employee_runtime/*`, `FHD/app/mod_sdk/employee_*`, `FHD/app/infrastructure/mods/employee_registry.py` | 员工包、agent loop、risk/workspace gate | 与主 workflow runtime 边界不清，缺少统一任务生命周期 |
| LLM Provider | `FHD/app/infrastructure/llm/*`, `FHD/app/ai_engines/*`, `FHD/app/services/deepseek_intent_service.py`, `FHD/app/services/intent_service.py` | OpenAI-compatible、DeepSeek、BERT/Rasa/intent | 多引擎冗余，LLM structured output 主链路不清晰 |
| Memory | `FHD/app/services/user_memory_service.py`, `FHD/app/application/user_memory_vector_app_service.py`, `FHD/app/infrastructure/persistence/user_memory_vector_store.py` | 用户动作、偏好、向量记忆、Memory v2 分层候选/确认/来源治理 | 仍缺真实历史数据上的过期、误命中和实体消歧评测 |
| RAG/Dataset | `FHD/app/infrastructure/rag/*`, `FHD/app/application/dataset_rag_app_service.py`, `FHD/app/fastapi_routes/knowledge_v1.py`, `FHD/app/infrastructure/persistence/*vector_store.py` | 轻量 chunk/retrieve/citation、JSON 持久化 dataset/document/chunk/query/delete、artifact 自动入库、tenant/version/filter/rerank、version diff/rollback、rebuild queue governance、RBAC tenant scope、SQLite vector backend、pgvector backend、embedding snapshot | 缺评测规模和更复杂多模态入库误差样本 |
| OCR/多模态 | `FHD/app/services/ocr_service.py`, `FHD/app/application/ocr_app_service.py`, `FHD/app/infrastructure/ocr/*`, `FHD/app/services/document_templates/analyzer.py`, `FHD/app/application/excel_vector_app_service.py`, `FHD/app/application/agent_orchestrator/multimodal_planner.py` | OCR、Excel/模板解析、向量化、artifact 入 AgentRun/Dataset；OCR route、Business OCR route、Excel vector route 和 `/api/templates/analyze` 已走 `AgentOrchestrator` + ToolSpecV2；模板分析通过 `template_extract.extract` 生成 `template_analysis` artifact；OCR artifact 可触发自主 Dataset/RAG 查询计划；Excel artifact 可触发确认后 `excel_import.import_records` 业务入库计划；PDF/Office/document artifact 可触发确认后 `generate_office_document.execute` 导出 Office 文档 | PDF 到业务执行、人工校验 UI 和低置信字段治理还不统一 |
| 事件/观测 | `FHD/app/neuro_bus/*`, `FHD/app/neuro_bus/neuro_application_instrumentation.py`, `FHD/metrics/*` | 事件总线、诊断、部分 metrics | 没有 AI trace/run metrics 标准 |
| 商业化 | `FHD/app/mod_sdk/*`, `FHD/app/infrastructure/payment/*`, `FHD/app/infrastructure/billing/*`, `FHD/app/fastapi_routes/model_payment.py` | Mod/员工、支付、权益、Token 钱包 | 成本/权限没有绑定到每次 AI run/tool call |
| API/UI | `FHD/app/fastapi_routes/*`, `FHD/frontend/src/views/*`, `FHD/frontend/src/components/*` | 路由和用户界面 | 多个展示态与执行态脱节，兼容路由多 |

## 3. 分阶段计划

### Phase 1: 收敛 AI 主入口

目标分数：6 -> 7。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| AgentOrchestrator v1 | `ai_chat_app_service.py`, `planner.py`, `employee_runtime/*`, `services/conversation/*` | 新增 `FHD/app/application/agent_orchestrator/`，统一 chat、workflow、employee、RAG、tool dispatch 入口 | 80% 以上 AI route 只调用 orchestrator；每次请求返回 `run_id`；旧入口只做 thin adapter | 8-12 人日 | 旧 chat 分支很多，容易改变现有用户路径 |
| Run/Step 数据模型 | `workflow/types.py`, `engine.py`, `neuro_bus/event_store.py` | 定义 `AgentRun`, `AgentStep`, `ToolCall`, `Artifact`, `RunEvent` | 每次 workflow/employee/tool 调用能查询 run 状态和节点日志 | 6-10 人日 | SQLite/Postgres 兼容、迁移成本 |
| API 收口 | `fastapi_routes/domains/conversation/*`, `fastapi_routes/domains/workflow/*`, `fastapi_routes/xcagi_compat*` | 新增 `/api/agent/runs`、`/api/agent/runs/{id}`、`/api/agent/runs/{id}/events` | 前端可用一个 run API 展示 chat/workflow/employee 进度 | 5-8 人日 | 兼容旧客户端和 SSE 事件格式 |
| 前端编排瘦身 | `useChatOrchestration.ts`, chat components | 前端不再推断过多 workflow 状态，只消费 run events | 现有 chat、pro mode、tool progress 仍通过类型检查和 smoke | 5-8 人日 | 当前前端聚合点复杂，容易引发类型爆炸 |

Phase 1 不做大规模功能新增，重点是把所有 AI 任务都变成可追踪 run。

### Phase 2: Tool Registry v2

目标分数：7 -> 7.5。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| 统一工具协议 | `application/tools/workflow.py`, `services/tools_workflow_registered.py`, `services/tools_execution/registry.py` | 定义 `ToolSpecV2`: name、description、input_schema、output_schema、risk、permission、cost、timeout、retry、idempotent | 所有 workflow tools 均能导出 JSON schema；schema 校验失败不会执行工具 | 8-12 人日 | 老工具参数形态不一致 |
| 权限/风险/审批统一 | `workflow/risk_gate.py`, `approval_gated_engine.py`, `employee_runtime/risk_gate.py`, `workspace_guard.py` | 抽出统一 `ToolPolicyEngine` | 写操作、外部 API、文件系统、数据库写入都有同一 gate 结果 | 5-8 人日 | 过严会挡住现有业务，过松没有平台价值 |
| 工具测试夹具 | `FHD/tests/*`, `services/tools_execution/*` | 每个核心工具提供 fixture 和 golden output | CI 可跑 `business_db.read/write`, Excel, OCR mock, employee list/execute, Mod tools | 6-10 人日 | 测试数据污染长-lived DB |
| 工具市场桥接 | `mod_sdk/*`, `infrastructure/mods/*` | Mod/员工包导出的工具自动注册为 ToolSpecV2 | Mod 工具可被 planner 选择、权限校验、计费、审计 | 8-12 人日 | Mod manifest 历史格式多 |

验收核心：planner 不再依赖散落的 Python dict 和业务分支，而是面向稳定 ToolSpecV2。

### Phase 3: Agent Runtime v2

目标分数：7.5 -> 8。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| Run 状态机 | `workflow/engine.py`, `employee_runtime/executor.py`, `neuro_bus/*` | 状态包括 queued/running/waiting_user/blocked/retrying/completed/failed/cancelled | 长任务可后台运行、查询、取消、恢复 | 10-15 人日 | 同步代码改异步/后台时边界复杂 |
| Plan-Execute-Observe-Repair | `planner.py`, `engine.py`, `agent_loop.py` | 每一步执行后写 observation，失败进入 deterministic repair 或受控 LLM repair advisor | 当前低风险幂等步骤已支持 deterministic 参数修复、LLM `params_patch` 修复，以及多步 run 中第二步修复后继续完成；目标态覆盖更复杂的 LLM 多步 repair、人工接管和恢复 | 8-12 人日 | LLM 修复可能引入不可控动作，必须受 policy、ToolSpec schema 和计费门禁限制 |
| 人工确认节点 | `approval_gated_engine.py`, shipment approval routes, frontend workflow UI | 将确认/审批建模为 first-class step | 写库、发消息、扣费、导出等可等待用户确认后继续 | 6-10 人日 | UI 与后端状态同步 |
| 多员工协作 | `employee_runtime/orchestrator.py`, `mod_sdk/employee_*` | 支持一个 run 中调多个 employee，并记录依赖 | “先分析 Excel，再交给报价员工，再写数据库”可端到端执行 | 8-12 人日 | 员工能力描述和工具权限需要标准化 |

验收核心：不是“LLM 调一个工具”，而是能执行可恢复多步任务。

### Phase 4: LLM-only 主链路与 Planner v2

目标分数：8 -> 8.2。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| 主链路去 Rasa 化 | `ai_engines/rasa/*`, `services/intent_service.py`, `services/deepseek_intent_service.py`, `normal_chat_dispatch.py` | Rasa/BERT 保留为 legacy fallback，主链路使用 LLM structured output | 新任务入口不依赖 Rasa；intent/tool selection 有 eval 通过率 | 5-8 人日 | 短指令和低成本路径可能变慢 |
| Structured output | `planner.py`, `infrastructure/llm/*` | 使用严格 JSON schema/repair parser 替代自由 JSON 提示 | invalid JSON 率低于 1%；schema error 可恢复 | 5-8 人日 | 不同 provider structured output 能力不一致 |
| Planner eval set | 新增 `FHD/tests/agent_eval/` 或 `FHD/evals/` | 建立 100-200 条真实任务样本，覆盖产品查询、Excel 入库、员工调用、RAG 问答、多模态 | 每次 CI 产出 intent/tool/plan 分数 | 6-10 人日 | 样本标注成本，模型漂移 |
| 成本/延迟策略 | `infrastructure/llm/providers/*`, billing/payment | simple intent 用小模型/规则，复杂任务用 planner 模型 | 平均延迟和成本有 dashboard；高成本模型调用有预算保护 | 5-8 人日 | 多模型路由会增加调试复杂度 |

验收核心：冗余引擎退到兼容层，LLM-only 不等于无规则，而是规则用于 safety/fast-path，不再分裂架构。

### Phase 5: Memory v2

目标分数：8.2 -> 8.4。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| 记忆引用审计 | `agent_orchestrator/run_models.py`, `agent_orchestrator/chat_trace.py` | 将用户记忆召回结果收口到 `AgentRun.memory_references` | 每次使用 `user_memory_rag_summary/user_memory_hits` 都生成 `memory.recalled` 事件和 hit/source 汇总 | 已完成基础接入 | 只记录引用，不等于完成记忆生命周期治理 |
| 记忆分层 | `user_memory_service.py`, `user_memory_vector_app_service.py`, `user_memory_vector_store.py` | 建立 `PreferenceMemory`, `EntityMemory`, `EpisodicMemory` | planner prompt 明确引用记忆来源和置信度 | 8-12 人日 | 记忆污染会导致错误自动化 |
| 写入策略 | conversation manager, agent run events | 从 run observation 自动抽取候选记忆，用户确认后持久化 | 用户可查看、删除、纠正记忆 | 6-10 人日 | 隐私与合规风险 |
| 业务实体记忆 | customer/product/material/shipment domain | 客户别名、产品型号、报价习惯、发货偏好进入 entity memory | 查询“上次那个客户”能命中正确实体并可解释 | 8-12 人日 | 实体消歧困难 |
| 记忆评测 | eval harness | 已有最小误用/污染源阻断样本；继续扩记忆命中、误命中、过期处理 | 记忆误用率低于阈值，失败可回滚 | 4-6 人日 | 缺真实历史数据 |

验收核心：记忆不能只是向量摘要，必须有生命周期、可解释引用和纠错机制。

### Phase 6: Dataset/RAG v1

目标分数：8.4 -> 8.7。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| Dataset 生命周期 | `infrastructure/rag/*`, `knowledge_v1.py`, vector stores | 新增 dataset/document/chunk/index 数据模型和 API | 上传、重建、删除、版本切换可用 | 10-15 人日 | 旧 SQLite/pgvector 环境差异 |
| 文档解析 pipeline | OCR、Excel、document_templates、uploads | PDF/Word/Excel/图片统一输出 `IngestionArtifact` | 每类文件解析结果可进入 RAG 或 workflow | 10-15 人日 | PDF/图片质量参差，依赖重 |
| Retrieval v2 | `hybrid_retriever.py`, vector stores | 增加 metadata filter、rerank、tenant 权限、citation source | RAG 回答必须带 chunk/source/version | 8-12 人日 | 性能与准确率平衡 |
| RAG eval | eval harness | 建立文档问答、引用准确率、拒答率测试 | 文档命中率、引用准确率、幻觉率可量化 | 6-10 人日 | 样本构造成本 |

验收核心：从轻量检索函数升级为产品级知识库。

### Phase 7: Multimodal Workflow

目标分数：8.7 -> 8.9。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| IngestionArtifact 标准 | `ocr_app_service.py`, `ocr_service.py`, `excel_vector_app_service.py`, template analyzer | 所有文件解析统一输出 artifact: type、fields、confidence、source spans、preview | OCR/Excel/PDF 解析可被 planner 作为输入选择工具 | 8-12 人日 | 旧接口返回格式多 |
| 图片/PDF 到工作流 | OCR routes, document routes, workflow planner | 用户上传图片/PDF 后，可自动进入“识别 -> 校验 -> 执行/入库/导出” | 当前已覆盖 OCR -> RAG 查询、Excel -> 确认后入库、PDF -> 确认后 Office 导出；目标态继续补产品图识别、发票/单据识别和低置信字段校验 | 12-18 人日 | 多模态误识别会造成业务写错 |
| 人工校验 UI | frontend upload/chat/workflow views | 低置信字段进入确认面板，高置信字段可自动填充 | 用户能改字段后继续同一个 run | 8-12 人日 | UI 状态复杂 |

验收核心：多模态不止“识别成功”，而是成为 Agent 可操作的结构化上下文。

### Phase 8: Observability, Eval, Commercialization

目标分数：8.9 -> 9。

| 改造项 | 当前模块 | 任务 | 验收标准 | 工作量 | 风险 |
|---|---|---|---|---|---|
| AI Trace | `neuro_bus/*`, metrics, run model | 每次 run 记录 prompt hash、model、tokens、cost、tool calls、latency、errors | 后台可按 run/user/tenant/model/tool 查询 | 8-12 人日 | 敏感信息脱敏 |
| Eval Harness | 新增 `FHD/evals/`, CI scripts | 任务完成率、工具选择率、RAG 引用率、人工接管率、成本 | CI 或 nightly 产出 AI score report | 8-12 人日 | 模型非确定性 |
| Token/权益计费闭环 | `payment/*`, `billing/*`, `model_payment.py`, `mod_entitlements.py` | 模型调用、工具调用、员工执行统一扣费/限额/审计 | 余额不足、越权、超预算均在 run 中可解释失败；当前已完成工具调用预算预判、模型/工具/员工 usage ledger、本地模型钱包扣减、修茈市场钱包实时预授权/结算/退款、工具/员工执行前钱包门禁、本地/审计/市场工具失败退款补偿、跨进程市场扣退样本，下一步补租户权益策略 | 8-12 人日 | 计费错误是高风险 |
| Admin 质量看板 | admin routes/frontend | 展示模型成本、成功率、失败 top、工具耗时、员工表现 | 管理员能看到 AI 能力是否变好 | 6-10 人日 | 指标口径需要稳定 |

验收核心：9 分平台必须能被观测、评测、计费和治理。

## 4. 优先级 Backlog

P0 先做，避免继续堆功能：

1. 已建 `FHD/app/application/agent_orchestrator/`，继续把 legacy route 迁入。
2. 已建 `AgentRun/AgentStep/ToolCall/AgentArtifact/RunEvent` 数据模型和存储端口，OCR/Excel/PDF/Office/生成文档下载 payload 已能产出 artifact；已建 JSON 持久化 Dataset/RAG 文档入库、PDF/DOCX citation QA、artifact 自动入库、tenant/version/filter/rerank、version diff/rollback、rebuild queue governance、RBAC tenant scope、SQLite/pgvector vector backend 和 embedding snapshot 持久化，下一步把更大规模评测和多模态误差样本接入 Dataset/RAG 生命周期。
3. `ai_chat_app_service.py` 的显式低风险工具意图、非 agentic 动态工作流、中风险确认继续、agentic Excel loop、Excel/文件导入写库路径已调用 orchestrator 或写入 observed AgentRun；兼容 payload 的低风险读类 `toolCall` 已由 trace 升级为真正 orchestrator run，普通版 `/api/ai/chat-unified*` alias、AIOPEN REST/MCP/OpenClaw/control route、旧 Qclaw 兼容控制/test-route、意图识别 route、Excel parse/analyze/file route、Kitten 报告/文档 route、审批写入/决策 route、AI Assistant compat 副作用 route 和 `/api/ai/message/save` 已补 run/artifact trace，legacy planner 已执行工具也能作为 observed ToolCall 进入 run 审计；下一步把旧 chat adapter 的自然语言主链路和多模态 workflow 继续从 trace/legacy 执行升级为真正 orchestrator run。
4. 把 `planner.py` 输出从直接执行前置为 `AgentRun` 计划节点。
5. 已把 `AgentToolExecutor -> execute_registered_workflow_tool` 包一层 ToolSpecV2 input 校验、raw SQL 拦截和 runtime output enforcement，并让所有 registry action 导出至少 1 个可校验 fixture；下一步把核心工具 fixture 升级为真实 golden output，并补齐更细的 cost policy。
6. 前端 `useChatOrchestration.ts` 已能消费 run events，下一步删除更多本地 workflow 状态推断。
7. 已让旧 chat/SSE 和 `/api/ai/chat-unified*` alias 返回 `run_id` 追踪，非流式、batch、SSE compat planner 已在调用前创建 run，并已接管低风险读类 `toolCall` 与 legacy planner 已执行工具记录；下一步将更多 planner 执行事件和普通 pro workflow 前置到同一个 orchestrator run。
8. 已建立 120 条最小离线 agent eval 样本并接入 pytest，覆盖 XCauto LLM trace、模型/工具/员工 usage ledger、本地和市场钱包扣退、PDF Dataset/RAG、Dataset governance/version/RBAC/rebuild queue/SQLite vector/pgvector、Memory v2 生命周期和来源治理、LLM repair、多步 repair、多模态 OCR/Excel/PDF 自主计划，以及 Excel vector/OCR/Business API/System maintenance/Dataset RAG/Memory v2/Products route/Products compat route/Customers route/Shipment records route/Shipment orders route/Print route/Materials route/Inventory route/Purchase route/Finance route/Tools execute/Template analyze/Excel+Label skill/Document template route 的真实 AgentRun。新增 Template analyze 样本验证 `/api/templates/analyze` 自动生成 `templates_analyze` run、执行 `template_extract.extract` ToolCall、返回 `run_id` 并记录 `template_analysis` artifact；新增 Excel/Label skill 样本验证 `/api/skills/analyze/excel`、`/api/skills/view/excel` 与 `/api/skills/generate-label-template` 自动生成 AgentRun，并执行 `excel_analyzer.analyze` / `excel_toolkit.view` / `label_template_generator.execute` ToolCall；新增 Document template 样本验证 `/api/templates/create|update|delete` 自动生成 AgentRun、route 确认继续并执行 `document_template.create/update/delete` ToolCall，其中删除为 high risk、非幂等；新增 Business API 样本验证 `/api/business/print/label`、`/api/business/inventory/update`、`/api/business/shipment/create` 自动生成高风险 AgentRun、route 确认继续并执行 `business_event.print_label/inventory_update/shipment_create` ToolCall；新增 System maintenance 样本验证 `/api/system/printer`、`/api/system/startup`、`/api/database/backup|restore`、`/api/performance/cache/*|optimize/reinitialize` 自动生成 AgentRun、route 确认继续并执行 `system_maintenance.*` ToolCall；新增 Dataset RAG 样本验证 `/api/knowledge/v1/datasets/*` 生产 POST/DELETE route 自动生成 AgentRun、route 确认继续并执行 `dataset_rag.*` ToolCall；新增 Memory v2 样本验证 `/memory/v2/*` mutation route 自动生成 AgentRun、route 确认继续并执行 `memory_v2.*` ToolCall；新增 Products 样本验证 `/api/products/batch|{id}` 写入自动生成 AgentRun、route 确认继续并执行 `products.batch_create/update/delete` ToolCall；新增 Products compat 样本验证 `/products/add|update|delete|batch-delete` 自动生成 AgentRun、legacy compat route 确认继续并执行 `products.create/update/delete/batch_delete` ToolCall；新增 Customers 样本验证 `/customers` create/update/delete/batch-delete 自动生成 AgentRun、route 确认继续并执行 `customers.create/update/delete/batch_delete` ToolCall；新增 Shipment records 样本验证 `/api/shipment/shipment-records/record` create/update/delete 自动生成 AgentRun、route 确认继续并执行 `shipment_records.create/update/delete` ToolCall；新增 Shipment orders 样本验证 `/api/shipment/generate|generate-batch|print` 自动生成 AgentRun、route 确认继续并执行 `shipment_orders.generate/generate_batch/print` ToolCall，并验证 `/api/shipment/orders/clear-shipment|set-sequence|reset-sequence|clear-all|{order_number}` 与 `/api/orders/set-sequence|clear-all` 订单管理路径执行 `shipment_orders.clear_shipment/set_sequence/reset_sequence/clear_all/delete` ToolCall；新增 Print route 样本验证 `/api/print/printer-selection|document|label|test` 和 `/api/print/workflow/label-print/dispatch` 自动生成 AgentRun、route 确认继续并执行 `print.save_printer_selection/print_document/print_label/test/workflow_label_dispatch` ToolCall；新增 Materials 样本验证 `/api/materials` create/update/delete/batch-delete 自动生成 AgentRun、route 确认继续并执行 `materials.create/update/delete/batch_delete` ToolCall；新增 Inventory 样本验证 `/api/inventory/*` 仓库/库位/入库/出库/调拨写入自动生成 AgentRun、route 确认继续并执行 `inventory.*` ToolCall；新增 Purchase 样本验证 `/api/purchase/*` 供应商/订单/入库写入自动生成 AgentRun、route 确认继续并执行 `purchase.*` ToolCall；新增 Finance 样本验证 `/api/finance/transactions` create/update/delete 自动生成 AgentRun、route 确认继续并执行 `finance.create_transaction/update_transaction/delete_transaction` ToolCall；已新增 ToolSpecV2 fixture/schema/runtime output 单测、Excel vector/OCR/Business API/System maintenance/Dataset RAG/Memory v2/Products/Products compat/Customers/Shipment records/Shipment orders/Print route/Materials/Inventory/Purchase/Finance/Tools+Skills execute/Template analyze/Excel+Label skill/Document template route AgentRun 单测和真实跨进程市场钱包扣费/退款 pytest 样本，后者启动 uvicorn market 进程并验证 `ai_preauth/ai_settle/ai_refund` 流水；下一步扩展更多工具选择、真实历史记忆误命中、复杂 LLM 多步 repair、PDF 到业务执行和低置信字段校验样本，作为每次改动的防回归门。

P1 做平台化：

1. Tool Registry v2 全量迁移。
2. Run 状态机支持后台、暂停、恢复、取消。
3. Memory v2 已有服务端候选/确认/纠错/删除基础闭环，active 记忆已接入 planner context，设置页已有确认/纠错 UI，候选来源治理和污染源阻断已进 eval，mutation route 已进入 `AgentOrchestrator` + `memory_v2.*` ToolSpecV2；下一步扩真实历史误命中/过期/实体消歧评测。
4. Dataset/RAG 生命周期。
5. 多模态 artifact 标准化。

P2 做商业闭环和规模化：

1. Token/权益/成本与 run 绑定。
2. Admin AI 质量看板。
3. Nightly eval + trend report。
4. Mod/员工市场按 ToolSpecV2 开放第三方扩展。

## 5. 验收测试矩阵

| 场景 | 输入 | 期望 |
|---|---|---|
| 产品查询 | “查七彩乐园 9803” | LLM/fast-path 选 `products.query`，带 keyword/model/unit；显式兼容 `toolCall` 会返回真实 `run_id`、ToolCall、cost_units 和 tool events |
| Excel 入库 | 上传 Excel 后说“加入数据库” | deterministic 捷径和多模态 Excel artifact 自主计划都必须返回 `run_id`，进入 `waiting_user`，确认后同一 run 执行 `excel_import.import_records` 写入 customers/products，并记录 artifact、tool events、ToolCall 和 cost_units；目标态继续补真实钱包扣费 |
| 员工调用 | “交给报价员工处理这个客户报价” | 先 `employee.list`，选/确认员工，执行 employee run |
| 业务写库 | “新增客户 A 并保存产品 B” | policy 判定中风险，等待确认后写库 |
| RAG 问答 | 上传 PDF 后问合同条款 | Dataset 检索、带 citation、无来源拒答 |
| 多模态 PDF 导出 | 上传 PDF 后说“生成 Word 摘要报告” | 自动生成 `multimodal_document_export` run，源 PDF artifact 进入 Dataset/RAG，`generate_office_document.execute` 进入 `waiting_user`，确认后同一 run 生成 Office artifact、记录下载地址和 ToolCall cost |
| OCR 工作流 | 上传产品图片并生成标签 | OCR artifact -> 字段确认 -> label/document tool |
| Office 文档生成 | “生成一份合同/报价单” | `generate_office_document` 进入 ToolSpecV2，中风险确认后执行，run 记录 Office artifact 和下载地址 |
| 记忆引用 | 询问“上次那个客户/偏好” | run 记录 `memory.recalled`、命中条目、来源和置信度摘要 |
| 失败恢复 | 工具参数缺失或 DB 暂不可用 | run 进入 repair/waiting_user/retrying，不丢状态 |
| 成本限制 | 余额不足执行复杂任务 | 当前工具预算不足会 `budget.exceeded` 且不发生副作用；模型调用已写入 usage ledger，本地模型钱包和修茈市场钱包均可扣减/余额不足失败；工具/员工调用会在执行前写入 usage ledger 并在钱包不足时阻断工具副作用；工具失败后本地和市场钱包会退款补偿；跨进程市场扣退样本已验证真实 HTTP 流水；目标态继续补租户权益策略 |
| Eval 基线 | `FHD/evals/agent_tasks.jsonl` | `FHD/evals/run_agent_eval.py` 离线输出 `score=1.0`；pytest 中 `test_agent_eval_harness_baseline_passes` 失败即阻断回归 |

## 6. 工作量汇总

粗估总工作量：约 150-230 人日。

| 阶段 | 工作量 |
|---|---:|
| Phase 1 主入口和 Run 模型 | 24-38 人日 |
| Phase 2 Tool Registry v2 | 27-42 人日 |
| Phase 3 Agent Runtime v2 | 32-49 人日 |
| Phase 4 Planner/LLM-only/eval | 20-34 人日 |
| Phase 5 Memory v2 | 26-40 人日 |
| Phase 6 Dataset/RAG | 34-52 人日 |
| Phase 7 Multimodal Workflow | 28-42 人日 |
| Phase 8 Observability/Commercialization | 30-46 人日 |

并行建议：Phase 1-3 必须串行优先完成；Phase 5-8 可以在 Run/ToolSpec 稳定后分支并行。

## 7. 主要风险与控制

| 风险 | 表现 | 控制方式 |
|---|---|---|
| 继续堆路由 | 新能力继续落在 `fastapi_routes/*` 或 `ai_chat_app_service.py` | 新 AI 能力必须先进 orchestrator；路由只做 DTO/鉴权/响应 |
| Planner 失控 | LLM 生成危险工具调用或伪造参数 | ToolPolicyEngine + schema validation + human confirmation |
| 记忆污染 | 错误记忆导致后续任务自动犯错 | 候选记忆需确认；记忆有来源、置信度、过期和删除 |
| RAG 幻觉 | 无来源回答或引用错误 | citation 强制、无命中拒答、RAG eval |
| 多模态误识别 | OCR/PDF 字段错误后入库 | 低置信字段必须人工确认，高风险写操作必须审批 |
| 兼容迁移破坏现有用户路径 | 老 chat/pro mode/desktop/admin 失效 | thin adapter、灰度开关、保留旧 API smoke |
| 成本失控 | 多步任务反复调用大模型 | budget per run、模型路由、max repair count、token dashboard |
| SQLite/Postgres 差异 | vector/pgvector 或迁移失败 | RECOVERABLE_ERRORS 降级、双后端测试、显式 migration |

## 8. 建议代码落点

新增模块：

```text
FHD/app/application/agent_orchestrator/
  __init__.py
  orchestrator.py
  run_models.py
  run_repository.py
  run_events.py
  planner_adapter.py
  tool_executor.py
  memory_context.py
  artifacts.py

FHD/app/application/tools_v2/
  spec.py
  registry.py
  policy.py
  fixtures.py

FHD/app/application/datasets/
  dataset_service.py
  ingestion_pipeline.py
  document_parser.py
  retrieval_service.py

FHD/evals/
  agent_tasks.jsonl
  rag_tasks.jsonl
  run_eval.py
```

改造入口：

| 旧入口 | 改造方向 |
|---|---|
| `ai_chat_app_service.py` | 保留 chat DTO 和兼容逻辑，复杂分支迁入 orchestrator |
| `application/workflow/planner.py` | Planner 成为 orchestrator 的 plan adapter，不直接承担所有业务分支 |
| `application/tools/workflow.py` | 工具实现保留，注册和执行迁到 ToolSpecV2 |
| `services/tools_workflow_registered.py` | 迁为 legacy adapter，逐步导出 ToolSpecV2 |
| `employee_runtime/*` | 成为 AgentRuntime 的 employee executor |
| `infrastructure/rag/*` | 成为 Dataset/Retrieval 的底层组件 |
| `useChatOrchestration.ts` | 从“推断状态”改成“渲染 run events” |

## 9. 第一个可交付切片

建议第一个 PR 不超过 10-12 人日，目标是打通最小 AgentRun 闭环：

1. `AgentRun` 内存/SQLite repository。
2. `/api/agent/runs` 创建 run。
3. Orchestrator 调用现有 planner 生成 PlanGraph。
4. 执行一个低风险工具，如 `products.query` 或 `employee.list`。
5. 每一步写 run event。
6. 前端或 smoke 脚本能查询 run 状态。
7. 新增最小 eval：产品查询、员工列表、业务 DB 读取三条样本。

完成后才继续扩 ToolSpecV2、Memory v2、Dataset/RAG。

## 10. 不做清单

短期不做：

1. 不重写所有路由。
2. 不删除 Rasa/BERT，只从主链路降级为 legacy fallback。
3. 不先做漂亮 Workflow UI，先保证后端 DAG/run 真实可执行。
4. 不把 RAG 做成只有一个问答接口，必须有 dataset/document/chunk 生命周期。
5. 不让 Token 钱包只停留在页面展示，必须绑定 run/tool/model cost。
