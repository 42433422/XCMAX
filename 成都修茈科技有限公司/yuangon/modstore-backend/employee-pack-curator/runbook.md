# Runbook — 员工包策展员

| 字段 | 值 |
|------|----|
| 员工 ID | `employee-pack-curator` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

## 日常巡检

```bash
cd MODstore_deploy

# 语法检查
python -m py_compile modstore_server/employee_executor.py
python -m py_compile modstore_server/employee_skill_register.py

# 员工包导出冒烟
python modstore_server/employee_pack_export.py --list

# 注册表一致性检查
python modstore_server/employee_skill_register.py --verify

# 文档一致性检查
# 对比员工包相关文档与代码实现是否同步
git diff --name-only HEAD~1 -- modstore_server/employee_*.py modstore_server/employee_pack_*.py modstore_server/employee_skill_register.py
# 若上述文件有变更，检查以下文档是否需要同步更新：
#   - docs/fhd-employee-composition.md
#   - docs/modstore/员工制作增强设计方案.md
#   - MODstore_deploy/docs/employee_publish_wizard.md
#   - docs/adr/0003-artifacts-bundles-employee-packs.md
```

## 异常处置

### 异常 1：.xcemp 导出失败

1. 检查 `employee_pack_export.py` 的员工定义 schema 是否合法。
2. 查看 `employee.yaml` 必填字段是否缺失。
3. 动态阶段：LLM 自动补全缺失字段建议。

### 异常 2：ESkill 固化失败

1. 检查 Sandbox 沙箱是否正常启动。
2. 验收标准是否全部通过（见 skill md 第 4 节）。
3. 手动将补丁 diff 和 trace 交 admin 确认。

### 异常 3：文档与代码不一致

1. 运行 `git diff --name-only HEAD~1 -- modstore_server/employee_*.py` 确认变更范围。
2. 对照 `skill-doc-ownership` 中列出的文档清单，逐一检查受影响章节。
3. 生成同步建议 diff，交 admin 审核后合并。
4. 若文档变更涉及架构决策，需同步更新 `docs/adr/0003-artifacts-bundles-employee-packs.md`。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
