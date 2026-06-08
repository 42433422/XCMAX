# 脚本工作流 vs 画布 Skill 组

| | **画布 Skill 组** | **脚本工作流** (`script_workflows`) |
|--|---------------------|-------------------------------------|
| 入口 | 工作台意图 `skill`，编排生成节点图 | `/script-workflows/new` 或附件脚本会话 |
| 存储 | `workflows` + `workflow_nodes/edges`，`kind=skill_group` | `script_workflows` + Python 脚本正文 |
| 执行 | `workflow_engine` + `eskill` 等节点 | Agent 生成脚本、沙箱运行 |

二者并行：需要「可运行的一段程序」走脚本工作流；需要「多 Skill 编排与画布编辑」走画布 Skill 组。
