# Ops Metrics P2

目标：把运营指标从页面临时统计提升为可聚合、可审计的数据域。

已落点：

- 后端 domain：`MODstore_deploy/modstore_server/domain/analytics.py`
- 后端 application：`MODstore_deploy/modstore_server/application/analytics.py`
- 后端 repository：`MODstore_deploy/modstore_server/infrastructure/analytics_repository.py`
- 后端 API：`MODstore_deploy/modstore_server/analytics_api.py`
- 前端 typed API：`MODstore_deploy/market/src/application/analyticsApi.ts`
- 前端类型：`MODstore_deploy/market/src/domain/analytics/types.ts`

首批指标：

- 员工执行总数、成功率、失败数、token 总量、平均耗时。
- 消费金额、购买次数、退款次数、钱包交易次数。
- 包总数、公开包数量、员工包数量。
- 最近员工执行记录。

后续扩展：

- 事件 outbox 聚合。
- 按日/周/月趋势。
- 管理员全局运营视图。
- 外部 BI/OLAP 同步。
