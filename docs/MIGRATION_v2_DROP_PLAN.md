# AppService `*_vN.py` 收口与删除计划

> **登记**：`FHD/app/application/app_service_pair_registry.py`（V1/V2 成对与 HTTP 选型）  
> **盘点日期**：2026-06-04（T11）  
> **原则**：不删业务功能；V1 为生产实现，V2 多为 NeuroBus 事件侧车；禁止 `from v2 import *` 替换 V1（会破坏路由与测试）。

---

## 1. 现状盘点（`FHD/app/**/*_v[0-9]+.py`）

共 **24** 个版本后缀源文件（`find FHD/app -name '*_v[0-9]*.py'`）：

| # | 路径 | 配对 V1 模块 | HTTP 层（registry） | 备注 |
|---|------|--------------|---------------------|------|
| 1 | `app/application/ai_chat_app_service_v2.py` | `ai_chat_app_service` | v1 | V2 为事件命令入口 |
| 2 | `app/application/auth_app_service_v2.py` | `auth_app_service` | v1 | V2 仅 `execute_command` |
| 3 | `app/application/conversation_app_service_v2.py` | `conversation_app_service` | v1 | legacy 会话仍在 V1 |
| 4 | `app/application/customer_app_service_v2.py` | `customer_app_service` | v2 | mutation event-primary |
| 5 | `app/application/excel_vector_app_service_v2.py` | `excel_vector_app_service` | v1 | ingest/search 在 V1 |
| 6 | `app/application/extract_log_app_service_v2.py` | `extract_log_app_service` | v1 | |
| 7 | `app/application/file_analysis_app_service_v2.py` | `file_analysis_app_service` | v1 | |
| 8 | `app/application/inventory_app_service_v2.py` | `inventory_app_service_v2`（mutation） | v2 | |
| 9 | `app/application/material_app_service_v2.py` | `material_app_service` | v1 | |
| 10 | `app/application/ocr_app_service_v2.py` | `ocr_app_service` | v1 | |
| 11 | `app/application/order_app_service_v2.py` | （无同名 v1 文件） | — | 待核对引用 |
| 12 | `app/application/print_app_service_v2.py` | `print_app_service` | v1 | |
| 13 | `app/application/product_app_service_v2.py` | `product_app_service` | v2 | |
| 14 | `app/application/product_import_app_service_v2.py` | `product_import_app_service` | v1 | |
| 15 | `app/application/purchase_app_service_v2.py` | （无同名 v1 文件） | — | 待核对引用 |
| 16 | `app/application/shipment_app_service_v2.py` | `shipment_app_service` | v2 | |
| 17 | `app/application/template_app_service_v2.py` | `template_app_service` | v1 | |
| 18 | `app/application/unit_products_import_app_service_v2.py` | `unit_products_import_app_service` | v1 | |
| 19 | `app/application/user_app_service_v2.py` | `user_app_service` | v1 | |
| 20 | `app/application/user_memory_vector_app_service_v2.py` | `user_memory_vector_app_service` | v1 | |
| 21 | `app/application/user_preference_app_service_v2.py` | `user_preference_app_service` | v1 | |
| 22 | `app/application/wechat_contact_app_service_v2.py` | `wechat_contact_app_service` | v1 | |
| 23 | `app/application/wechat_task_app_service_v2.py` | `wechat_task_app_service` | v1 | |
| 24 | `app/mod_sdk/sdk_v2.py` | `mod_sdk` 兼容层 | — | **保留**；非 AppService 重复实现 |

**误报排除**（文件名含 `_v` 但非版本后缀）：`legacy_vo.py`、`catalog_visibility.py`、`mod_views_compat.py`、`fk_validation.py` 等 — 未计入上表。

---

## 2. 目标与守门

| 里程碑 | 目标 | 验收 |
|--------|------|------|
| 2026-06 | 禁止**新增** `*_v[0-9]+.py` | pre-commit + CI `guard-no-new-v2-files` |
| 2026-12 | `app/application/**/*_v2.py` → **0**（`sdk_v2`、明确 compat 除外） | `find` 清单为空 |
| 持续 | 数量**单调递减** | 每月更新 §1 表格行数 |

允许列表（守门脚本配置源）：[`scripts/ci/v2_versioned_py_allowlist.txt`](../scripts/ci/v2_versioned_py_allowlist.txt)

---

## 3. V1 → V2 迁移策略（非破坏性）

### 3.1 禁止的操作

- 禁止将 V1 模块改为 `from …_v2 import *`（V1/V2 API 不兼容，见 `auth_app_service` vs `AuthAppServiceV2`）。
- 禁止在未切换 `app_service_pair_registry.http_layer` 前删除 V1 文件。

### 3.2 推荐步骤（每域一批 PR）

1. 确认 `AppServicePair.http_layer` 与路由/bootstrap 一致。
2. 将 HTTP mutation 切到 event-primary / V2 getter（已有域：customer、product、shipment、inventory）。
3. 跑全量 `pytest FHD/tests/` + 相关 e2e。
4. V1 文件改为**薄 re-export 或 deprecation shim**（仅当 import 路径需兼容 1 个发布周期）。
5. 30 天后删除 V1（本文件 §4 登记删除日）。

### 3.3 T12 结论（2026-06-04）

**本轮未做 V1→alias 代码改动**：registry 中 22 个 application 域均为「V1 生产 + V2 侧车」，无安全的一行 alias 替换。后续仅在单域 HTTP 已 100% 走 V2 且测试绿后再加 shim。

---

## 4. 删除时间表（骨架，按域填日期）

| 域 | V1 计划删除日 | V2 保留至 | 负责人 | 状态 |
|----|---------------|-----------|--------|------|
| customer | — | 合并进主模块后删 `_v2` 后缀 | — | HTTP 已 v2 |
| product | — | 同上 | — | HTTP 已 v2 |
| shipment | — | 同上 | — | HTTP 已 v2 |
| inventory | — | 同上 | — | HTTP 已 v2 |
| auth | — | 长期保留 V1 | — | http_layer=v1 |
| ai_chat | — | 长期保留 V1 | — | http_layer=v1 |
| … | | | | 待填 |

---

## 5. 下一批人工工作（建议）

1. 核对 `order_app_service_v2` / `purchase_app_service_v2` 无 V1 文件时的引用链路与 registry 登记。
2. 对 `http_layer=v2` 四域：规划「去掉 `_v2` 后缀、单文件 canonical」命名 PR（先重导出，再改 import）。
3. 将 CHANGELOG / `V10_ACCEPTANCE.md` 中「0 个 _v2」表述改为指向本文档与 allowlist 数量。
4. 每月运行：`find FHD/app -name '*_v[0-9]*.py' | wc -l`，更新 §1 与 allowlist（仅减少、不增加）。

---

*维护：P0-4 执行人 · 最后更新 2026-06-04*
