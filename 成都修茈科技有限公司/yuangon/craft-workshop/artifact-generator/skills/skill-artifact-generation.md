# ESkill：员工包产物生成（skill-artifact-generation）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-artifact-generation` |
| 所属员工 | `artifact-generator` |
| 业务域 | 员工包产物生成与骨架搭建 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取规划蓝图 → 判断生成模式（资产驱动 / LLM 驱动）
→ 资产驱动：执行 run_asset_employee_scaffold_async
→ LLM 驱动：执行 generate_mod_employee_impls_async
→ 生成 manifest / 目录结构 / 资产文件
→ 输出产物路径与初步校验结果
```

**输出 schema**：
```json
{ "status": "ok | error", "artifact_paths": [], "generation_mode": "asset | llm", "validation_result": {}, "warnings": [] }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | scaffold 或 generate 函数抛出异常 |
| 结果不达标 | 产物路径为空或 manifest 缺失必填字段 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析蓝图与生成错误 → 补全缺失产物 → 修复 manifest 字段 → 重新生成。

## 4. 固化

**验收标准**：`status == ok` 且 `artifact_paths` 非空且 `validation_result` 通过。
