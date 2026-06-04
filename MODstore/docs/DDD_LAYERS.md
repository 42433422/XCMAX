# MODstore DDD 分层（Phase 1）

| 层 | 包路径 | 职责 |
|----|--------|------|
| Domain | `modstore.domain` | 实体、值对象、领域规则 |
| Application | `modstore.application` | 用例编排、事务边界 |
| Infrastructure | `modstore.infrastructure` | SQLAlchemy、文件、外部 API |
| Interfaces | `modstore.interfaces.http` | FastAPI `app` 入口 |

**兼容**：`modstore_server/` 与 `modman/` 仍为运行时包名；新代码优先写入 `modstore.*`，旧路径逐步迁移。

HTTP 入口：`from modstore.interfaces.http import app`（与 `modstore_server.app` 等价）。
