# Security SSOT 映射（项 22）

本目录是桌面/私有化主路径的**安全边界模块**，不是凑文件数。

| 能力 | 模块 | 说明 |
|------|------|------|
| Web JWT | `web_jwt.py` | 管理端/Web 会话 |
| Mobile JWT / 配对 | `mobile_jwt.py`, `mobile_pairing.py` | 移动端 |
| License | `license_*.py`, `license_guard.py` | 授权与审计 |
| LAN | `lan_*.py` | 局域网门禁 |
| 日志脱敏 | `log_redaction.py` | 禁止密钥进日志 |
| 扫码登录 | `auth_qr_login.py` | QR 登录 |

相关但不在本目录（有意保留，避免重复搬迁）：

- `app/infrastructure/auth/` — FastAPI Depends / 身份注入
- `app/utils/security/` — 密码哈希、安全文件名、下载路径
- `app/fastapi_routes/domains/auth/` — HTTP 路由

新增安全能力：优先扩展本目录或 `infrastructure/auth`，并补测试；禁止空文件充数。

## debt19 thicken

Added input_sanitizer, secrets_redactor, authz_policy, audit_trail, csrf_protect, rate_limit_policy, threat_headers, session_hardening, path_traversal_guard, security_health.
