# XCMAX 18 域对标审计：状态记录（2026-09-28）

> 本记录**只声明证据现状，不授予分数**。标准与字段定义见
> `FHD/config/audit_benchmark_ssot.json`（生成视图 `FHD/docs/AUDIT_BENCHMARK_SSOT.md`）。
> 基准清单锚点 `source_sha = 6fccb47f38a7bc5cfe38a15b57c41c51afd54481`（origin/main 写入时点）。

- standard_version: `1.0.0`；scoring_version: `external-anchors-v1`；measurement_status: `anchors_defined_not_benchmarked`
- 缺失证据规则：合格线所需证据未知/跳过/不可访问 ⇒ `domain_status = UNRATED`、`score = null`；未知不得填 0 或通过。
- 因此**本轮不出正式 18 域总分**（任一域 UNRATED 即不合成总分）。
- 参考版本/数据集哈希/任务协议/预算/环境等逐域字段：待该域真正开测时按 `required_audit_record_fields` 逐项登记，本表不预填。

## 逐域状态

| 域 | 已可引用证据 | domain_status | score | 主要缺口 |
|---|---|---|---|---|
| architecture 依赖注入与分层 | 仅仓库源码与 CI 静态检查（E1） | UNRATED | null | 无同协议任务集；缺 E3 运行证据 |
| erp ERP 订单与资金闭环 | 2026-09-28 Windows 客户闭环 U1–U7 PASS / U8 FAIL | UNRATED | null | U8 未过，E3 未闭环 |
| agent-orchestration Agent 编排与审批 | 参考选择记录 `agent-langgraph-benchmark-20260909.md`（E0） | UNRATED | null | 仅参考选择，无同协议实测 |
| etl ETL 与业务文件处理 | 参考选择记录 `etl-nifi-benchmark-20260910.md`（E0） | UNRATED | null | 无 ≥30 冻结用例与负向集 |
| intent-routing AI 意图与工具路由 | 无 benchmark 记录；仅有单测/离线夹具（E2） | UNRATED | null | 缺 ≥100 留出任务与模型/预算登记 |
| event-kernel NeuroBus 事件内核 | 参考选择记录 `event-kafka-benchmark-20260909.md`（E0） | UNRATED | null | 无并发竞争与恢复实测 |
| mod-sdk Mod SDK 与行业模块 | 仅 Mod 目录/schema 静态证据（E1） | UNRATED | null | 无真机加载/故障恢复任务 |
| desktop 桌面壳与更新恢复 | [MACOS_RELEASE_SSOT.md](../../MACOS_RELEASE_SSOT.md)、[WINDOWS_RELEASE_SSOT.md](../../WINDOWS_RELEASE_SSOT.md)（G1–G13 历史真机） | UNRATED | null | 无连续 ≥30 天 E4 窗口；macOS G1/G2/G4 仍 YELLOW |
| business-frontend FHD 前端与用户任务 | 参考选择记录 `business-frontend-erpnext-desk-benchmark-20260909.md`（E0） | UNRATED | null | 无冻结任务集与原材料样本 |
| marketplace-ui 商城前端与工作流 UI | 参考选择记录 `marketplace-ui-saleor-dashboard-benchmark-20260910.md`（E0） | UNRATED | null | 同上 |
| commerce-backend 商城交易与交付后端 | 参考选择记录 `commerce-backend-saleor-benchmark-20260910.md`（E0） | UNRATED | null | 缺重复扣款/幂等不变量实测 |
| autonomy 自治与维护执行 | 参考选择记录 `autonomy-rundeck-benchmark-20260910.md`（E0） | UNRATED | null | 现有 90 天门槛未累计满 |
| java-payment Java 支付服务 | 无 benchmark 记录（E0/E1 均缺） | UNRATED | null | 参考条目与实测协议均未建立 |
| flutter-mobile Flutter 移动端 | 无 benchmark 记录 | UNRATED | null | 参考条目与实测协议均未建立 |
| shared-engine Retort 共享引擎 | 无 benchmark 记录 | UNRATED | null | 参考条目与实测协议均未建立 |
| coding-sandbox Vibe 编码与沙箱 | 无 benchmark 记录 | UNRATED | null | 需 ≥100 留出编码任务与沙箱隔离证据 |
| customer-service 客来来独立子系统 | 参考选择记录 `customer-service-chatwoot-benchmark-20260910.md`（E0） | UNRATED | null | 生产积压率与 handler_failed 未实跑验收 |
| ci-release CI、发布与治理 | 78 个 workflow + 门禁运行历史（E2） | UNRATED | null | 无该域参考实测与观察窗口 |

## 结论

- 18 域均为 `UNRATED`：合格所需证据（`>=30` 冻结用例、E3 真机任务与恢复、90 分档 ≥30 自然日 E4）尚未按本协议采集。
- 下一步顺序：先补齐 desktop / erp / customer-service 三域的 E3（已有真机链路），再逐域冻结任务集与预登记指标以启动 E4 观察窗。