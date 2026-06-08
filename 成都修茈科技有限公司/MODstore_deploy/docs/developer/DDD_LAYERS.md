# MODstore DDD 分层（P2 落位约定）

新业务能力请按层落位，**不要**在扁平 `*_api.py` 中继续堆叠业务逻辑。

| 层 | 路径 | 职责 |
|----|------|------|
| Domain | `modstore_server/domain/<bounded_context>/` | 类型、不变量、端口（`types.py`, `ports.py`） |
| Application | `modstore_server/application/` | 用例编排、跨聚合协调 |
| Infrastructure | `modstore_server/infrastructure/` | DB、HTTP、外部系统适配 |
| API | `modstore_server/*_api.py` | HTTP 映射、鉴权、DTO 转换 |

已有 bounded context：`catalog`, `employee`, `workflow`, `payment_gateway`, `auth`, 等（见 `domain/` 子目录）。

验收（与 [specs/spec.md](../../../specs/spec.md) P2-1 对齐）：`application/` ≥3 服务文件、`domain/` ≥2 上下文包——当前仓库已满足；新增功能应扩展既有包而非新建平行 `*_legacy.py`。
