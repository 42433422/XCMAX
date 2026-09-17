# 项目真实状态（诚实仪表盘）

> **本文件的唯一职责：说真话。** 不写愿景、不写"已完成"除非有证据。
> 给人看，也给 AI 员工看——它们照字面信这里的每一行，所以这里只许写实测。
> 最后更新：2026-09-17

## 一句话定位

被资深架构师画在**生产级图纸**上、地基三刀（SSOT / schema / 运行时真相）已通电的项目。
结构的雄心仍略跑在业务闭环前面。**成熟度不以本文自评数字表述**：能力分级计数、三线交付等级与覆盖率一律取自动生成视图 [`PRODUCT_LINES_STATUS.md`](PRODUCT_LINES_STATUS.md)；外部对标评分口径见 [`AUDIT_BENCHMARK_SSOT.md`](AUDIT_BENCHMARK_SSOT.md)。

## 客服闭环总线 SSOT（勿混）

**客服工单闭环的事件总线 SSOT = MODstore `incident_bus` + `incident_team`（intake-dispatcher / user-customer-service-officer 等），不是 FHD NeuroBus。**

- 事件名如 `ops.intake.customer_ticket` 走 MODstore 发布与派发；duty 触发绑定 incident_bus，不写 NeuroBus subscribe。
- FHD NeuroBus 仍服务宿主域事件与 Mod 钩子，**不承担**客服工单 intake→派发→回写闭环。
- 短注：[`architecture/CUSTOMER_TICKET_BUS_SSOT.md`](./architecture/CUSTOMER_TICKET_BUS_SSOT.md)

## 两份幻觉，真相在中间

- **架构图骗你往高看**：DDD 四层 / NeuroBus 全套可靠性 / 一套大脑三端 / SSOT 元框架——看着 8 分。
- **文档骗你往低看**：写 deps 漂移 31、k8s 漂移 51，**实测全是 0**；写"企业版无向量搜索"，其实 SQLite 暴力余弦**早已实现**。
- **真相在中间**：很多地方**实物比文档好，但比架构差**。

## 状态数字来源（禁止自评）

本文件只做**定性**陈述与问题清单，不承载任何评分或百分比。需要数字时读生成视图：

| 需要什么 | 唯一来源 |
|---|---|
| 能力分级（已验证 / 部分验证 / 已实现待验证 / 规划中） | [`PRODUCT_LINES_STATUS.md`](PRODUCT_LINES_STATUS.md) ← 能力目录 `catalog.json` 逐项证据校验 |
| 三线交付等级（macOS / Windows 门禁结论） | [`PRODUCT_LINES_STATUS.md`](PRODUCT_LINES_STATUS.md) ← [MACOS](MACOS_RELEASE_SSOT.md) / [WINDOWS](WINDOWS_RELEASE_SSOT.md) 发布 SSOT |
| 覆盖率 | [`../metrics/coverage-dual-summary.json`](../metrics/coverage-dual-summary.json) |
| 外部对标评分（18 领域，商业 90 / 开源 60 锚点） | [`AUDIT_BENCHMARK_SSOT.md`](AUDIT_BENCHMARK_SSOT.md) |

## 真东西（不是空架子）👍

- **租户隔离 🟢**：34 模型覆盖、读过滤+写打标+ratchet 守卫、27 测试。**真·承重墙。**
- **方言分叉处理对了**：alembic baseline 已 dialect-aware，SQLite 端干净、向量检索已实现。
- **底子比文档体面**：真实漂移是 0，不是 82。
- **SSOT gate 🟢**：`ssot_cli.py gate` 对全部 enabled 域阻断；`neuro-bus-events` 已启用；`docs-ssot` 走 `--strict`。
- **运行时真相 🟢**：`scripts/ops/runtime_inventory.py` + `/api/xcmax/ops/runtime-inventory` + 公司大厅 `runtime` 字段。

## 曾卡住"成为产品"的 3 件事（2026-07-24 通电）

| # | 问题 | 状态 | 证据 |
|---|---|---|---|
| 1 | 底座没插电（SSOT advisory） | 🟢 已通电 | `ssot.yaml` 全域 enabled；`registry-crosscheck`；CI `ssot-drift-gate` `continue-on-error: false` |
| 2 | schema 双头 + SKIP 绕过 | 🟢 旁路已封 / 双头冻结 | entrypoint 拒 `FHD_SKIP_ALEMBIC=1`；FHD+MODstore ensure_* only-shrink 冻结测试 |
| 3 | 运行时真相缺失 | 🟢 清单已落地 | topology 真值端口 9999/9990；runtime inventory；大厅嵌入；行动板 `day_stale` |

## 地基施工进度（自底向上打 SSOT）

| 级别 | 内容 | 状态 |
|---|---|---|
| **L0** 元层插电 | SSOT 统一 gate advisory→blocking | 🟢 已落地 |
| **L1** 接神经 | 双注册表（ssot.yaml / SSOT_INDEX.md）互校验 | 🟢 `ssot_registry_crosscheck.py` |
| **L2** schema 承重 | SQLite parity blocking + 冻结 ensure_* + 方言文档 + 摘 SKIP 开关 | 🟢 旁路封死；存量库 stamp 仍按发版流程执行 |
| **L3** 运行时真相 | desired×actual 单一清单 | 🟢 runtime-inventory 域 + 公开投影 |

> L0–L2 差价已收回大半。下一刀在**业务闭环**（客服 incident_bus 执行串、handler_failed、Para 真修通）。

### 客服闭环定轨（2026-07-24）

- **SSOT**：MODstore `incident_bus` + incident team（见 [`architecture/CUSTOMER_TICKET_BUS_SSOT.md`](architecture/CUSTOMER_TICKET_BUS_SSOT.md)）
- **不是** FHD NeuroBus 订阅轨；duty 合同经 binding 落到 incident，不经 `bus.subscribe`
- 执行体：`intake-dispatcher.routing_plan` → incident_bus 下游派发；publish 边界强制 enrich

## SSOT 全景（从最底层往上）

```
L5 治理元层    注册表本身 ssot.yaml / SSOT_INDEX        🟢 互校验 blocking
L4 质量可观测  coverage🟢 / claimed-vs-actual🟢 / compliance🟡
L3 依赖构建    deps🟢(0漂移) / ci-workflows🟢
L2 系统自契约  version🟢 / mods🟢 / routes🟡 / error-codes🟢 / neuro-bus-events🟢
L1 组织与人    duty_roster🟢(有守卫)
L0 物理基底    DB schema🟢(旁路封+冻结) · 租户隔离🟢 · runtime-inventory🟢
```

## 仍未解决（别假装）

- 客服 `customer_ticket`：已定轨 **MODstore `incident_bus`**（enrich + `routing_plan` 真派发 + handler_failed 按 event_type 可观测）；**生产积压率仍需实跑验收**
- Para 多 CLI 已有 fallback，但「真改代码→验证→回写」端到端未稳定证明
- 存量生产库若历史 `SKIP_ALEMBIC` 过，需一次 `alembic stamp/upgrade` 对齐（发版流程执行，非代码缺口）
- 认知 Processor 已挂生产 intent（失败 fallback unified）；域事件样板仅采购订单创建→`order.created` 持久化，未宣称全域落地
- 认知全栈补齐（2026-07-29）：SCM lite 因果/反事实、技能契约开放世界、策略向持续学习、软约束规划、白名单自我反思已落地（见 `docs/architecture/COGNITIVE_FULL_STACK_20260729.md`）；全域业务因果与跨行业适配器仍需扩样板
- 战略自治规划（2026-07-29）：LLM 季度目标分解 + 反思修正 + adaptive_thresholds 已接入；运维 impact-predictor 规则轨仍在，LLM advisory 需 `XCAGI_IMPACT_LLM=1` 开启
- **Windows 交付面偏差不在此复述**：stable feed 仍广播旧构建（`73861ed7`）、未签名隔离包进 testing 通道、签名管线未配置、故障注入与 AI 任务实测结论——全部事实、门禁结论与处置选项见 [`WINDOWS_RELEASE_SSOT.md`](WINDOWS_RELEASE_SSOT.md)（§2 产物校验和 / §4 门禁状态 / §5 B1–B12 阻断项）。**本节只保留决策口径：不回滚、不改写 stable feed，等同一 SHA 的签名构建覆盖**（对应 B6 的两个可选处置，需用户授权）。
