# Runbook — 安全密钥守卫

| 字段 | 值 |
|------|----|
| 员工 ID | `security-secrets-guard` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin（安全事件立即通知） |

## 日常巡检

```bash
# 依赖 CVE 扫描
pip-audit -r requirements.txt
pip-audit -r MODstore_deploy/modstore_server/requirements.txt

# 密钥目录权限检查
ls -la _local_secrets/

# 证书过期检查（替换为实际证书路径）
openssl x509 -enddate -noout -in /path/to/cert.pem
```

## 安全事件处置

### 事件 1：高危 CVE（CVSS ≥ 7.0）

1. **立即**通知 admin 和 `deploy-release-officer` 暂缓发布。
2. 确认受影响包和版本范围。
3. 生成升级方案（新版本号 + 兼容性说明）。
4. 由 `flask-entry-keeper` 或对应员工执行升级。

### 事件 2：secrets 疑似泄露

1. **立即**通知 admin。
2. 确认泄露范围（git history、日志）。
3. 吊销并重新生成受影响密钥。
4. **禁止**在此 Runbook 或任何输出中记录明文密钥。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
