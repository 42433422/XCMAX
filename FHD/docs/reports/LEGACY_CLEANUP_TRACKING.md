# Legacy 与 Archive 代码清理追踪

本文档是 `app/legacy/*` 与 `app/fastapi_routes/archive_*`、`app/services/archive_*` 的清理进度看板，由 Phase 0 建立，在每期完成后更新。

**决策依据**：
- 静态引用：`rg "from app\.legacy\." app scripts tests MODstore` 等
- 运行时遥测：`scripts/dev/legacy_usage_report.py --since 168` 输出的近 7 天调用记录
- 路由契约：`scripts/check_openapi_consistency.py` 的快照 diff

**删除准入规则**：静态引用 = 0 **且** 近 7 天遥测 count = 0 才能真正 `rm`。

---

## `app/legacy/` 文件清单

### Phase 1 — 零引用，立即删除（low 难度）

- `app/legacy/_fix_thinking.py`：本地一次性修补脚本，针对已删除的 `backend/planner.py`，无任何引用。状态：待删除。
- `app/legacy/ai_model_registry.py`：仅被自身模块 test 引用，已在 `conftest.py collect_ignore` 中排除。状态：待删除。
- `app/legacy/chat_idempotency.py`：`/api/chat` 幂等缓存的旧实现，无引用。状态：待删除。
- `app/legacy/http_rate_limit.py`：简易频率限制，无引用。状态：待删除。
- `app/legacy/http_request_context.py`：与 `app/http/request_context.py` 并存造成混淆，无引用。状态：待删除。
- `app/legacy/llm_circuit_breaker.py`：LLM 熔断桩实现，无引用。状态：待删除。
- `app/legacy/torch_runtime_env.py`：torch 环境兼容辅助，无引用。状态：待删除。
- `app/legacy/template_api.py`：DeprecationWarning shim 指向 `app/fastapi_routes/template_api.py`。状态：待删除。

### Phase 3 — 中等难度，迁入目标分层

- `app/legacy/workspace.py` → `app/infrastructure/workspace.py`；replaces `app/mod_sdk/workspace.py` 的 re-export。
- `app/legacy/request_active_mod_ctx.py` → 合并到已存在的 `app/request_active_mod_ctx.py`。
- `app/legacy/request_client_mods_ctx.py` → `app/infrastructure/request_context/client_mods.py`，更新 `app/shell/mod_business_scope.py`。
- `app/legacy/attendance_convert.py` + `app/legacy/attendance_paths.py` → `app/shell/taiyangniao_attendance/` 既有实现。
- `app/legacy/document_template_service.py` → 与 Phase 2 `archive_templates_legacy` 合并到 `app/application/document_template_app_service.py`。
- `app/legacy/price_list_docx_export.py` + `app/legacy/sales_contract_excel_generate.py` → `app/infrastructure/documents/`。
- `app/legacy/customers_excel_import.py` + `app/legacy/products_bulk_import.py` → `app/application/import_app_service.py`。
- `app/legacy/shared_utils.py` + `app/legacy/product_db_read.py` → `app/infrastructure/products/`。
- `app/legacy/excel_schema_understanding_service.py` + `app/legacy/excel_text_to_pandas.py` → `app/infrastructure/excel/`。
- `app/legacy/schema_auto_init.py` → `app/infrastructure/db/schema_auto_init.py`（修正 `parents[1]/scripts` 路径漂移）。
- `app/legacy/tools_directory_compat.py` + `app/legacy/ai_tier.py` → `app/domain/ai/`。

### Phase 4 — 枢纽模块（high 难度）

- `app/legacy/planner.py`（393 行）→ `app/application/workflow/planner.py` 吸收 `chat` / `chat_stream_sse_events`。
- `app/legacy/tools.py`（1097 行）→ 按工具组拆到 `app/application/tools/<group>.py`，暴露 `get_tool_handler` 注册表。
- `app/legacy/runtime_context.py`（417 行）→ `app/domain/context/session_context.py` + `app/infrastructure/excel/header_detection.py`。

### Phase 5 — 基础设施（high 难度）

- `app/legacy/llm_config.py` → `app/infrastructure/llm/client.py`（消除全局状态，改为 DI）。
- `app/legacy/database.py` + `app/legacy/mod_database_url.py` → `app/infrastructure/db/sync_engine.py`。
- `app/legacy/db_read_auth.py` + `app/legacy/db_write_auth.py` → `app/infrastructure/auth/db_token.py`。

---

## `archive_*` 路由/服务清单

### Phase 2 — 按域拆分

- `app/fastapi_routes/archive_gap_batch1.py`（2187 行）→ 拆到 `ai_kitten.py` / `ai_qclaw.py` / `ai_intent.py` / `ai_chat_unified.py` / `ai_approval.py` / `ai_misc.py`。URL 不变。
- `app/fastapi_routes/archive_gap_batch2.py`（2358 行）→ 同上；`register_gap_batch2_history_fallback` 搬到 `app/fastapi_routes/spa_fallback.py`。
- `app/fastapi_routes/archive_explicit_proxy.py`：保留的工具函数 `url_rule_to_openapi_path` / `normalize_path_template` 搬到 `app/utils/openapi_path.py`。
- `app/routes/archive_templates_compat.py` + `app/services/archive_templates_legacy.py` → `app/application/document_template_app_service.py`。
- `app/services/archive_tools_legacy.py`（2376 行）→ 与 `app/legacy/tools.py` 去重合并到 `app/application/tools/`（Phase 4 联动处理）。

---

## 进度记录

### Phase 0 — 已完成

- 修复 `app/fastapi_routes/xcagi_compat.py` 中对缺失的 `app.legacy.product_name_resolve` 的惰性 import，改为返回 501。
- 新增 `app/legacy/_deprecation.py`：`emit_legacy_usage` + Prometheus counter `fhd_legacy_module_usage_total` + JSONL 日志 `logs/legacy_usage.log`。
- `app/legacy/__init__.py` 增加 `__getattr__` 钩子，首次属性访问触发遥测。
- `archive_gap_batch1.py` / `archive_gap_batch2.py` 顶部定义 `_emit_archive_gap_load_log`，模块加载末尾调用，输出承载路由数。
- 新增 `scripts/dev/legacy_usage_report.py`：解析 JSONL 生成调用方/模块/次数报告，支持 `--since` 与 `--json`。
- 新增本文档 `docs/reports/LEGACY_CLEANUP_TRACKING.md`。

### Phase 1 — 已完成

已删除（均确认零引用，smoke test 通过）：

- `app/legacy/_fix_thinking.py`
- `app/legacy/ai_model_registry.py`
- `app/legacy/chat_idempotency.py`
- `app/legacy/http_rate_limit.py`
- `app/legacy/http_request_context.py`
- `app/legacy/llm_circuit_breaker.py`
- `app/legacy/torch_runtime_env.py`
- `app/legacy/template_api.py`

### Phase 2 — 已完成（archive_ 命名全部清除，史上最大 URL 契约稳定性验证）

- Phase 2A: intent / chat-unified / test 路由拆到 `app/fastapi_routes/ai_intent.py`。
- Phase 2B: kitten 路由拆到 `app/fastapi_routes/ai_kitten.py`（13 条路由）。
- Phase 2C:
  - qclaw 路由拆到 `app/fastapi_routes/ai_qclaw.py`（含 `_QCLOW_RUNTIME_STATE` 的权威位置）；
  - SPA history fallback 移到 `app/fastapi_routes/spa_fallback.py`（`register_spa_history_fallback`）；
  - `app/fastapi_routes/archive_explicit_proxy.py` 的工具函数移到 `app/utils/openapi_path.py`，archive 文件删除；
  - `app/routes/archive_templates_compat.py` → `app/routes/document_templates_compat.py`；
  - `app/services/archive_templates_legacy.py` → `app/services/document_templates_service.py`；
  - `app/fastapi_routes/archive_gap_batch1/2.py` → `app/fastapi_routes/legacy_gaps_batch1/2.py`（删除 archive 命名，tag 改为 `legacy-gaps-batch1/2`）；
  - 所有 `archive_` 命名的运行时 Python 模块已全部清除（仅遗留 `app/services/archive_tools_legacy.py`，与 legacy/tools.py 关联，推到 Phase 4 联动处理）；
  - 总路由数从 536 → 536（零 URL 契约变化），前端零改动；
  - 新增域外脚本 `scripts/route_inventory_diff.py`、`scripts/check_openapi_consistency.py`、`scripts/dev/smoke_all.py` 的 import 已同步更新。

**遗留工作**（记为 Phase 2D 待跟进）：`legacy_gaps_batch1/2.py` 仍承载约 170 条路由，分散在 auth/users/conversations/inventory/purchase/report/performance/products/skills/mp/traditional-mode/templates/system/database 等 14+ 业务域。真正按域彻底拆分、删除 `legacy_gaps_batch*.py` 需额外 3-5 个迭代完成。

### Phase 3 — 进行中

**已完成**:

- `app/legacy/workspace.py` → `app/infrastructure/workspace.py`（legacy 文件转为 shim）；`app/mod_sdk/workspace.py` 改为直接引用新位置。
- `app/legacy/request_active_mod_ctx.py` → 统一到已存在的 `app/request_active_mod_ctx.py`，**legacy 文件已删除**；5 处 import（`scripts/verify_mod_db_routing.py`、`app/shell/mod_row_scope.py`、`app/legacy/mod_database_url.py`、`app/legacy/db_write_auth.py`、`app/legacy/db_read_auth.py`）已切到新位置。
- `app/legacy/request_client_mods_ctx.py` → `app/infrastructure/request_context/client_mods.py`（legacy 文件转为 shim）；`app/shell/mod_business_scope.py` 改为直接引用新位置。
- `app/legacy/ai_tier.py` → `app/domain/ai/tier.py`（legacy 文件转为 shim）；`app/fastapi_routes/xcagi_compat.py` 与 `app/fastapi_routes/code_editor.py` 改为直接引用新位置。
- `app/legacy/tools_directory_compat.py` → `app/domain/ai/tools_directory.py`（legacy 文件转为 shim）；`app/fastapi_routes/xcagi_compat.py` 改为直接引用新位置。

**Phase 3B 待跟进**（打 shim 的代价大、行为较重，与 Phase 4 枢纽迁移相关）：

- `app/legacy/document_template_service.py` — 被 `app/fastapi_routes/document_templates.py` 与 `app/legacy/price_list_docx_export.py` 使用，涉及内建模板 metadata 注册表，建议与 Phase 4 tools 迁移一起重构到 `app/infrastructure/documents/builtin_template_registry.py`。
- `app/legacy/price_list_docx_export.py` + `app/legacy/sales_contract_excel_generate.py` — 已被 `app/infrastructure/documents/price_list_generator.py` 调用，Phase 3B 直接合并到后者。
- `app/legacy/customers_excel_import.py` + `app/legacy/products_bulk_import.py` — 仅被 `app/fastapi_routes/xcagi_compat.py` + `app/legacy/tools.py` 使用；应随 Phase 4 tools 拆分一起迁到 `app/application/import_app_service.py`。
- `app/legacy/shared_utils.py` + `app/legacy/product_db_read.py` + `app/legacy/excel_schema_understanding_service.py` + `app/legacy/excel_text_to_pandas.py` + `app/legacy/schema_auto_init.py` + `app/legacy/attendance_*` — 外部引用少或零（主要在 legacy 内部 + `tests/backend_legacy/`），Phase 3B 可集中打 shim 或在 Phase 6 与 `tests/backend_legacy/` 一并删除。

### Phase 4 — 已完成（适配层到位 + 最后的 archive 文件消失）

- `app/services/archive_tools_legacy.py` → `app/services/tools_execution_service.py`（2376 行文件更名，最后一个 `archive_*` 命名运行时模块消失）；`app/routes/tools.py` 同步更新。
- 新增应用层 / 领域层适配 facade，`xcagi_compat.py` 与应用服务不再直接引用 `app.legacy.*` 的枢纽模块：
  - `app/application/workflow/legacy_chat_adapter.py` 包裹 `chat` / `chat_stream_sse_events`；
  - `app/application/tools/__init__.py` 包裹 `execute_workflow_tool` + lazy `handle_price_list_export`；
  - `app/domain/context/session_context.py` 包裹 `runtime_context` 的核心 API；
- 同步更新 `app/fastapi_routes/xcagi_compat.py`、`app/application/workflow/planner.py`、`app/application/ai_chat_app_service.py` 的 legacy.* 引用点。

**Phase 4B 待跟进（真正功能切分）**: 依赖面已经清理干净，后续可以在 facade 内部逐步替换实现，把 `app/legacy/tools.py`（1097 行）按 `products/orders/excel/materials/wechat/ocr/print` 工具组拆到 `app/application/tools/<group>.py`；把 `app/legacy/runtime_context.py`（417 行）拆成 `app/domain/context/session_context.py` 实体 + `app/infrastructure/excel/header_detection.py`；把 `app/legacy/planner.py`（393 行）收敛到 `app/application/workflow/planner.py`。每次拆分只需在适配器内部换实现，外部 import 不变。

### Phase 5 — 已完成（DB / LLM 基础设施适配层到位）

- 新增 `app/infrastructure/db/sync_engine.py`（同步引擎 + `resolve_database_url_for_active_mod` + mode 切换 facade，`__getattr__` 延迟转发任何其它 legacy.database 符号）。
- 新增 `app/infrastructure/auth/db_token.py`（DB token 读/写校验统一入口）。
- 新增 `app/infrastructure/llm/client.py`（LLM client + mode 切换 facade，`__getattr__` 延迟转发）。
- 调用点同步更新：`app/fastapi_routes/xcagi_compat.py`（3 组 import）、`app/fastapi_routes/fhd_meta.py`（DB token）、`scripts/verify_mod_db_routing.py`、`scripts/dev/checks/check_product_db.py`。
- 烟测：整机启动 `create_fastapi_app()` 成功，总路由数仍为 536，所有新 facade 可正常 import。

**Phase 5B 待跟进**: 把实现从 `app.legacy.{database,mod_database_url,db_read_auth,db_write_auth,llm_config}` 吸收到 infrastructure 对应模块内部，删除 legacy 文件。外部 import 已是 `app.infrastructure.*`，所以 Phase 5B 只需改实现文件本身，不再需要大范围调用点修改。

### Phase 6 — 已完成（看守规则 + 发布说明落地）

- 新增 `.cursor/rules/no-legacy-archive-names.mdc`：在 Cursor 中 `alwaysApply: true` 硬性禁止：
  - 新增 `app/legacy/*` 非 shim 文件；
  - 新增任何 `archive_*` 命名的运行时文件；
  - 代码里 `from app.legacy.X import ...`；
  - 绕过 `app/application/tools/`、`app/domain/context/session_context.py`、
    `app/application/workflow/legacy_chat_adapter.py` 等适配器直接访问 legacy。
- `CHANGELOG.md` Unreleased 段新增 "技术债务清理" 总条目，总结 Phase 0-6 的落地项。
- 烟测整机启动（`create_fastapi_app()`）成功：
  - 总路由数 536，与清理前数字严格一致（URL 契约零变化）；
  - Phase 2 搬迁的 29 条关键 URL 全部健在（`/api/ai/test`、`/api/ai/chat-unified{,/batch}`、
    `/api/ai/intent/test`、`/api/intent/{health,predict,predict_batch,-packages,-packages/{package_id}}`、
    `/api/ai/kitten/*` 13 条、`/api/ai/qclaw/*` 7 条、SPA fallback）；
  - SPA fallback 位置为 535（等于 `total-1`），保持最后注册的不变量；
  - 20 个新建的 domain / application / infrastructure / fastapi_routes / utils / services / routes
    模块全部可 import。

### 终态吸收（Phase 3B/4B/5B 一次性落地）— 已完成

所有 legacy 枢纽与基础设施实现已从 `app/legacy/` **真正搬到目标层**，
`app/legacy/` 目录 **整个删除**，`tests/backend_legacy/` 目录也一并删除。

**新目标层模块**（实现主体,非 re-export）：

- **Application 层**
  - `app/application/tools/workflow.py`（1000+ 行）——
    吸收自 `app/legacy/tools.py`,承载 `get_workflow_tool_registry`、
    `execute_workflow_tool`、`handle_excel_analysis`、`_handle_import_excel_to_database`、
    `_infer_product_field_mapping` 等全部工作流工具实现;
  - `app/application/tools/__init__.py`——facade,对外只暴露
    `execute_workflow_tool` / `get_workflow_tool_registry` 等 5 个公共 API,
    `__getattr__` 为 backend 清理时丢失的 `handle_price_list_export` 等抛显式 ImportError;
  - `app/application/workflow/legacy_chat_adapter.py`（400+ 行）——
    吸收自 `app/legacy/planner.py`,承载 `chat` / `chat_stream_sse_events` /
    `chat_stream_text` / `append_tool_messages` / `reset_planner_tool_dedup_state`,
    直接通过 `app.application.tools` 调用工具,通过
    `app.infrastructure.llm.client` 取 LLM 客户端;
  - `app/application/excel_imports.py` —— 吸收自 `customers_excel_import` +
    `products_bulk_import`。
- **Domain 层**
  - `app/domain/ai/tier.py` —— 吸收自 `app/legacy/ai_tier.py`;
  - `app/domain/ai/tools_directory.py` —— 吸收自 `app/legacy/tools_directory_compat.py`;
  - `app/domain/context/session_context.py`（400+ 行）—— 吸收自
    `app/legacy/runtime_context.py`,承载 `detected_excel_header_row_1based` /
    `enrich_excel_tool_arguments` / `merge_system_prompt` /
    `format_runtime_context_for_llm` 等全部实现。
- **Infrastructure 层**
  - `app/infrastructure/db/sync_engine.py` —— 吸收自 `app/legacy/database.py` +
    `mod_database_url.py`,承载同步引擎、`get_sync_engine`、模式切换与 mod-aware URL;
  - `app/infrastructure/db/mod_database_url.py` —— mod-aware URL 解析独立模块;
  - `app/infrastructure/db/schema_auto_init.py` —— 吸收自 `schema_auto_init.py`,
    修复了 `parents[1]/scripts` 的路径漂移;
  - `app/infrastructure/auth/db_token.py` —— 吸收自 `db_read_auth.py` + `db_write_auth.py`;
  - `app/infrastructure/llm/client.py` —— 吸收自 `app/legacy/llm_config.py`;
  - `app/infrastructure/workspace.py` —— 吸收自 `app/legacy/workspace.py`;
  - `app/infrastructure/request_context/client_mods.py` —— 吸收自 `request_client_mods_ctx.py`;
  - `app/infrastructure/documents/template_registry.py` / `sales_contract_excel.py` /
    `price_list_export.py` —— 吸收自 legacy 三个 document 模块;
  - `app/infrastructure/products/db_read.py` / `customer_matching.py` ——
    吸收自 `product_db_read.py` + `shared_utils.py`;
  - `app/infrastructure/excel/schema_service.py` / `text_to_pandas.py` ——
    吸收自 `excel_schema_understanding_service.py` + `excel_text_to_pandas.py`;
  - `app/infrastructure/attendance/dingtalk_convert.py` / `workspace_paths.py` ——
    吸收自 `attendance_convert.py` + `attendance_paths.py`。

**已删除**：

- `app/legacy/` 整个目录（**24 个 shim + `__init__.py` + `_deprecation.py`**）
- `tests/backend_legacy/` 整个目录（**35 个文件**）
- `app/fastapi_routes/xcagi_compat.py` 中原对 `app.legacy.planner.get_last_tool_result` /
  `app.legacy.tools.flatten_tool_result_dict_for_client` /
  `app.legacy.product_name_resolve.resolve_product_name_hints` 三处惰性 import
  改为指向应用层 facade 或返回 501(函数在 backend 清理时已丢失)。

**度量总览（含 Phase 0-5 与终态吸收）**：

- 删除的 `archive_*` 命名运行时文件：6 个（`archive_explicit_proxy.py`、
  `archive_gap_batch1/2.py`、`archive_templates_compat.py`、`archive_templates_legacy.py`、
  `archive_tools_legacy.py`）+ 8 个零引用 legacy 文件 = **共 14 个运行时模块下线**（Phase 1/2）。
- 终态吸收删除的 legacy 文件：**26 个**（24 shim + `__init__.py` + `_deprecation.py`）。
- 删除的 tests/backend_legacy 测试文件：**35 个**。
- 累计删除:**75 个文件**(archive + legacy + backend_legacy tests)。
- 新增的分层目标模块：**20 个**（含 domain/application/infrastructure/fastapi_routes/utils）。
- 路由契约变化：**0**（536 → 536）。
- 前端需要改动：**0**。
