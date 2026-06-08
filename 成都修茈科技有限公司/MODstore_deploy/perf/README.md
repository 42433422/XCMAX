# MODstore 全链路压测

本目录放置可执行的 k6 压测脚本，用于把登录、市场浏览、支付/钱包、知识库/LLM 和 WebSocket 串成统一容量基线。

## 快速开始

本机已有业务栈时：

```bash
k6 run perf/full_link_smoke.js
```

通过 Docker Compose 运行：

```bash
docker compose --profile app --profile loadtest up --build loadtest
```

压测远端或非默认端口：

```bash
BASE_URL=https://staging.example.com \
WS_URL=wss://staging.example.com \
K6_STAGE=step \
TEST_EMAIL=loadtest@example.com \
TEST_PASSWORD='***' \
k6 run perf/full_link_smoke.js
```

## 场景

`K6_STAGE` 支持以下值：

| 值 | 用途 |
| --- | --- |
| `smoke` | 2 VU、1 分钟，部署后冒烟与轻量回归 |
| `step` | 阶梯加压，观察容量拐点 |
| `soak` | 稳定性压测，观察内存、连接池和错误率漂移 |
| `spike` | 尖峰压测，观察限流、重试和恢复能力 |

默认不压 LLM/RAG 写入和重型任务，避免消耗外部额度。需要覆盖时显式打开：

```bash
ENABLE_LLM=true ENABLE_RAG=true k6 run perf/full_link_smoke.js
```

## 覆盖链路

- `GET /api/health`、`GET /health/live`
- `POST /api/auth/login`、`GET /api/auth/me`（配置测试账号时启用）
- `GET /api/market/catalog`、`GET /api/market/facets`、`GET /v1/packages`
- `GET /api/payment/plans`、`GET /api/payment/orders`、`GET /api/wallet/balance`
- `GET /api/llm/status`、知识库轻量查询（显式开启时）
- `WS /api/realtime/ws?token=...`（配置测试账号时启用）

## 验收阈值

脚本内置基础阈值：

- HTTP 失败率 `< 2%`
- HTTP p95 `< 1s`
- HTTP p99 `< 2.5s`
- 业务检查错误 `< 5`
- WebSocket 连接 p95 `< 1s`

这些阈值用于发现明显回归。正式容量报告应结合 Grafana 的 `MODstore Overview` 面板记录 CPU、JVM、连接池、支付代理和 5xx 指标。

## 压测报告模板

每次压测记录以下信息：

- 版本/commit、部署方式、目标环境规格。
- `K6_STAGE`、VU、持续时间、测试账号、是否开启 LLM/RAG。
- k6 摘要：吞吐、p95/p99、错误率、业务错误。
- Grafana 观察：FastAPI p95、支付代理 p95、Java heap、Hikari 连接池、告警。
- 瓶颈和下一步动作。

## 公开基线文档

仓库内已发布的压测记录与复现命令见 **[`../docs/perf-benchmark-public.md`](../docs/perf-benchmark-public.md)**（当前最近更新日期以该文件「元数据」一节为准）。
