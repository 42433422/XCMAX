# MODstore SRE 运行体系

## 服务分级

| 等级 | 服务/链路 | 说明 |
| --- | --- | --- |
| P0 | 登录、市场入口、支付、钱包、订单查询 | 直接影响交易和用户进入系统 |
| P1 | WebSocket 工作台、知识库/RAG、LLM 状态与会话 | 影响核心体验，可短时降级 |
| P2 | Grafana/Prometheus、Webhook 重放、管理工具 | 影响运维效率或异步补偿 |

## SLO

| 链路 | 可用性目标 | 延迟目标 | 错误率目标 |
| --- | --- | --- | --- |
| 入口健康 `/api/health` | 99.9% | p95 < 300ms | 5xx < 0.1% |
| 登录/鉴权 | 99.5% | p95 < 800ms | 5xx < 0.5% |
| 市场浏览 | 99.5% | p95 < 1s | 5xx < 0.5% |
| 支付/钱包 | 99.9% | p95 < 2s | 5xx < 0.2% |
| WebSocket 连接 | 99.0% | 连接 p95 < 1s | 异常断开可恢复 |
| LLM/RAG | 99.0% | 首响应优先，外部错误单独归因 | 5xx < 1% |

## 错误预算

- 以 30 天为窗口计算错误预算。
- P0 链路预算消耗超过 50%：暂停高风险发布，必须补监控或压测证据。
- P0 链路预算耗尽：冻结非紧急发布，只允许修复、回滚、容量和可观测性变更。
- 外部供应商导致的 LLM/RAG 错误要单独归因，但仍需要前端降级和用户提示。

## 发布门禁

每次生产发布至少满足：

1. CI 通过。
2. `python scripts/sre_smoke_check.py ...` 通过。
3. Grafana 无 P0/P1 未处理告警。
4. 支付相关变更已执行 `docs/PAYMENT_GRAY_RELEASE.md` 的预检。
5. 有明确回滚方式和负责人。
6. 数据结构或支付变更已说明数据补偿路径。

## 事故分级

| 等级 | 条件 | 响应目标 |
| --- | --- | --- |
| SEV1 | 支付不可用、登录不可用、整站不可用、数据损坏 | 15 分钟内响应，优先止血 |
| SEV2 | 核心链路部分失败、错误率持续超 SLO、WebSocket 大面积异常 | 30 分钟内响应 |
| SEV3 | 单个功能异常、监控缺口、性能退化但可用 | 1 个工作日内处理 |

## 事故流程

1. 确认影响：Grafana、Prometheus targets、冒烟脚本、用户反馈。
2. 指派负责人：一个 incident commander，一个执行修复的人。
3. 止血优先：回滚、限流、关闭高风险入口、切回 Python/Java 支付后端。
4. 恢复验证：冒烟检查、关键业务手工验证、告警归零。
5. 复盘：24 小时内记录时间线、根因、影响、改进项。

## 容量管理

- 提交到仓库的公开基线表：[`docs/perf-benchmark-public.md`](perf-benchmark-public.md)。
- 每个生产版本至少保留一次 `K6_STAGE=smoke` 结果。
- 大版本或支付/数据库变更前执行 `K6_STAGE=step`。
- 每月执行一次 `K6_STAGE=soak`，观察 JVM heap、Hikari、FastAPI p95 和支付代理 p95。
- 记录单机容量基线：最大稳定 QPS、CPU/内存水位、数据库连接池水位、主要瓶颈。
- 当任一核心资源持续超过 70% 且 p95 接近 SLO 上限时，进入扩容或优化评估。

## 值班入口

- 监控：Grafana `MODstore Overview`。
- 冒烟：`scripts/sre_smoke_check.py`。
- 压测：`perf/full_link_smoke.js`；公开记录见 [`docs/perf-benchmark-public.md`](perf-benchmark-public.md)。
- 混沌：`chaos/chaos_drill.py`。
- 备份：`scripts/backup_modstore.py`。
- 灾备：`docs/runbooks/disaster-recovery.md`。
- 支付灰度：`docs/PAYMENT_GRAY_RELEASE.md`。
- 演练记录：`docs/runbooks/exercises/`（dry-run / tabletop / 预发 confirm 全部按日期归档）。
