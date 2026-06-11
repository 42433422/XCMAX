# ESkill：Nginx 配置检查与更新（skill-nginx-config-check）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-nginx-config-check` |
| 所属员工 | `nginx-config-engineer` |
| 业务域 | Nginx 配置维护 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取目标 .conf 文件 → 解析修改需求 → 生成新配置 diff
→ nginx -t 模拟检查 → 输出结果
```

**输出 schema**：
```json
{ "status": "ok | error", "syntax_valid": true, "diff_lines": 0, "warnings": [] }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | `nginx -t` 返回非零退出码 |
| 结果不达标 | `syntax_valid == false` |

## 3. 动态阶段

**预算**：3000 tokens，4 步。  
**LLM 任务**：分析 `nginx -t` 错误信息 → 生成最小修复 diff。

## 4. 固化

**验收标准**：`syntax_valid == true` 且配置 reload 后服务可达。
