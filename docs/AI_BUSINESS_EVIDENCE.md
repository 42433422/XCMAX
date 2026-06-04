# AI 业务证据（T55–T57）

> **状态（2026-06）**：已写入 **SYNTHETIC/SEED** 月报（2026-06）；生产/staging 真实数据仍待 T56 复核 + SYNTHETIC/SEED 入口；生产/staging 真实数据仍待 **T56** 复核。  
> **生成**：`python scripts/ai_evidence/seed_synthetic_evidence.py YYYY-MM`

## 场景（T55）

1. 发货单自动审（AI 命中率）
2. 合同到期提醒（触达率）

## 月报索引

| 月份 | 场景1 AI 命中率 | 场景2 触达率 | 备注 |
|------|-----------------|--------------|------|
| 2026-06 | SYNTHETIC 75.8% | SYNTHETIC 90.0% | seed-sqlite；非生产 |

---

---

## 月报 — 场景 1：发货单自动审（**SYNTHETIC/SEED**）

**统计月份**：`2026-06`  
**环境**：`seed-sqlite`（[`metrics/ai-evidence-seed.db`](../../metrics/ai-evidence-seed.db)）  
**数据性质**：**非生产** — 由 [`scripts/ai_evidence/seed_synthetic_evidence.py`](../../scripts/ai_evidence/seed_synthetic_evidence.py) 生成

| 指标 | 数值 | 说明 |
|------|------|------|
| 处理总量 | 100 | 进入审单流水线的发货单数 |
| AI 自动通过 | 72 | `decision=auto_approve` |
| 转人工 | 23 | `decision=manual` |
| **AI 命中率** | **75.8%** | `auto_approve / (auto_approve + manual)` |
| OCR 失败放弃 | 5 | 无法解析 |

**结论**：种子数据 AI 命中率 75.8%（目标 ≥70%）；待 staging 真实月报替换。

---

## 月报 — 场景 2：合同到期提醒（**SYNTHETIC/SEED**）

**统计月份**：`2026-06`  
**环境**：`seed-sqlite`（同上种子库）  
**数据性质**：**非生产**

| 指标 | 数值 | 说明 |
|------|------|------|
| 到期前 30 天合同数 | 95 | 符合条件合同（种子常量） |
| 应推送任务数 | 120 | 调度生成 |
| 推送成功 | 108 | 企微 API 2xx |
| 推送失败 / 跳过 | 12 | 含用户拒收 |
| **触达率** | **90.0%** | `成功 / 应推送` |

**结论**：种子数据触达率 90.0%（目标 ≥90%）；待 staging 真实月报替换。

---

## 月报模板 — 场景 1：发货单自动审

（模板段落；SYNTHETIC 块由 `seed_synthetic_evidence.py` 注入）

## 月报模板 — 场景 2：合同到期提醒

（模板段落）
