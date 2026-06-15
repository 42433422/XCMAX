# ESkill：支付对账（skill-payment-reconcile）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-payment-reconcile` |
| 所属员工 | `payment-billing-reconciler` |
| 业务域 | 支付账单对账与报告 |
| 版本 | 1.1.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取本地订单数据 → 读取 LLM 计费记录 → 对比支付宝账单数据（API 或 CSV）
→ 计算差异 → 生成对账报告（Markdown）
→ 差异 > 阈值则标记告警
```

**输出 schema**：
```json
{
  "status": "ok | warning | error",
  "total_orders": 0,
  "matched": 0,
  "diff_count": 0,
  "diff_amount_cny": 0.0,
  "report_md": "",
  "platform_snapshot": {
    "total_orders": 0,
    "total_gmv": 0.0,
    "platform_revenue": 0.0,
    "author_payable": 0.0,
    "refunds_count": 0,
    "refunds_amount": 0.0,
    "wallet_top_ups": 0.0,
    "alipay_income": 0.0
  },
  "local_book_total_cny": 0.0,
  "history_vs_previous_period": {
    "previous_report_id": null,
    "previous_period_end": null,
    "total_gmv_delta_cny": null,
    "total_gmv_delta_pct": null
  },
  "llm_narrative": null,
  "doc_archive_hint": ""
}
```

- `platform_snapshot` / `local_book_total_cny`：与后端 `POST /api/admin/reconciliation/preview` 对齐（只读，不落库）。  
- `history_vs_previous_period`：相对最近一份 **已确认** 快照的 GMV 变动；无历史时为 `null`。  
- `llm_narrative`：动态阶段填入差异归因摘要（假设须标注）；静态流水可为 `null`。  
- `doc_archive_hint`：定稿后交由 `doc-knowledge-curator` 归档，`report_md` 勿含密钥。

**约束**：不写 DB，不打印密钥明文，所有金额操作只读。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 账单 API 不可达；数据格式解析失败 |
| 结果不达标 | `diff_count > 0` 或 `diff_amount_cny > 0.01` |

## 3. 动态阶段

**预算**：4000 tokens，4 步。  
**约束**：资金差异修复必须经 admin 确认，不自动写入。

## 4. 固化

**验收标准**：对外部账单比对场景 `diff_count == 0` 且 `diff_amount_cny` 容差内；admin 确认 `report_md`。

## 5. 后端对齐（可选自动化入口）

管理员只读：`POST /api/admin/reconciliation/preview` — 详见仓库内 `MODstore_deploy/docs/runbooks/payment-reconciliation-preview-api.md`（相对本文件：`../../../../MODstore_deploy/docs/runbooks/payment-reconciliation-preview-api.md`）。脚本与 RPA 仅持 token，不写 `_local_secrets`，且遵守各员工 `forbidden_globs`。
