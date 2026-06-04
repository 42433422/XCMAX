# M1 启动清单（阶段 1 · M1–M3）

> **对照 SSOT**：[`specs/对标头部SaaS-步骤路径图.md`](../../specs/对标头部SaaS-步骤路径图.md) §3 **阶段 1（M1–M3）— 自证 + AI 深化**  
> **前置**：M0 本地/文档侧已基本闭环（见 [`M0-remaining-gaps.md`](M0-remaining-gaps.md)「已达标」）；**staging 7 天流量仍缺**（#1 → `specs/BLOCKERS.md` **T36–T37**）。  
> **M1 结束标志**（路径图原文）：投资人问「AI 审单命中率」能拿出 **1 份真实月报**；销售谈客户能拿出 **Mod 商店 4 张截图**。

---

## M0 staging 依赖说明

下列 M1 项 **硬依赖** M0 staging（7 天流量 / Grafana 基线 / 只读库），在 **T36–T37** 解阻塞前只能做骨架或 SYNTHETIC，**不可**在 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md) 标「已验证」：

| 依赖项 | M1 任务 | 阻塞 SSOT |
|--------|---------|-----------|
| staging 7 天 P95 / 错误率 / QPS | AI 月报 PDF（真实数据） | T36–T37 · [`M0-remaining-gaps.md`](M0-remaining-gaps.md) #1 |
| staging / 生产只读库 | AI 月报复核、审单命中率口径 | **T56** |
| `docs/evidence/slo/` 四域 PNG | 月报与 SLO 自证交叉引用 | T36–T37 · #1 / #3 |

**不依赖 staging**（可并行开工）：mypy（已达标）、API 契约测试、AI Agent V0 demo、Mod 四图试点、等保测评机构接洽。

---

## 阶段 1 任务对账

| 路径图周次 | 任务 | 验收 | 状态 | 依赖 M0 staging? |
|------------|------|------|------|------------------|
| M2-W1 | mypy 收紧：FHD `ignore_errors` **18→6** | `pyproject.toml` 宽口径 ≤6；见 CLAIMED mypy 行 | ✅ **已完成**（2026-06-05，**6/6**） | 否 |
| M2-W1 | 核心 API 契约测试 | `cd FHD/frontend && npm run test -- src/api` 全绿（**30** 文件 / **367** 测例，2026-06-05） | ✅ **已完成** | 否 |
| M2-W2 | **AI Agent 平台 V0** | 自然语言 → 工作流；1 个 demo 跑通 | ✅ mock + **live** 工具链（`087cf0a9` · `demo-run-20260605-live.json`）；planner 无 Key 仍为 fallback | 否 |
| M2-W3 | **AI 月报自动生成** | 1 份 PDF 入 `docs/evidence/` | ⬜ 待启动 | **是**（7 天 staging 数据；T36–T37 / T56） |
| M2-W4 | **Mod 真实商家**（四图） | 上架 → 支付 → 开通 → `evidence/mod/01–04.png` | ⬜ 待启动 | 否（与 staging SLO 独立） |
| M3-W1 | Mod 商店 **0.01 元**真实流水 | 支付宝账单截图 | ⬜ 待启动 | 否 |
| M3-W2 | 智能搜索 V0 | API 文档 + 1 个 demo | 📝 计划已起草 [`smart-search-v0-plan.md`](smart-search-v0-plan.md)；demo 未交付 | 否 |
| M3-W3 | 智能纪要 | 通义听悟 / 腾讯会议 API；1 个 demo | 📝 计划已起草 [`meeting-minutes-v0-plan.md`](meeting-minutes-v0-plan.md)；demo 未交付 | 否 |
| M3-W4 | **等保二级测评启动** | 测评机构合同 + 时间表（[`compliance-tier2-kickoff.md`](compliance-tier2-kickoff.md)） | 📝 **已起草**（启动清单）；合同/时间表待签 | 否 |

---

## 执行优先级（建议）

1. **已闭项**：mypy **6/6** — 勿重复开工；MODstore 自有模块继续减半（路径图 M2-W1 后半句）。
2. **可立即开**：AI Agent V0 demo、API 契约测试绿线、Mod 四图（[`mod-merchant-pilot.md`](mod-merchant-pilot.md) + 脚本）、等保机构询价/合同（[`compliance-tier2-kickoff.md`](compliance-tier2-kickoff.md)）。
3. **等 staging**：AI 月报 PDF 真实版；月报写入 CLAIMED 前需 T36–T37 + T56 复核。

---

## 证据目录

| 产物 | 路径 |
|------|------|
| Mod 四图 | [`evidence/mod/`](evidence/mod/)（01–04.png） |
| AI 月报 PDF | `docs/evidence/`（待建；文件名建议 `ai-monthly-YYYY-MM.pdf`） |
| staging SLO | [`evidence/slo/`](evidence/slo/)（M0 #1，M1 月报数据源） |
| AI Agent demo | 待定点（建议 `docs/evidence/ai-agent-v0/`） |
| 等保二级启动 | [`evidence/compliance-tier2/`](evidence/compliance-tier2/)（合同脱敏 + 时间表） |

---

## 相关文档

- M0 剩余缺口：[`M0-remaining-gaps.md`](M0-remaining-gaps.md)
- Mod 试点步骤：[`mod-merchant-pilot.md`](mod-merchant-pilot.md)
- 等保二级启动：[`compliance-tier2-kickoff.md`](compliance-tier2-kickoff.md)（M3-W4）
- 声称对照：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)
- 阻塞 SSOT：[`specs/BLOCKERS.md`](../../specs/BLOCKERS.md)（T36–T37、T56）
- Staging runbook：[`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md)

---

| 日期 | 更新 |
|------|------|
| 2026-06-05 | 初版：对照路径图阶段 1；mypy 标绿；staging 依赖单列 |
| 2026-06-05 | M3-W4 等保二级：链 [`compliance-tier2-kickoff.md`](compliance-tier2-kickoff.md)，状态标 **已起草** |
| 2026-06-05 | M2-W1 API 契约测试：`src/api` **367/367** 通过（vitest 2.0.5） |
