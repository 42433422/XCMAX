# ESkill：打包登记（skill-pack-registration）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-pack-registration` |
| 所属员工 | `pack-registrar` |
| 业务域 | 员工包五维审核与 Catalog 注册 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
接收员工包 → 调用 run_package_audit_async → 执行五维审核
→ 调用 register_mod_employee_packs_async → 注册到 Catalog
→ 调用 build_employee_pack_zip → 生成 .xcemp 发布包
→ 输出注册结果
```

**输出 schema**：
```json
{ "status": "ok | error", "employee_pack_id": "", "audit_passed": true, "catalog_registered": true, "xcemp_path": "" }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 审核失败；注册失败；打包失败 |
| 结果不达标 | `audit_passed == false`；`catalog_registered == false` |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：修复审核不通过项；补全缺失的注册信息；重试打包。

## 4. 固化

**验收标准**：五维审核全部通过，Catalog 注册成功，.xcemp 发布包完整且可导入。
