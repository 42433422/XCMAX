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

- Sensitive data encryption at rest (AES-256-GCM)
- TLS 1.3 for data in transit
- Database encryption for PII (Personally Identifiable Information)
- Automatic session timeout and token rotation

### Mod Security

- Mod signature verification before installation
- Sandbox execution for untrusted Mods
- Permission-based Mod capabilities
- Mod version integrity checking

### Token Wallet Security

- Cryptographic signature for Token consumption
- Rate limiting per user and per API
- Usage anomaly detection
- Automatic lockout for suspicious activity

### Audit & Compliance

- Comprehensive audit logging for all operations
- GDPR compliance for EU users
- China Cybersecurity Law compliance
- Data retention and deletion policies

## Compliance

### Data Privacy

- Compliant with China's Personal Information Protection Law (PIPL)
- GDPR compliant for international deployments
- Data minimization principles
- User consent mechanisms

### Industry Standards

- OWASP Top 10 mitigation
- CIS Benchmarks for deployment
- ISO 27001 aligned security controls

## Security Updates

Security updates are released as patch versions (e.g., 6.0.1, 6.0.2). We recommend always running the latest patch version for your major release.

Subscribe to our security advisories:
- GitHub Security Advisories: https://github.com/42433422/xcagi/security/advisories
- Security mailing list: security@example.com

---

*Last updated: 2026-04-17*  
*Version: 6.0.0*
