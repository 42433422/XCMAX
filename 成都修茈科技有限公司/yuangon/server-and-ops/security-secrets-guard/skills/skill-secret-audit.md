# ESkill：安全审计（skill-secret-audit）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-secret-audit` |
| 所属员工 | `security-secrets-guard` |
| 业务域 | 密钥与依赖安全 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
pip-audit 扫描依赖 → 读取证书过期日期 → 检查 _local_secrets/ 权限
→ 汇总风险报告（不含明文密钥）
```

**输出 schema**：
```json
{
  "status": "ok | warning | critical",
  "cve_count": { "high": 0, "medium": 0, "low": 0 },
  "cert_days_remaining": 90,
  "secret_dir_world_readable": false,
  "summary": "..."
}
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | pip-audit 命令失败 |
| 结果不达标 | `cve_count.high > 0` 或 `cert_days_remaining < 30` 或 `secret_dir_world_readable == true` |

## 3. 动态阶段

**预算**：2000 tokens，3 步。  
**约束**：输出中绝对禁止包含任何 secret 明文。  
**LLM 任务**：为高危 CVE 生成升级建议；为证书过期生成续签步骤。

## 4. 固化

**验收标准**：`status != critical` 且 admin 确认审计结果。
