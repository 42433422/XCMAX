# ESkill：原型推进到正式生产（skill-eskill-prototype-promote）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-eskill-prototype-promote` |
| 所属员工 | `mods-and-eskill-curator` |
| 业务域 | ESkill 原型从实验到正式生产的推进审核 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**触发条件**：`eskill-prototype/experiments/<id>/` 下存在 `hypothesis.md` 和 `prototype_logic.json`，且实验结果目录 `results/` 中有至少一条成功记录。

**执行逻辑**：
```
读取实验目录 → 校验 prototype_logic.json 结构完整性
→ 校验 hypothesis.md 与实验结果一致性
→ 检查无 secret 泄露 → 检查逻辑类型在允许列表中
→ 生成推进审核报告（通过/不通过 + 理由）
```

**输出 schema**：
```json
{
  "status": "approved | rejected | pending_fix",
  "experiment_id": "",
  "issues": [],
  "secret_leak": false,
  "logic_type_valid": true,
  "review_notes": "",
  "recommended_next": "employee-pack-curator | fix_and_retry | abandon"
}
```

**工具绑定**：
- 文件读取（`eskill-prototype/experiments/**`）
- JSON Schema 校验（`prototype_logic.json`）
- 正则扫描（secret 泄露检测）

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `issues` 非空；`secret_leak == true`；`logic_type_valid == false` |
| 场景特殊 | `prototype_logic.json` 包含未在允许列表中的 `type` 字段 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析实验结果与原型的差异，生成修复建议或适配方案。
**约束**：`secret_leak == true` 时立即 `status = rejected`，不进入修复流程。

## 4. 固化

**验收标准**：
- `status == approved`
- `logic_type_valid == true`
- `secret_leak == false`
- `employee-pack-curator` 完成注册表登记

**固化后动作**：
1. 实验目录标记为 `promoted`（创建 `results/promoted.flag`）
2. 通知 `employee-pack-curator` 执行注册
3. 通知 `doc-knowledge-curator` 同步文档
4. 在 runbook 动态阶段触发记录表中追加记录
