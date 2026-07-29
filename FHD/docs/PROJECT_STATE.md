# 项目真实状态（诚实仪表盘）

> **本文件的唯一职责：说真话。** 不写愿景、不写"已完成"除非有证据。
> 给人看，也给 AI 员工看——它们照字面信这里的每一行，所以这里只许写实测。
> 最后更新：2026-07-24

## 一句话定位

被资深架构师画在**生产级图纸**上、地基三刀（SSOT / schema / 运行时真相）已通电的项目。
结构的雄心仍略跑在业务闭环前面。**当前综合 ≈ 6.5 / 10**（地基通电后上修；无人公司业务闭环另计）。

## 客服闭环总线 SSOT（勿混）

**客服工单闭环的事件总线 SSOT = MODstore `incident_bus` + `incident_team`（intake-dispatcher / user-customer-service-officer 等），不是 FHD NeuroBus。**

- 事件名如 `ops.intake.customer_ticket` 走 MODstore 发布与派发；duty 触发绑定 incident_bus，不写 NeuroBus subscribe。
- FHD NeuroBus 仍服务宿主域事件与 Mod 钩子，**不承担**客服工单 intake→派发→回写闭环。
- 短注：[`architecture/CUSTOMER_TICKET_BUS_SSOT.md`](./architecture/CUSTOMER_TICKET_BUS_SSOT.md)

## 两份幻觉，真相在中间

- **架构图骗你往高看**：DDD 四层 / NeuroBus 全套可靠性 / 一套大脑三端 / SSOT 元框架——看着 8 分。
- **文档骗你往低看**：写 deps 漂移 31、k8s 漂移 51，**实测全是 0**；写"企业版无向量搜索"，其实 SQLite 暴力余弦**早已实现**。
- **真相在中间**：很多地方**实物比文档好，但比架构差**。

## 三轴打分（基于实证，非记忆）

| 维度 | 分 | 依据 |
|---|---|---|
| 架构设计 / 雄心 | 8 | NeuroBus 800 行带熔断/重试/死信/追踪；跨端复用 |
| 工程治理 | 7 | SSOT gate **blocking**；双注册表互校验；neuro-bus-events 已启用 |
| 落地 / 生产可用 | 5 | schema 旁路已封；runtime inventory 已落地；业务闭环（客服工单/Para 真修）仍有缺口 |
| **综合** | **6.5** | 地基通电；无人公司业务层未满 |

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
