# SQLite 多库与一致性说明

## 背景

主市场库使用 [`modstore_server/models.py`](../modstore_server/models.py) 中的 SQLAlchemy `Base` 与单一 SQLite 文件（或 `DATABASE_URL` 指向的其他库）。Mod 侧可能附带独立 SQLite 数据文件（例如随包分发的 `data/*.db`），与主库**不在同一 SQLite 连接**内。

## 限制

SQLite **不支持**跨多个物理数据库文件的单事务 ACID。若业务步骤既写主库又写 Mod 自带库，中途失败会出现部分提交。

## 推荐做法

1. **优先单库**：将与订单/用户强一致的数据保留在主库 schema 中。
2. **Saga / 补偿**：若必须双写，实现显式应用层步骤：先写主库并持久化意图 → 写 Mod 库 → 失败则根据主库状态重试或标记待修复任务。
3. **文档化边界**：在 API 与运维手册中标出「非原子」操作，便于排障与审计。

## 与「可靠性层」

若「可靠性层」指对 FHD / 外部 HTTP 的调用，见 [`workflow_fhd_bridge.py`](../modstore_server/workflow_fhd_bridge.py)：应在 httpx 客户端上配置超时、有限重试，并在编排层记录失败状态以便人工或自动补偿。
