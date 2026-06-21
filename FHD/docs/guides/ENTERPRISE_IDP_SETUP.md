# 企业身份提供商（IdP）接入 — OIDC / SAML

> **范围**：FHD 主站企业 SSO。SAML 路由已存在，本文以 **OIDC（Keycloak）** 为 M4-W3 验收路径。

## 1. 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `XCAGI_OIDC_ENABLED` | 是 | `1` / `true` 启用 |
| `XCAGI_OIDC_ISSUER` | 是 | IdP Issuer URL，如 `https://idp.example.com/realms/xcmax` |
| `XCAGI_OIDC_CLIENT_ID` | 是 | OIDC Client ID |
| `XCAGI_OIDC_CLIENT_SECRET` | 视 IdP | 机密客户端需配置 |
| `XCAGI_OIDC_REDIRECT_URI` | 是 | **后端**回调，如 `https://app.example.com/api/auth/oidc/callback` |
| `XCAGI_OIDC_SCOPES` | 否 | 默认 `openid profile email` |
| `XCAGI_OIDC_FRONTEND_REDIRECT` | 否 | SSO 成功后浏览器落地页，默认 `/login`（前端解析 `?oidc=ok`） |
| `SECRET_KEY` | 是 | ≥32 字符，用于 OIDC state 签名 |
| `REDIS_URL` | 推荐 | 生产限流与会话辅助 |

SAML（可选）：`XCAGI_SAML_*` 见 [`DEPLOYMENT.md`](../DEPLOYMENT.md)。

## 2. Keycloak 最小配置

1. 创建 Realm `xcmax`（或复用企业 Realm）。
2. Clients → Create → Client ID `fhd-web`，类型 **OpenID Connect**。
3. **Valid redirect URIs**：`https://<FHD 域名>/api/auth/oidc/callback`
4. **Web origins**：`https://<FHD 域名>`
5. 复制 Client secret（若启用机密客户端）。
6. Issuer：`https://<keycloak>/realms/xcmax`

## 3. 登录流程

```text
用户点击「企业 SSO 登录」
  → GET /api/auth/oidc/start（302 至 IdP）
  → IdP 授权
  → GET /api/auth/oidc/callback（换 token + JIT 用户 + Set-Cookie）
  → 302 /login?oidc=ok
  → 前端 GET /api/auth/me → 进入业务首页
```

失败时回调 **302** 至 `/login?oidc_error=<code>&oidc_message=<msg>`。

SSO 成功后 FHD 会通过 MODstore 内部接口 `POST /api/auth/internal/sso-issue-token`（Header `X-Internal-Api-Key: $XCAGI_MARKET_INTERNAL_API_KEY`）自动签发市场 JWT 并写入会话；FHD 与 MODstore 须配置 **相同** 密钥。

## 4. 验收（M4-W3）

- [ ] Keycloak 测试 Realm 跑通上述流程
- [ ] 新用户 JIT 创建后可访问 ERP（权限按默认 role）
- [ ] `GET /api/auth/oidc/status` 返回 `enabled: true`
- [ ] 未启用时登录页不显示 SSO 按钮
- [ ] SSO 登录后 `GET /api/market/session-handoff` 可返回 `market_access_token`（需 `XCAGI_MARKET_INTERNAL_API_KEY`）

## 5. 相关代码

- SSO-only 会话通过内部桥接自动绑定市场 JWT；见 `login_market_for_oidc_profile`。
- OIDC Provider：[`app/infrastructure/auth/oidc_provider.py`](../../app/infrastructure/auth/oidc_provider.py)
- 路由：[`app/fastapi_routes/domains/auth/routes.py`](../../app/fastapi_routes/domains/auth/routes.py)
- 前端：[`frontend/src/views/LoginView.vue`](../../frontend/src/views/LoginView.vue)
