# ESkill：Mod 包审核（skill-mod-review）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-mod-review` |
| 所属员工 | `mods-and-eskill-curator` |
| 业务域 | Mod/.xcemp 包上架审核 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取待审核 .xcemp / mods 定义 → 校验 schema 必填字段
→ 检查 scope_globs/forbidden_globs 是否合理
→ 检查无明文 secret → 检查版本号格式
→ 生成审核报告（通过/不通过 + 理由）
```

**输出 schema**：
```json
{
  "status": "approved | rejected | pending_fix",
  "issues": [],
  "secret_leak": false,
  "schema_valid": true,
  "review_notes": ""
}
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `issues` 非空；`secret_leak == true`；`schema_valid == false` |

## 3. 动态阶段

**预算**：3000 tokens，4 步。  
**LLM 任务**：生成修复建议列表，返回给开发员工。  
**约束**：`secret_leak == true` 时立即 `status = rejected`，不进入修复流程。

## 4. 固化

**验收标准**：`status == approved`，CI 检查通过，`employee-pack-curator` 完成注册。
