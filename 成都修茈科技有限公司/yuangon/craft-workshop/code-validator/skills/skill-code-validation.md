# ESkill：代码校验（skill-code-validation）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-code-validation` |
| 所属员工 | `code-validator` |
| 业务域 | 员工包体轻量校验 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
analyze_mod_employee_readiness(employee_pack)
→ manifest 合规性结果
→ mod_compileall_warnings(employee_pack)
→ Python 编译检查结果
→ _build_employee_pack_zip_with_source(employee_pack)
→ 构建 .xcemp 包
→ 子进程 validate(employee_pack)
→ 独立包验证结果
→ 输出校验报告
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "employee_id": "",
  "manifest_validation": { "status": "", "errors": [] },
  "python_compile": { "status": "", "warnings": [], "errors": [] },
  "consistency_check": { "status": "", "missing_skills": [], "missing_depends": [] },
  "xcemp_validation": { "status": "", "errors": [] },
  "summary": ""
}
```

**工具绑定**：
- analyze_mod_employee_readiness
- mod_compileall_warnings
- _build_employee_pack_zip_with_source
- validate（子进程）

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 任意工具调用抛出异常 |
| 结果不达标 | manifest_validation.status == "fail" 或 python_compile.status == "fail" 或 xcemp_validation.status == "fail" |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析校验失败原因 → 判断是 manifest 缺陷、编译错误还是包体不一致 → 生成修复建议。

**允许改动的模块白名单**：
- workbench/validation/* 配置文件

## 4. 固化

**验收标准**：
- [ ] manifest_validation.status == "ok"
- [ ] python_compile.status == "ok"
- [ ] consistency_check.status == "ok"
- [ ] xcemp_validation.status == "ok"
