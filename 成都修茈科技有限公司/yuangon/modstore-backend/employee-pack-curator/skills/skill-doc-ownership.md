# ESkill：文档所有权管理（skill-doc-ownership）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-doc-ownership` |
| 所属员工 | `employee-pack-curator` |
| 业务域 | 员工包相关文档的准确性维护与代码-文档同步 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**触发条件**：满足以下全部条件时走静态路径。
- 员工包相关代码文件发生变更（git diff 检测）
- 变更涉及 `employee_ai_*.py`、`employee_pack_*.py`、`employee_executor.py`、`employee_skill_register.py` 等 scope_globs 内文件
- 无历史已知异常 flag

**执行逻辑**：
```
检测 scope_globs 内代码变更 → 识别受影响的文档
→ 对比文档描述与代码实现是否一致
→ 不一致时生成同步建议（diff 格式）
→ 一致时输出通过报告
```

**输出 schema**：
```json
{
  "status": "ok | needs_sync | error",
  "checked_docs": ["doc_path_1", "doc_path_2"],
  "sync_suggestions": [
    {
      "doc_path": "",
      "section": "",
      "current_text": "",
      "suggested_text": "",
      "reason": ""
    }
  ],
  "metrics": {
    "docs_checked": 0,
    "inconsistencies_found": 0
  }
}
```

**工具绑定**：
- `git diff`（检测代码变更）
- 文件读取（对比文档与代码）

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 执行报错 | 文件读取失败、文档格式异常 | 即触发 |
| 结果不达标 | `metrics.inconsistencies_found > 0` 且自动修复失败 | 可配 |
| 场景特殊 | 新增代码文件但无对应文档说明 | 可配 |

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：`5000`（来自 employee.yaml `max_patch_budget_tokens`）
- 最大步数：`6`

**允许改动的模块白名单**：
- `docs/fhd-employee-composition.md`
- `docs/modstore/员工制作增强设计方案.md`
- `MODstore_deploy/docs/employee_publish_wizard.md`
- `docs/adr/0003-artifacts-bundles-employee-packs.md`
- `yuangon/modstore-backend/employee-pack-curator/README.md`

**LLM 补丁格式**：
```json
{
  "patch_id": "<uuid>",
  "base_version": "1.0.0",
  "proposals": [
    {
      "target_doc": "docs/fhd-employee-composition.md",
      "section": "B. 独立 employee_pack",
      "change_type": "update_description | add_section | remove_stale",
      "description": "同步 employee_pack 校验逻辑变更到文档",
      "text_diff": "..."
    }
  ]
}
```

## 4. 固化

**验收标准**：
- [ ] 所有受影响文档已与代码实现一致
- [ ] `metrics.inconsistencies_found == 0`
- [ ] 文档变更通过人工审核（admin 确认）
- [ ] Sandbox 环境无副作用外溢

**固化后动作**：
1. 生效 delta 写入 `skills/skill-doc-ownership-v2.md`
2. `employee.yaml` 中版本号递增
3. 旧版本保留（打 tag `deprecated`）供回滚

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| 文档-代码一致性率 | ≥ 95% |
| 静态路径成功率 | ≥ 90% |
| 动态触发率 | ≤ 15% |
| 文档同步延迟 | ≤ 24h（代码变更后） |
