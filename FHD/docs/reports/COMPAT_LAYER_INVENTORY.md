# 兼容层摸底建账（①-A）

> v10 线内迭代 · 盘点日 2026-06-07 · **只读建账，非升版**

## 摘要

| 维度 | 数量 | HTTP 层 |
|------|------|---------|
| `*_app_service_v2.py` | 23 | 全部事件/Neuro 入口 |
| `APP_SERVICE_PAIRS` 登记 | 23 对（含 3 孤儿补登） | **100% `http_layer=v1`** |
| `legacy_compat` 顶层挂载 | ~35 router | 活跃 |
| `deprecated=True` 域路由 | 10 文件 | 仍挂载 |
| `legacy_gap` | 7 域 | 默认**不**挂载 |

SSOT 登记：[`app/application/app_service_pair_registry.py`](../../app/application/app_service_pair_registry.py)

---

## 1. V1/V2 应用服务对

| domain | v1 getter | v2 getter | http_layer | 备注 |
|--------|-----------|-----------|------------|------|
| auth | get_auth_app_service | get_auth_app_service_v2 | v1 | V2 仅 execute_command |
| user | get_user_app_service | get_user_app_service_v2 | v1 | |
| customer | get_customer_app_service | get_customer_app_service_v2 | v1 | |
| conversation | get_conversation_app_service | get_conversation_app_service_v2 | v1 | |
| shipment | get_shipment_application_service | get_shipment_app_service_v2 | v1 | |
| template | get_template_app_service | get_template_app_service_v2 | v1 | |
| wechat_contact | get_wechat_contact_app_service | get_wechat_contact_app_service_v2 | v1 | |
| wechat_task | get_wechat_task_app_service | get_wechat_task_app_service_v2 | v1 | |
| ai_chat | get_ai_chat_app_service | get_ai_chat_app_service_v2 | v1 | |
| product | get_product_app_service | get_product_app_service_v2 | v1 | |
| material | get_material_app_service | get_material_app_service_v2 | v1 | |
| print | get_print_application_service | get_print_app_service_v2 | v1 | |
| ocr | get_ocr_application_service | get_ocr_app_service_v2 | v1 | |
| excel_vector | get_excel_vector_ingest_app_service | get_excel_vector_app_service_v2 | v1 | |
| file_analysis | get_file_analysis_app_service | get_file_analysis_app_service_v2 | v1 | |
| unit_products_import | get_unit_products_import_app_service | get_unit_products_import_app_service_v2 | v1 | |
| product_import | get_product_import_application_service | get_product_import_app_service_v2 | v1 | |
| extract_log | get_extract_log_app_service | get_extract_log_app_service_v2 | v1 | |
| user_preference | get_user_preference_app_service | get_user_preference_app_service_v2 | v1 | |
| user_memory_vector | get_user_memory_vector_ingest_app_service | get_user_memory_vector_app_service_v2 | v1 | |
| order | get_order_app_service | get_order_app_service_v2 | v1 | ①-B 补登 |
| purchase | — | get_purchase_app_service_v2 | v1 | 仅 V2 |
| inventory | get_inventory_app_service | get_inventory_app_service_v2 | v1 | ①-B 补登 |

---

## 2. Compat 路由挂载（`legacy_compat.py`）

| 路由模块 | URL 前缀/标签 | 迁移优先级 |
|----------|---------------|------------|
| market_account | /api/market/* | P2 |
| fhd_meta | /api/fhd/db-tokens/status | P3 |
| debug_client_log | /api/debug/client-log | P3 |
| domains.auth.routes | /api/auth/* | P1（deprecated） |
| system_routes | /api/system/* | P2 |
| code_editor | /api/code-editor/* | P3 |
| private_db_read_assistant_compat | 函数注册 | P2 |
| user_cs_wechat_passive_compat | 函数注册 | P2 |
| wechat_decrypt_routes | /api/wechat/decrypt/* | P2 |
| **xcagi_compat** | /api（聚合） | **P0 SSOT** |
| document_templates | /api/document-templates | P2 |
| xcagi_startup | /api/startup/status | P2 |
| template_api | /api/templates* | P1 |
| shipment_orders | /api/orders*, shipment-records | P1 |
| materials | /api/materials* | P1 |
| upload | /api/upload/* | P2 |
| ocr | /api/ocr/* | P2 |
| print_routes | /api/print/* | P2 |
| ai_assistant | /health, /api/generate, shipment-records | P1 |
| excel_* | /api/excel/* | P2 |
| health_k8s | /health/liveness\|readiness | P0 |
| state | /api/state/* | P2 |
| payment/sales/contract/operations | 各 /api/* | P2 |
| ai_intent / ai_kitten / ai_qclaw | /api/ai/* | P1 |
| approval | /api/approval/* | P2 |
| service_bridge | /api/service-bridge/* | P2 |

`XCAGI_REGISTER_LEGACY_ROUTES=1` 时额外挂载 [`legacy_gap.py`](../../app/fastapi_routes/mounts/legacy_gap.py)（与 xcagi_compat **双挂载风险**）。

---

## 3. Deprecated 域路由（仍注册）

| 文件 | tag |
|------|-----|
| domains/auth/routes.py | legacy-auth |
| domains/conversation/routes.py | legacy-conversation |
| domains/excel/routes.py | legacy-excel |
| domains/inventory/routes.py | legacy-inventory |
| domains/product/routes.py | legacy-products |
| domains/shipment/routes.py | legacy-workflow |
| domains/static/routes.py | legacy-static |
| domains/system/routes.py | legacy-system |
| domains/wechat/routes.py | legacy-wechat |
| domains/misc/helpers.py | (deprecated) |

---

## 4. 独立 compat 模块

- [`xcagi_compat.py`](../../app/fastapi_routes/xcagi_compat.py) — 57 行聚合器
- [`xcagi_compat_product.py`](../../app/fastapi_routes/xcagi_compat_product.py)
- [`private_db_read_assistant_compat.py`](../../app/fastapi_routes/private_db_read_assistant_compat.py)
- [`user_cs_wechat_passive_compat.py`](../../app/fastapi_routes/user_cs_wechat_passive_compat.py)
- [`openapi_route_compat.py`](../../app/fastapi_routes/openapi_route_compat.py)
- `domains/{conversation,product,wechat}/compat_routes.py`

---

## 5. 测试与遥测

| 项 | 状态 |
|----|------|
| `test_order_neuro_command_service.py` | 已从 collect_ignore 移除，可收集 |
| Neuro 命令 SSOT | `app.application.neuro_commands.*` |
| 清理看板 | [`LEGACY_CLEANUP_TRACKING.md`](LEGACY_CLEANUP_TRACKING.md) |
| 声称 vs 实际 | [`CLAIMED_VS_ACTUAL.md`](../CLAIMED_VS_ACTUAL.md) |

---

## 6. Wave 2 对齐（Tier C 规划）

执行顺序见 [`WAVE2_ROUTE_SSOT.md`](WAVE2_ROUTE_SSOT.md)；P0 health → P1 auth/shipment/AI → P2 legacy_compat 余项。

## 7. ①-B 建议顺序

1. 保持 HTTP V1，V2 仅 Neuro 事件（当前策略）
2. `purchase` 域文档化「仅 V2」策略
3. 逐域将 deprecated routes 流量迁至 `xcagi_compat` / domains SSOT
4. `_v2` 后缀收敛见 [`MIGRATION_v2_DROP_PLAN.md`](../MIGRATION_v2_DROP_PLAN.md)
