# AI 工具链完善 · 批次 A：可信 AI 三件套 — 设计文档

> 日期：2026-07-16
> 状态：已批准（用户确认）
> 所属批次：AI 工具链 A→B→C→D 全量完善的第 1 批

---

## 1. 背景与目标

### 1.1 背景

项目评估（2026-07-16）确认 AI 内核（Agent Orchestrator / ReAct / RAG / 审批门控）已达企业级，但外围工具链与头部平台（Dify/Langflow/Langfuse 生态）存在明显差距。盘点出的 10 项差距按「杠杆 ÷ 单人工作量」分为四批：

- **批次 A（本 spec）**：LLM Observability 标准化 + Structured Output 自动修复 + Guardrails 全链路
- 批次 B：Eval Pipeline 强化 + Cost 精细归因 + Model Router 智能化
- 批次 C：RAG 混合检索 + rerank + 效果评估
- 批次 D：可视化编排 IDE + Fine-tuning/模型管理

### 1.2 批次 A 目标

为全部 LLM 调用装上「可信三件套」，使任意一次 LLM 调用：

1. **可观测**——自动生成符合 OTel GenAI semantic conventions 的 span，本地 JSONL 持久化，可查询、可导出；
2. **可防护**——输入经 prompt 注入检测与敏感词检查，输出经敏感词过滤，拦截留痕可审计；
3. **可自愈**——结构化输出经 schema 校验，失败自动带错误反馈重试，修复过程全程留痕。

### 1.3 已确认决策

| 决策点 | 结论 |
|---|---|
| 执行顺序 | A→B→C→D 全部执行，每批独立可用 |
| Observability 方案 | OTel GenAI 语义标准（自研实现，非强依赖 SDK） |
| Span 存储 | 本地 JSONL + 管理查询 API + 可选 OTLP 导出；无内置 UI |
| Guardrails 范围 | 仅注入检测 + 敏感词（不做 PII/内容审查/token 限额） |
| 架构方案 | 方案 1：registry 层统一包裹（InstrumentedProvider 装饰器） |

---

## 2. 现状基线（代码实测）

| 事实 | 位置 |
|---|---|
| 所有卫星 LLM 调用统一入口 | `FHD/app/infrastructure/llm/invoke.py::chat_completion_openai_format` |
| Provider 解析与路由 | `FHD/app/infrastructure/llm/providers/registry.py::get_active_provider` |
| Provider 协议（chat_completion） | `FHD/app/infrastructure/llm/providers/base.py::LLMProvider` |
| 现有 tracer（内存 span，可选 OTel 委托） | `FHD/app/neuro_bus/tracer.py`（trace_id 经 ContextVar 传播） |
| OTel 依赖已在生产 requirements | `FHD/requirements.txt` L48-50（api/sdk/otlp ≥1.24） |
| jsonschema 仅在 dev 依赖 | `FHD/deploy/requirements-dev.txt` L6 → 生产端复用轻量校验 |
| 现有轻量 schema 校验（可复用） | `FHD/app/application/agent_orchestrator/tool_spec.py::_validate_schema_payload` |
| 待迁移的高风险裸解析点 | `app/services/deepseek_intent_service.py:199`、`app/services/tools_execution/order_parser.py:402` |
| 流式 SSE 为独立链路（本批不覆盖） | `app/services/conversation/api.py` |

---

## 3. 架构设计

### 3.1 总体结构

```
业务代码 → invoke.chat_completion_openai_format
         → registry.get_active_provider
              ↓ 返回 InstrumentedProvider（新增装饰层，实现 LLMProvider Protocol）
              ├─ ① genai_telemetry.start_span()  先开 span（拦截也需留痕）
              ├─ ② guardrails.check_input()      拦截 → span 记 blocked + 返回 None
              ├─ ③ 内部 provider.chat_completion() 真实调用
              ├─ ④ guardrails.check_output()     脱敏 / 拦截
              └─ ⑤ span.finish() → trace_store 队列 → JSONL 落盘（+OTLP 双写）
```

**包裹点选择 registry 而非 invoke**：所有经 `get_active_provider` 拿 provider 的调用方（invoke、orchestrator、任何卫星代码）自动全覆盖，业务代码零改动。

### 3.2 新增文件清单

| 文件 | 职责 |
|---|---|
| `FHD/app/infrastructure/llm/genai_telemetry.py` | GenAI span 生成、属性规范、neuro_bus trace_id 桥接、采样 |
| `FHD/app/infrastructure/llm/trace_store.py` | JSONL 日轮转持久化、保留期清理、异步 flush 队列、OTLP 双写 |
| `FHD/app/infrastructure/llm/guardrails.py` | 注入检测（规则引擎）、敏感词加载/热更新、输入输出检查 |
| `FHD/app/infrastructure/llm/structured_output.py` | `complete_structured()`：提取→校验→修复重试循环 |
| `FHD/app/infrastructure/llm/instrumented_provider.py` | `InstrumentedProvider` 装饰器（组合以上三组件） |
| `FHD/config/guardrails/sensitive_words.txt` | 敏感词配置（支持 mtime 热更新） |
| `FHD/app/fastapi_routes/domains/` 新增 `genai_traces.py` | 管理查询 API |

### 3.3 修改文件清单（最小化）

| 文件 | 改动 |
|---|---|
| `providers/registry.py` | `get_active_provider` 返回前包 `InstrumentedProvider`（env 开关控制） |
| `app/services/deepseek_intent_service.py` | 裸 `json.loads` → `complete_structured()` |
| `app/services/tools_execution/order_parser.py` | 裸 `json.loads` → `complete_structured()` |
| 路由注册处 | 注册 `genai_traces` 管理路由（遵循路由注册 golden 测试规则） |

---

## 4. 组件 1：GenAI Telemetry

### 4.1 Span 属性规范

对齐 OTel GenAI semantic conventions（v1.28+）：

| 属性 | 来源 | 说明 |
|---|---|---|
| `gen_ai.operation.name` | 固定 `"chat"` | 操作类型 |
| `gen_ai.system` | provider.provider_id | deepseek / openai / ollama… |
| `gen_ai.request.model` | 解析后的模型名 | |
| `gen_ai.request.temperature` / `gen_ai.request.max_tokens` | 调用参数 | |
| `gen_ai.response.finish_reasons` | 响应 choices | |
| `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` | usage 字段（缺失时用 token_estimator 估算） | |
| `xcagi.profile` | invoke 的 profile 参数 | default / modstore… |
| `xcagi.caller` | 调用栈推断的模块名 | 归因用 |
| `xcagi.tenant_id` | request 上下文（有则） | 多租户归因 |
| `xcagi.cost_usd` | 由 model+token 经费率表估算（批次 B 升级为精细归因） | |

消息内容：默认只记 `len` + `sha256`；`XCAGI_GENAI_TRACE_CAPTURE_CONTENT=1` 时记全文（截断 4KB）。

### 4.2 与 neuro_bus tracer 桥接

- 读取 `app.neuro_bus.tracer.current_trace` ContextVar；存在则作为 parent trace_id，LLM span 挂到业务链路
- 两系统不合并，仅靠 trace_id 互联；neuro_bus 未启用时 GenAI span 自成 root

### 4.3 存储（trace_store）

- 路径：非桌面 `logs/genai_traces/trace-YYYY-MM-DD.jsonl`；桌面端走 `%APPDATA%\XCAGI\logs\genai_traces\`（遵循项目桌面路径约定）
- 格式：一行一个 span JSON（append-only）
- 保留：默认 14 天，`XCAGI_GENAI_TRACE_RETENTION_DAYS` 可调；启动时清理过期文件
- 写入：内存队列 + 后台 task flush（每 1s 或满 100 条）；LLM 链路零阻塞；写入异常 fail-open + warning
- 采样：`XCAGI_GENAI_TRACE_SAMPLE_RATE`（默认 1.0）；**错误 span 与 guardrail 拦截 span 永远记录**

### 4.4 OTLP 导出

- `XCAGI_OTLP_ENDPOINT` 非空时启用，经 `opentelemetry-exporter-otlp`（已在 requirements）双写
- 端点不可达：本地 JSONL 不受影响，导出 skip + 周期 warning

### 4.5 查询 API

`GET /api/admin/genai/traces`（复用 admin 认证）

参数：`trace_id` / `model` / `status` / `from` / `to` / `has_guardrail_block` / `limit`（≤500）
响应：span 列表（按 start_time 倒序）+ `total`；日轮转文件内顺序扫描，超窗早退。

---

## 5. 组件 2：Guardrails

### 5.1 注入检测（纯规则、零依赖）

规则集（每条含 id / pattern / weight）：

| 类别 | 示例模式 |
|---|---|
| 指令覆盖 | `ignore (all|previous) instructions`、`忽略(以上|之前|所有)(指令|指示)` |
| system prompt 套取 | `(reveal|show|print) (your|the) (system prompt|instructions)`、`输出你的提示词` |
| 角色越狱 | `you are now (DAN|jailbreak)`、`现在你是没有限制的` |
| 协议分隔符注入 | `<\|im_start\|>`、`<\|endoftext\|>`、`[INST]`、`<<SYS>>` |
| 编码绕过 | 高熵 base64/hex 段（长度 >120 且解码后命中上述模式） |

评分：命中规则 weight 求和 → 归一化 0–1。
动作：`score ≥ XCAGI_GUARDRAILS_INJECTION_THRESHOLD`（默认 0.7）→ 拦截；0.4–0.7 → 记录放行；<0.4 → 放行。

### 5.2 敏感词

- 配置：`config/guardrails/sensitive_words.txt`（一行一词，支持 `#` 注释）
- 热更新：mtime 变化时重载，无需重启
- 输入命中 → 拦截；输出命中 → `***` 脱敏 + 记录（`XCAGI_GUARDRAILS_OUTPUT_MODE=strict` 时拦截）

### 5.3 失败策略与审计

- guardrail 自身异常：**fail-open** + error log（绝不阻断业务）
- 拦截决策：严格执行；返回 None（符合 invoke 现有 `dict | None` 契约），调用方走既有 None 降级
- 审计：每次检查写 span event（`guardrail.rule_id` / `guardrail.score` / `guardrail.action`），拦截 span 强制落盘

---

## 6. 组件 3：Structured Output Repair

### 6.1 API

```python
async def complete_structured(
    messages: list[dict[str, str]],
    *,
    schema: dict,
    max_repairs: int = 2,
    profile: str = "default",
    temperature: float = 0.3,
) -> StructuredResult
```

`StructuredResult`：`data`（校验通过的 dict）、`attempts`、`repaired`（是否经过修复）、`trace_id`。

### 6.2 流程

1. 经 invoke 调用（自动获得 telemetry + guardrails）
2. JSON 提取：容忍 ```` ```json ```` fence、首尾废话（取首个 `{` 至末个 `}` 平衡切片）
3. 轻量 schema 校验：复用 tool_spec_data 同款 `_validate_schema_payload`（零新增依赖）
4. 失败 → 修复 prompt（原始输出 + 逐条校验错误 + 「只返回修正后的 JSON」）→ 重试 ≤ `max_repairs` 次；每次 attempt 记 span event（`attempt`、`error_count`、`repair_success`）
5. 终败 → 抛 `StructuredOutputError(attempts, last_errors, last_raw)`，调用方负责降级

### 6.3 本批迁移点

- `app/services/deepseek_intent_service.py:199`（意图识别，错误影响全链路）
- `app/services/tools_execution/order_parser.py:402`（订单解析，直接影响业务写入）

其余 `json.loads(content)` 裸解析点列入 follow-up 清单，渐进迁移，不在本批。

---

## 7. 配置项（全部 env，遵循项目风格）

| env | 默认 | 说明 |
|---|---|---|
| `XCAGI_GENAI_TRACE_ENABLED` | `1` | telemetry 总开关 |
| `XCAGI_GENAI_TRACE_SAMPLE_RATE` | `1.0` | 采样率（错误/拦截强制记录） |
| `XCAGI_GENAI_TRACE_RETENTION_DAYS` | `14` | JSONL 保留天数 |
| `XCAGI_GENAI_TRACE_CAPTURE_CONTENT` | `0` | 是否记录消息全文 |
| `XCAGI_OTLP_ENDPOINT` | 空 | 非空启用 OTLP 双写 |
| `XCAGI_GUARDRAILS_ENABLED` | `1` | guardrails 总开关 |
| `XCAGI_GUARDRAILS_INJECTION_THRESHOLD` | `0.7` | 注入拦截阈值 |
| `XCAGI_GUARDRAILS_OUTPUT_MODE` | `mask` | mask / strict |
| `XCAGI_STRUCTURED_OUTPUT_MAX_REPAIRS` | `2` | 修复重试上限 |

---

## 8. 错误处理矩阵

| 场景 | 行为 |
|---|---|
| guardrail 模块异常 | fail-open + error log |
| trace 写入异常 | fail-open + warning |
| OTLP 端点不可达 | 本地 JSONL 不受影响，导出 skip |
| 注入/敏感词拦截 | invoke 返回 None + span 记 `guardrail.blocked=true` |
| structured output 终败 | 抛 `StructuredOutputError`，调用方降级 |
| 敏感词配置缺失/为空 | 视为空词表，仅注入检测生效 |

---

## 9. 测试策略（遵循覆盖率六条铁律）

1. **三组件独立单测**（fake provider，零网络，可独立运行）：
   - telemetry：属性完整性、采样、桥接 trace_id、内容脱敏开关
   - trace_store：日轮转、保留期清理、flush 队列、OTLP 降级
   - guardrails：20+ 已知注入样本必须拦截；30+ 正常业务话术（发货单/考勤/微信场景）不误拦；敏感词热更新
   - structured_output：坏 JSON→修复→成功全循环；max_repairs 耗尽；fence/废话容忍
2. **集成测试**：registry 包裹生效（fake provider 经 registry 取出后被装饰）；拦截链路端到端；span 落盘可查（调查询 API）
3. **迁移点回归**：deepseek_intent_service / order_parser 既有测试全绿 + 新增修复路径用例
4. **覆盖率**：新增代码行覆盖 ≥90%，分支 ≥85%，不降低全库 floor（89 行/85 分支）
5. **guard-temp-scripts / ruff / mypy / 路由 golden 测试** 全绿

---

## 10. 验收标准

- [ ] 任意经 registry 的 LLM 调用产生符合 §4.1 属性表的 span，JSONL 落盘可查询
- [ ] 注入样本集 100% 拦截，业务话术误报率 ≤3%
- [ ] `complete_structured` 对可修复坏 JSON 修复成功率（构造集）≥90%
- [ ] 全部新增 env 有文档默认值，未配置时行为 = 现状（向后兼容）
- [ ] 全量测试绿、覆盖率 floor 不降、CI 流水线绿
- [ ] 查询 API 经 admin 认证，未认证返回 401

---

## 11. 明确不做（范围外）

- 流式 SSE 路径（`conversation/api.py`）的 telemetry/guardrails → follow-up
- PII 脱敏、输出内容审查、token 限额熔断（用户未选，后续可单独立项）
- 可视化 trace UI（仅查询 API）
- 全部裸 `json.loads` 点迁移（本批只移 2 个高风险点）
- Cost 精细归因（批次 B 范围，本批仅埋 `xcagi.cost_usd` 估算字段）

## 12. 与后续批次的衔接

- 批次 B 的 Cost 归因直接消费本批 span 中的 `gen_ai.usage.*` + `xcagi.cost_usd`
- 批次 B 的 Model Router 决策依据可从本批 trace 数据（延迟/失败率/成本）训练
- 批次 B 的 Eval Pipeline 可引用 trace_id 做 bad case 回溯
- Guardrails 审计数据为企业合规报表（self-dev loop 的审批门控）供数
