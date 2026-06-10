# ESkill：员工包质量校验（skill-quality-validation）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-quality-validation` |
| 所属员工 | `quality-validator` |
| 业务域 | 员工包产物质量校验与一致性检查 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取产物路径 → 执行 validate_warnings 检查
→ 执行 mod_compileall_warnings（Python 语法）
→ 执行 employee_pack_consistency_warnings（一致性）
→ 汇总校验结果 → 输出校验报告与警告
```

**输出 schema**：
```json
{ "status": "ok | error", "manifest_valid": true, "python_valid": true, "assets_valid": true, "consistency_valid": true, "warnings": [], "report_path": "" }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | validate_warnings 或一致性检查抛出异常 |
| 结果不达标 | manifest_valid == false 或 consistency_valid == false |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析校验失败详情 → 定位根因 → 生成修复建议 → 标记严重程度。

## 4. 固化

**验收标准**：`status == ok` 且 `manifest_valid == true` 且 `consistency_valid == true` 且 `warnings` 中无严重级别项。
