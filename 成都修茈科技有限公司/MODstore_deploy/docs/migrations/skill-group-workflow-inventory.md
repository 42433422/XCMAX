# Skill 组 ↔ 工作流：兼容矩阵与引用盘点（阶段 0）

本文档支撑「制作 Skill 组替代工作流」迁移；物理表仍以 `workflows` / `workflow_*` 为主（路径 A）。

## 语义

| 概念 | 说明 |
|------|------|
| 画布 Skill 组 | 对外 intent：`skill`（原 `workflow`，仍兼容解析） |
| 容器行 | `workflows` 表；可选列 `kind='skill_group'`（新建画布） |
| 脚本工作流 | `script_workflows`，与画布分流；`execution_mode=script` |

## API：intent / 字段

| 位置 | 旧值 | 新值（规范） | 兼容 |
|------|------|--------------|------|
| `POST /api/workbench/sessions` body.intent | `workflow` | `skill` | 服务端将 `workflow` 规范为 `skill` |
| `WorkbenchResearchBody.intent` | `workflow` | `skill`（默认） | 同上 |
| 会话 artifact | `workflow_id` | 增加 `skill_group_id`（同 id） | 旧键保留 |
| | `workflow_name` | 增加 `skill_group_name` | 旧键保留 |

## 前端

| 位置 | 说明 |
|------|------|
| `WorkbenchHomeView` | `composerIntent` 默认 `skill`；`workflow` 仅缓存兼容 |
| `UnifiedWorkbenchView` | URL `focus=skill` 映射画布面板；`focus=workflow` 仍可用 |
| 路由 `workbench-workflow` | 重定向 `focus=skill` |

## DB 外键（指向 `workflows.id`）

- `workflow_nodes.workflow_id`
- `workflow_edges.workflow_id`
- `workflow_sandbox_runs.workflow_id`
- `workflow_executions.workflow_id`
- 及模型文件中其它 `ForeignKey("workflows.id")` 引用

路径 B（新表 `skill_groups`）未启用；见计划阶段 3。

## 客户端依赖（需自行确认）

- FHD / 宿主：manifest `workflow_id`、`workflow_employees` 字段名——本次不改 manifest 契约，仅工作台 API 别名。
- 自动化脚本：若硬编码 `intent=workflow`，仍可工作（服务端规范化）。

## 退役指标（阶段 5）

- 监控：`POST /api/workbench/sessions` 中 `intent=workflow` 占比 → 0
- 所有画布新建行的 `workflows.kind`（若启用）为 `skill_group`
