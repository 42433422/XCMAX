# 只读对账预览 API（RPA / automation）

## `POST /api/admin/reconciliation/preview`

- **鉴权**：管理员 JWT（与普通对账快照 API 相同）。
- **副作用**：无（不落库、不改 `payment_orders`）。
- **请求体**：`period_start`、`period_end`（ISO 8601）；可选 `alipay_statement_total_cny`（支付宝侧由 RPA 归集后的总额，用于粗比）。
- **响应**：`payment_reconcile` 与 Yuangon `skill-payment-reconcile` 对齐（含 `report_md`、`history_vs_previous_period`、`doc_archive_hint`）。

## 密钥与 Alipay

开放平台证书与私钥仅保留在服务端或 `_local_secrets` 治理流程内；自动化脚本调用本接口时使用 **服务端颁发** 的管理员 token，不得在仓库或 RPA 配置中写入私钥明文。

批量账单下载应与 `java_payment_service` / Alipay SDK 对齐，避免重复维护两套验签逻辑。
