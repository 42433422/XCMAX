# app/legacy/ 登记表

> legacy 模块唯一收容目录。所有 `legacy_*` 命名的过渡期模块必须迁入此目录；
> 禁止在 `app/` 其他子目录新增 `legacy_*` 文件。
>
> 边界由 `scripts/arch_fitness.py` 的 `check_legacy_boundary()` 守护。

## 迁入登记

| 原路径 | 新路径 | 退役条件 | 负责模块 |
|--------|--------|---------|---------|
| `app/application/workflow/legacy_chat_adapter.py` | `app/legacy/chat/legacy_chat_adapter.py` | `chat` / `chat_stream_sse_events` 工作流迁移到 `app/application/ai_chat_app_service.py` 原生实现、移除对 `app.legacy.planner` 的吸收式实现后 | AI Chat |
| `app/fastapi_routes/mounts/legacy_compat.py` | `app/legacy/routes/legacy_compat.py` | 前端从 `xcagi_compat` 历史契约迁移到新 domain API 契约、`register_legacy_compat_routes` 内的历史路由逐个迁入 `app/fastapi_routes/domains/` 后 | FastAPI Routes / Frontend Compat |
| `app/fastapi_routes/mounts/legacy_gap.py` | `app/legacy/routes/legacy_gap.py` | 所有 domain routes 通过 `xcagi_compat`（SSOT）统一注册、移除 `XCAGI_REGISTER_LEGACY_ROUTES` opt-in gap mount 后 | FastAPI Routes |
| `app/infrastructure/documents/legacy_shipment_document.py` | `app/legacy/documents/legacy_shipment_document.py` | `ShipmentDocumentGenerator` 生成逻辑完全迁移到 `app/infrastructure/documents/` 原生实现、移除对 `resources/tools_legacy/AI助手/shipment_document.py` 的 `sys.path` + `importlib` 动态加载后 | Shipment Documents |
| `app/domain/shipment/legacy_vo.py` | `app/legacy/domain/legacy_vo.py` | 涂料行业值对象迁移到 `app/domain/value_objects/` 分层模块、移除对 `app.domain.value_objects_compat` 的转发后 | Shipment Domain |

## 退役流程

1. 在负责模块的应用层/领域层完成原生实现。
2. 更新所有 import 指向新位置。
3. 从本目录删除对应 `legacy_*` 文件，并在本表标注「已退役」。
4. 运行 `python scripts/arch_fitness.py` 确认边界检查通过。
