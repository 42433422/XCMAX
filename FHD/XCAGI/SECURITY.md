# Security Policy

## Supported Versions

Use this section to tell people about which versions of your project are currently being supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 6.0.x   | :white_check_mark: |
| 5.0.x   | :white_check_mark: |
| 4.0.x   | :x:                |
| 3.0.x   | :x:                |
| 2.0.x   | :x:                |
| 1.0.x   | :x:                |

## Reporting a Vulnerability

We take the security of XCAGI seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email at [security@example.com](mailto:security@example.com) or create a draft security advisory on GitHub.

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

## Security Best Practices

### For Users

1. **Environment Variables**: Never commit sensitive information like API keys or passwords
2. **Database Security**: Use strong passwords for database access
3. **HTTPS**: Always use HTTPS in production environments
4. **Regular Updates**: Keep your dependencies up to date
5. **Token Security**: Never share your Token wallet credentials
6. **Mod Verification**: Only install Mods from trusted sources
7. **Access Control**: Implement proper RBAC for your organization
8. **Audit Logs**: Regularly review audit logs for suspicious activity

### For Developers

1. **Input Validation**: Always validate user input using Pydantic schemas
2. **SQL Injection**: Use SQLAlchemy ORM parameterized queries
3. **XSS Prevention**: Sanitize user-generated content before rendering
4. **CSRF Protection**: Implement CSRF tokens for state-changing operations
5. **Rate Limiting**: Use NeuroBus rate limiter to prevent abuse
6. **Token Authentication**: Verify Token signatures before processing
7. **Secrets Management**: Use environment variables, never hardcode secrets
8. **Dependency Scanning**: Regularly scan for vulnerable dependencies

## v6.0 Security Features

### Authentication & Authorization

- JWT Token-based authentication with refresh mechanism
- RBAC (Role-Based Access Control)
- API Key management for third-party integrations
- Token Wallet authentication for AI service calls

### Data Protection

- TLS for data in transit (terminated at the reverse proxy; see `docs/DEPLOYMENT.md` for setup guidance)
- HttpOnly session cookies with configurable `Secure`/`SameSite` flags (`app/config.py` `SESSION_COOKIE_*`)
- Stateless web JWT with one-time refresh-token rotation (`POST /api/auth/token/refresh`)
- Salted password hashing (`app/utils/password_hash.py`)
- **Known gap**: no at-rest / field-level database encryption for PII is implemented; at-rest protection currently depends on the deployment environment (disk / volume level)

### Mod Security

- Ed25519 signature verification for Mod packages against publisher keys built into the app (fail-closed; `app/infrastructure/mods/package.py`, `trusted_keys.py`)
- SHA-256 per-file and whole-package integrity hashing (`app/infrastructure/mods/package.py`)
- Entitlement gating for licensed Mods (protected packages require granted entitlements)
- **Known gap**: Mods are not executed in a sandbox — only install Mods from trusted sources

### Token Wallet Security

- Wallet-based billing enforcement for AI service calls (quota middleware)
- Rate limiting per user and per API (global, auth, and chat-stream limiters in `app/middleware/`)
- Login lockout after repeated failed attempts (defaults: 5 attempts / 15-minute lock; `app/application/account_security.py`)

### Audit & Compliance

- Application-level audit logging of security-relevant events (auth, licensing, NeuroBus safety domain) as JSON via `app/utils/audit_logger.py`, with optional JSONL persistence to `AUDIT_LOG_PATH` (`app/utils/audit_events.py`; **no-op when the env var is unset**); admin review via `GET /api/admin/audit-logs`
- Targeted masking of sensitive values: HTTP trace headers redacted (`app/middleware/neuro_http_trace.py`), phone numbers masked for display (`app/domain/value_objects/phone.py`) — there is **no systematic audit-record redaction pipeline**
- Compliance mainline is China's MLPS Level 2 (等保二级): remediation is **in progress and not yet certified** — control-by-control status lives in `docs/evidence/compliance-tier2/00-control-matrix.md`
- **Known gap**: no automated data-retention or data-deletion policy engine; data-subject rights APIs are not implemented (see Compliance below)

## Compliance

This section states actual status, not aspirations. The single source of truth for control-level status is `docs/evidence/compliance-tier2/00-control-matrix.md`.

### Data Privacy

- **Target framework: China's Personal Information Protection Law (PIPL).** Alignment is being worked as part of the MLPS Level 2 (等保二级) remediation; this is a direction, not a completed-compliance claim.
- Implemented today: RBAC with multi-tenant isolation, application-level audit logging of security-relevant events, targeted masking of sensitive values in logs and traces.
- **Known gaps** (tracked in the control matrix): data-subject export / deletion / correction APIs are not implemented — a former GDPR placeholder route was never functional and was removed on 2026-07-01; no consent-management mechanism; no automated data-retention / deletion policies.
- **GDPR: not claimed.** The product has no GDPR data-subject-rights capability, and there is no EU deployment target (the internationalization roadmap covers Southeast Asia only).

### Industry Standards

- OWASP Top 10: mitigations implemented for the key risks — SQLAlchemy parameterized queries, XSS sanitization middleware, CSRF protection, security headers, and global / auth rate limiting.
- ISO 27001: **roadmap item only** (12+ months out per the control matrix); no alignment is claimed today.

## Security Updates

Security updates are released as patch versions (e.g., 6.0.1, 6.0.2). We recommend always running the latest patch version for your major release.

Subscribe to our security advisories:
- GitHub Security Advisories: https://github.com/42433422/xcagi/security/advisories
- Security mailing list: security@example.com

---

*Last updated: 2026-07-01*  
*Version: 6.0.0*
