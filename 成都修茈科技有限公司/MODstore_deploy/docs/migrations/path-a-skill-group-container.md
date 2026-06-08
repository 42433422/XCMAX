# 路径 A：Skill 组容器（保留 `workflows` 表）

已实施：

- ORM [`Workflow`](../../modstore_server/models.py) 增加 **`kind`** 列（SQLite 启动时 `ALTER TABLE`），画布编排新建的 Skill 组写入 `kind='skill_group'`。
- 对外 API：`intent` 规范值 **`skill`**（仍接受 **`workflow`** 并映射为 `skill`）；artifact 增加 **`skill_group_id` / `skill_group_name`**（与 `workflow_id` / `workflow_name` 并存）。

未实施路径 B（新表 `skill_groups`）时，所有 `workflow_*` 外键保持不变；迁移脚本仅在选定路径 B 后编写。
