# 等保二级控制项映射（代码证据 · 未认证）

> **状态**：测评机构合同签署前，本文档仅作**整改预埋对照**，不构成「已通过等保二级」声明。  
> **SSOT**：[`compliance-tier2-kickoff.md`](../../compliance-tier2-kickoff.md)

| 控制域（二级常见项） | XCMAX 现状 | 证据路径 |
|---------------------|------------|----------|
| 身份鉴别 | 密码登录、OIDC/SAML 可选、MFA TOTP | `app/fastapi_routes/domains/auth/routes.py` · [`ENTERPRISE_IDP_SETUP.md`](../../guides/ENTERPRISE_IDP_SETUP.md) |
| 访问控制 | RBAC、多租户 `tenant_id`、数据域 scope | `app/fastapi_routes/domains/rbac/` · `app/domain/rbac/data_scope_policy.py` |
| 安全审计 | HTTP 敏感路径 JSON Lines + 应用层 `audit_logger` | `app/middleware/sensitive_audit.py` · `AUDIT_LOG_PATH` · `GET /api/admin/audit-logs` |
| 入侵防范 | 全局限流、认证限流、XSS 清理、CSRF | `app/middleware/global_rate_limit.py` · `auth_rate_limit.py` · `csrf.py` |
| 恶意代码防范 | Dependabot、CI 扫描（非运行时 AV） | `FHD/.github/dependabot.yml` |
| 数据保密性 | 会话 HttpOnly Cookie、TLS 部署指引 | `DEPLOYMENT.md` · `SESSION_COOKIE_*` |
| 数据备份恢复 | 运维 runbook（外部） | `MODstore_deploy/docs/runbooks/` |
| 剩余信息保护 | 日志脱敏、聊天 body 不记入审计 | `sensitive_audit.py` `_BODY_EXCLUDE_PREFIXES` |
| 个人信息保护 | GDPR 路由（Feature Flag） | `app/fastapi_routes/gdpr.py` |

## 待机构测评后补齐

- [ ] 定级备案材料与测评报告（`evidence/compliance-tier2/` 目录占位）
- [ ] 现场整改项闭环签字
- [ ] ISO 27001 / 等保三级（路径图 P3，12+ 月）
