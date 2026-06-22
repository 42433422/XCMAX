# v10 技术债收口状态（2026-06-07）

## 已完成（v10 线内迭代）

| 项 | 说明 |
|----|------|
| P0 SQLite 并发 | `get_db` / `session.get_db` → `MultiDbConsistencyManager.transaction` + 写锁 |
| P1 限流 / NDJSON | 桌面与 Helm 默认开启；整机中间件测试 |
| P2 SLA / Helm | `sla-probe.yml`、`helm lint` + `envFrom` |
| Shim 删除 | 删除 22 个 `legacy_*` / `xcagi_compat_*` shim；保留 `xcagi_compat.py` |
| **路由登记** | `RouteRegistry` + `mounts/*`；去重 `aibiz_terminal`；legacy_gap 不再默认双挂 |
| **Redis 安全** | 无 pickle；token 锁 |
| **K8s 基线** | SecurityContext / PDB / NetworkPolicy |
| **session 缓存** | `ThreadSafeLRUCache` + 可选 Redis 后端 |
| **依赖分类** | `requirements.txt` / `requirements-ml.txt` / `[dev]` |
| **CI 门禁** | mypy 硬失败；coverage M1 40%；vue-tsc |

## Shim 删除后导入规范

```python
from app.fastapi_routes.domains.auth import routes
from app.fastapi_routes.xcagi_compat import router
from app.fastapi_app import create_fastapi_app  # 包 app/fastapi_app/factory.py
```

CI 门禁：`python scripts/dev/verify_no_legacy_shims.py`

## 可选后续

- chat.js 物理删除（当前：生产构建已不加载；Vue `useChatView` 为唯一实现）
- 全量 API `ok` → `success` 迁移（已提供 `response_envelope.py`）
