# Runbook — 支付账单对账员

| 字段 | 值 |
|------|----|
| 员工 ID | `payment-billing-reconciler` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin（所有资金操作需人工确认）|

## 日常巡检

```bash
# 语法检查
python -m py_compile MODstore_deploy/modstore_server/payment_api.py
python -m py_compile MODstore_deploy/modstore_server/payment_orders.py

# 只读对账预览（管理员 JWT；不落库）。详见 MODstore_deploy/docs/runbooks/payment-reconciliation-preview-api.md
# curl -H "Authorization: Bearer <admin_jwt>" -H "Content-Type: application/json" \
#   -d '{"period_start":"2026-05-01T00:00:00","period_end":"2026-06-01T00:00:00"}' \
#   https://<host>/api/admin/reconciliation/preview

# 证书过期检查（替换实际证书路径）
openssl x509 -enddate -noout -in alipay_package/alipay_public_key.crt

# 订阅续费任务状态
python MODstore_deploy/modstore_server/subscription_renewer.py --status
```

## 异常处置

### 异常 1：支付回调签名验证失败

1. 确认支付宝证书路径和版本（联系 `security-secrets-guard`）。
2. 检查 `payment_common.py` 中签名算法配置。
3. **所有变更经 admin 审批后执行**。

### 异常 2：LLM 账单与实际消耗不符

1. 对比 `llm_billing.py` 计费记录与 LLM 供应商账单。
2. 生成差异报告，不直接修改账单记录（通知 admin）。

### 异常 3：订阅续费失败

1. 检查订阅到期的用户列表。
2. 确认支付宝通道可用。
3. 通知 admin 是否手动重试。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
