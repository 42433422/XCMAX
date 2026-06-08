# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 10.0.x  | :white_check_mark: |
| 8.0.x   | :x:                |
| 7.0.x   | :x:                |
| < 7.0   | :x:                |

## Reporting a Vulnerability

We take the security of XCAGI seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email at [security@xcagi.com](mailto:security@xcagi.com) or create a draft security advisory on GitHub.

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

### Information to Include

Please include the following information in your report:

- A description of the vulnerability
- Steps to reproduce the issue
- Affected versions
- Any potential impact
- Suggested fixes (if any)

### Process

1. **Initial Response**: Within 48 hours, we will acknowledge your report
2. **Investigation**: We will investigate the issue within 5 business days
3. **Fix Development**: We will work on a fix and test it thoroughly
4. **Release**: We will release a patched version and credit you (if desired)
5. **Disclosure**: After 30 days, we may disclose the issue publicly

## Secrets Governance（尽调 / 投资前必读）

### 禁止入库的路径

以下模式**不得**出现在 Git 跟踪中（仅允许 `*.example` / `*.template` 占位模板）：

| 类型 | 模式 | 说明 |
|------|------|------|
| 环境变量 | `.env`、`.env.*`（非 example） | 含 `SECRET_KEY`、`DATABASE_URL`、支付密钥等 |
| Docker 本地 | `.env.fhd-docker` | 对照 [`/.env.fhd-docker.example`](.env.fhd-docker.example) |
| K8s | `secret.yaml`（非 example） | 对照 [`k8s/secret.yaml.example`](k8s/secret.yaml.example) |
| 支付订单 | `**/payment_orders/order_*.json` | 运行时快照，含真实订单号 |
| 密钥目录 | `**/keys_staging/`、`**/*.pem`、`**/*.der` | 支付宝/SSH 等私钥 |
| 本地密钥池 | `_local_secrets/` | MODstore 员工账号池等 |

### 若本地曾存在真实密钥

1. **立即轮换**：`SECRET_KEY`、`POSTGRES`/`DATABASE_URL` 密码、`ADMIN_PASSWORD`、支付宝私钥、`PAYMENT_SECRET_KEY`、`MODSTORE_JWT_SECRET` 等——**假定已泄露**。
2. **历史清理**：旧 commit 可能仍含敏感文件。投资/开源发布前须运行第三方扫描（[Gitleaks](https://github.com/gitleaks/gitleaks)、[TruffleHog](https://github.com/trufflesecurity/trufflehog)）并按需执行 `git filter-repo` / BFG 清除历史 blob。
3. **扫描门禁**：建议在 CI 增加 `gitleaks detect --redact`；合并前人工确认 `git ls-files` 无上述模式。
4. **报告渠道**：发现仓库内疑似真实密钥，请通过下方邮箱私密报告，**勿**开公开 Issue。

### 模板文件约定

- 示例 env 使用 `change-me-*`、`YOUR_PASSWORD`、`REPLACE_ME` 等明显占位符。
- 禁止在 example 中写入可连通的 DB 密码、生产域名 API Key 或 `openssl rand` 样式的「看起来像真」的 hex（本地 `.env.fhd-docker` 若已生成，仅保留在工作区，勿 `git add`）。

## Security Best Practices

### For Users

1. **Environment Variables**: Never commit sensitive information like API keys or passwords
2. **Database Security**: Use strong passwords for database access
3. **HTTPS**: Always use HTTPS in production environments
4. **Regular Updates**: Keep your dependencies up to date
5. **Access Control**: Implement proper authentication and authorization

### For Contributors

1. **Code Review**: All code changes must be reviewed
2. **Testing**: Security-sensitive code must have tests
3. **Documentation**: Document security implications
4. **Input Validation**: Always validate and sanitize user input
5. **Error Handling**: Never expose sensitive information in error messages

## Security Features

XCAGI includes several security features:

- **Password Hashing**: Passwords are hashed using PBKDF2-SHA256
- **Session Management**: Secure session handling with expiration
- **CORS Protection**: Configurable CORS policies
- **CSRF Protection**: Double-submit token pattern (OWASP recommended)
- **Rate Limiting**: Protection against brute-force attacks
- **Input Sanitization**: Protection against SQL injection and XSS
- **LAN Security**: CIDR whitelist + HMAC-SHA256 token authorization
- **Security Headers**: X-Content-Type-Options, X-Frame-Options, CSP

## Known Limitations

- SQLite database files should be properly backed up and protected (desktop mode)
- Local deployment requires proper system security
- API keys must be managed securely by the user
- Prometheus /metrics endpoint should be protected in production

## Contact

For security-related questions, please contact:
- Email: [security@xcagi.com](mailto:security@xcagi.com)
- GitHub Security Advisories: https://github.com/42433422/xcagi/security/advisories

---

**Last Updated**: 2026-06-08（尽调治理：密钥红线、历史扫描、Apache-2.0 对齐见 [`docs/guides/LICENSING.md`](docs/guides/LICENSING.md)）
