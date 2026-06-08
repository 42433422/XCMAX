# 对外 TLS 域名与证书路径清单

本文档由 **nginx-config-engineer** 维护；新增公网域名或更换证书路径时须同步更新，并由 **`deploy-release-officer`** / **`payment-billing-reconciler`** 确认支付回调域名与高优先级证书续签流程。

## 当前站点（仓库内可见配置）

| 域名 | 用途 | 证书路径示例（宿主机） | 备注 |
|------|------|-------------------------|------|
| `xiu-ci.com` | 主站 HTTPS | `/etc/nginx/ssl/xiu-ci.com_bundle.crt` + `.key` | 参见 [`nginx-https-example.conf`](../nginx-https-example.conf) |
| `www.xiu-ci.com` | 主站 WWW | 同上 bundle（SAN） | 与上行通常为同一证书 |

## 运行时巡检配置

每日摘要 / 运维 `cert-expiry-check` 需要可读 PEM。**不在仓库内存私钥**；生产主机通过环境变量声明路径：

- **`MODSTORE_TLS_CERT_PATHS`**：逗号或分号分隔的证书 PEM（CRT）路径，例如  
  `/etc/nginx/ssl/xiu-ci.com_bundle.crt`

可选告警阈值（天，`daily_digest` / `tls_cert_inspection`）：

- `CERT_EXPIRY_INFO_DAYS`（默认 60）
- `CERT_EXPIRY_WARN_DAYS`（默认 30）
- `CERT_EXPIRY_CRIT_DAYS`（默认 14）

## 支付相关

浏览器 → 本站使用上表站点证书；**支付宝开放平台** 使用平台侧 TLS，不由我方托管证书。Java 支付子服务内网 URL 常见为 HTTP（非面向公网的 TLS 终止点）——见 `.env.production.example` 中的 `JAVA_PAYMENT_SERVICE_URL`。
