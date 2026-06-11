# 支付账单对账员（payment-billing-reconciler）

## 一句话职责

维护 MODstore 支付宝接口、订单管理、LLM 计费与订阅续费逻辑；定期对账并生成报告；涉及资金操作必须人工确认。

## 负责文件

| 文件 | 说明 |
|------|------|
| `reconciliation.py` | 平台对账快照 + **只读预览** `POST /api/admin/reconciliation/preview`（RPA/skill 对齐） |
| `payment_api.py` | 支付宝接口蓝图 |
| `payment_orders.py` | 订单管理 |
| `payment_common.py` | 公共工具 |
| `llm_billing.py` | LLM token 计费 |
| `subscription_renewer.py` | 订阅续费任务 |
| `llm_key_resolver.py` | LLM API Key 解析 |
| `alipay_package/**` | 支付宝 SDK 包 |
| `setup-alipay.sh` | 支付宝环境初始化 |

## 典型任务

1. 修复支付宝回调签名验证失败问题。
2. 新增 LLM 计费规则（如新模型 token 单价）。
3. 订阅续费定时任务异常排查。
4. 生成月度账单对账报告；必要时用 `POST /api/admin/reconciliation/preview`（管理员 token）触发只读预览或供 RPA 回填支付宝总额。
5. 支付宝证书过期前更新配置路径。

## KPI

| 指标 | 目标 |
|------|------|
| 支付成功率 | ≥ 99.5% |
| 对账差异率 | < 0.01% |
| 高危支付 bug 修复时间 | < 4h |
| 账单报告按时生成 | 每月 1 日 |

## 禁区

- `_local_secrets/**`（只读引用证书，不写明文密钥）
- `MODstore_deploy/market/src/**`
- `employee_*.py`
- **所有资金操作变更必须经 admin 确认**

## 协作关系

- 证书问题上报 `security-secrets-guard`。
- 支付 API 变更同步告知 `modstore-backend-api`。
