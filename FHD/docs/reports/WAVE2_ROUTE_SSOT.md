# Wave 2 路由 SSOT 进度

> v10 线内迭代 · 对齐 [COMPAT_LAYER_INVENTORY.md](COMPAT_LAYER_INVENTORY.md)

| 优先级 | 域 | 状态 | SSOT 路径 |
|--------|-----|------|-----------|
| P0 | health/liveness | 完成 | `fastapi_routes/health_k8s.py` |
| P1 | auth | 进行中 | `domains/auth/routes.py`（deprecated tag 待摘） |
| P1 | shipment/materials/print | 进行中 | `domains/shipment/` + compat mounts |
| P1 | AI chat/intent | 完成 | `domains/conversation/compat_routes.py` + `ai_intent/kitten/qclaw` |
| P2 | legacy_compat 余项 | 待办 | 逐项迁入 `domains/*` |
| P2 | legacy_gap | 待空 | `mounts/legacy_gap.py` |

每域 PR 门禁：`route_inventory_diff` 0 · OpenAPI 一致 · 相关 pytest 绿。
