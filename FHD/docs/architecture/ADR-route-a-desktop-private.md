# ADR：路线 A — 桌面 + 私有化为主

- **状态**：已接受（2026-06-12，v10 线内迭代）
- **决策者**：产品 + 平台工程

## 背景

XCAGI 同时交付 Web、Electron 桌面、Android 与 Mod 生态。需在「多租户 SaaS」与「桌面/私有化」之间选定主路线，避免 SQLite / PostgreSQL 双轨混用导致容量与 SLO 表述混乱。

## 决策

**主路线为桌面 + 私有化**：业务数据与 Mod 运行时以 **本地 SQLite Mod 分库** 为主；云端承担 **账号、MODstore 市场、支付、LLM 网关** 及可选同步，**不承担** Mod 业务数据主库。

## 域划分

| 域 | 运行时 | 数据 |
|----|--------|------|
| 桌面 / 私有化节点 | Electron + 本地 FastAPI | SQLite Mod、本地文件队列 |
| 云端 API | K8s / 单机 FastAPI | 会话、配置、市场代理；staging 用 SQLite 母库 |
| MODstore | 姊妹栈 | 账号、订单、支付、LLM 配额 |

## 写并发与扩容

- SQLite + `sqlite_write_guard`：**单机写并发**，不承诺多副本写同一 Mod 库。
- 私有化扩容：**垂直扩容**（CPU/RAM）+ 多桌面节点；非 HPA 水平写扩展。
- 云端 staging/production API：可按 [`k8s/deployment.yaml`](../../k8s/deployment.yaml) 水平扩展 **读与无状态 API**；Mod 业务写仍在桌面侧。

## Staging 定位

`119.27.178.147` staging 用于：**云侧 API、Prometheus/Grafana、k6 合同流量、SLO 证据**。不模拟桌面 SQLite 全量负载；容量分表见 [`capacity-planning.md`](../reports/capacity-planning.md)。

## 必须在云 vs 必须在本地

| 必须在云 | 必须在本地（桌面 SKU） |
|----------|------------------------|
| `/api/auth/*` 市场 JIT | Mod SQLite 业务库 |
| MODstore 市场 / 支付 | 离线 Excel / 打印 |
| LLM 代理（修茈平台） | 大文件上传缓存 |
| 可选：远程备份 | NeuroBus 本地事件（可同步） |

参考 [`lan_config.py`](../../app/security/lan_config.py) 局域网白名单。

## 后果

- **正面**：离线可用、数据主权、与 Mod 隔离模型一致。
- **负面**：Web 多租户 PG SaaS、千级并发写需另立路线 B（Backlog）。
- **SLO**：合同级 7d SLO 以 **云 API 路径** 为准；桌面性能单独记录。

## 相关文档

- [`ARCHITECTURE.md`](../ARCHITECTURE.md) §1.4
- [`STAGING_RUNBOOK.md`](../../k8s/monitoring/STAGING_RUNBOOK.md)
- [`acceptance-round1-invalid-20260612.yaml`](../evidence/slo/acceptance-round1-invalid-20260612.yaml)
