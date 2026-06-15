# skill-static-audit

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-static-audit` |
| 所属员工 | `change-request-auditor` |
| 业务域 | 补丁静态规则审查 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**输入**：`change_request_id`，能拿到 `diff` + `author.employee_id`。  
**执行图**：
```
1. 加载 author 的 scope_globs / forbidden_globs
2. 对 diff 中每个修改文件 path：
   - path 命中 author.forbidden_globs → 返回 violation: forbidden_hit
   - path 不命中 author.scope_globs → 返回 violation: out_of_scope
3. 内容扫描（regex + AST）：
   - secrets：BEGIN PRIVATE KEY、AKIA[0-9A-Z]{16}、长度 ≥ 32 的疑似 token
   - SQL 高危：drop_column / DROP TABLE / DELETE FROM <t> 不带 WHERE
   - .env 直写：os.environ\[".*"\] *= 
   - hardcoded URL：含 staging / prod 的 https://
4. 行数 / 文件数 → 计 risk_score
5. 输出 audit_report.json
```

**输出 schema**：
```json
{
  "violations": [{"type": "forbidden_hit|out_of_scope|secret|sql_hazard", "path": "...", "evidence": "..."}],
  "risk_score": 0.0,
  "auto_approve_eligible": true|false,
  "recommend": "approve | request_changes | escalate"
}
```

## 2. 动态触发

- 静态规则解析失败（diff 不可解析 / 文件二进制）。
- LLM 反对静态结论（如 secret 是占位符）。

## 3. 动态阶段

预算 4000 token，5 步。LLM 任务：用 author 的 README 与 diff 上下文，判断"占位符 vs 真密钥"等边界。

## 4. 固化

把 admin 复审一致的规则沉淀到 `MODstore_deploy/scripts/audit_rules.json`。
