# MODstore 与 XCAGI（FHD）身份对齐建议

## 现状

- **MODstore**：HS256 JWT，`MODSTORE_JWT_SECRET`（见 `auth_service.py`）；Java 支付服务需与之共用密钥（`app_factory` 注释）。
- **FHD/XCAGI**：小程序 JWT（`mp_auth`）、业务 API Key、`license_token`、开发者 PAT 等多套凭证。

## 统一路径（择一）

### A. 共享密钥签发「市场用户 JWT」（最小改动）

1. FHD 校验 MODstore 下发的 Bearer JWT 时，使用与 MODstore **相同**的 `MODSTORE_JWT_SECRET` 与 **相同**的 `sub`/`exp` 约定（算法 HS256）。  
2. 网关或 FHD 增加可选中间件：信任来自 MODstore 域的 `Authorization` 头。  
3. 密钥轮换：两边同步更新环境变量并重启。

### B. OIDC / SSO（推荐中长期）

1. 引入 IdP（Authentik、Keycloak、Auth0 等），MODstore 与 FHD 均配置同一 OIDC Client 或同一 Organization。  
2. MODstore 的「登录」与 FHD 的「登录」均走授权码流，后端只验 OIDC `access_token`（JWKS）。  
3. 支付与用户 ID 仍以 MODstore `users.id` 为主键时，在 IdP `claims` 中映射 `modstore_user_id`。

## 环境变量备忘

| 变量 | 用途 |
|------|------|
| `MODSTORE_JWT_SECRET` | MODstore Python/Java JWT |
| `MODSTORE_JWT_ISSUER` / `AUD`（若启用） | 跨服务校验声明 |

部署时请避免在仓库模板中保留默认弱密钥。
