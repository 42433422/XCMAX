# Runbook — Nginx 配置工程师

| 字段 | 值 |
|------|----|
| 员工 ID | `nginx-config-engineer` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

## 日常巡检

```bash
# 语法检查（在服务器上执行）
nginx -t

# 检查主站可达
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/api/health
```

## 异常处置

### 异常 1：nginx -t 报错

**修复**：根据错误行定位配置文件 → 修正语法 → 重新 `nginx -t` → `nginx -s reload`。

### 异常 2：502 Bad Gateway

**排查**：`upstream` 地址是否正确；上游服务是否在运行；`proxy_pass` 端口是否匹配。

### 异常 3：TLS 证书过期

**修复**：通知 `security-secrets-guard` 确认新证书路径 → 更新 `ssl_certificate` → `nginx -s reload`。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
