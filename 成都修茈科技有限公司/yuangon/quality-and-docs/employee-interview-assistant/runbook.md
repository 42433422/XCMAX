# Runbook

1. 收到补全需求时，先确认目标 `pkg_id` 与现有 `yuangon/.../employee.yaml` 片段。
2. 列出缺口字段（scope、forbidden、depends_on、skills、SLA 等），逐项给出可粘贴的 YAML/Markdown 草案；Agent 岗位引导按 `skills/skill-employee-intake.md` 填能力四维（数据处理 / 流程自动化 / 决策逻辑 / 协作边界）。
3. 若涉及跨目录引用，检查 `depends_on` 是否在编制矩阵中存在对应岗位；README「运行依赖」表格见本目录 `README.md`。
4. 变更汇总写入 MR 描述；文档类变更可交给 `doc-knowledge-curator` 做最终排版。
