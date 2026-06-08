        # Runbook：任务派发员 (`task-router-officer`)

        ## 职责摘要

        把 `intake-dispatcher` 产出的结构化 task 派发给最合适的员工：基于 task.files_hint 与各员工 scope_globs 做匹配，命中多人时按仲裁规则选一人，无人匹配则升级 admin；本岗只做路由决策，不直接改业务代码、不执行任务。

        ## 上游 Handoff 契约

        ### handoff: intake-dispatcher → 本岗
- **触发条件**：`employee.task.done:intake-dispatcher`
- **输入**：待补充（参见 `yuangon/**/intake-dispatcher/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: employee-pack-curator → 本岗
- **触发条件**：`employee.task.done:employee-pack-curator`
- **输入**：待补充（参见 `yuangon/**/employee-pack-curator/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |
| `agent` | 启动多步 agent 执行链 |

        ## 核心 Scope

        - `MODstore_deploy/modstore_server/eventing/router/**`
- `MODstore_deploy/modstore_server/api/router_api.py`
- `MODstore_deploy/modstore_server/scripts/build_routing_table.py`
- `MODstore_deploy/scripts/build_routing_table.py`
- `MODstore_deploy/docs/routing-table.md`
- `yuangon/platform-core/task-router-officer/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:task-router-officer` |
        | 上游依赖未完成 | 等待 `employee.task.done:<dep>` 事件，不自行推进 |
        | scope 文件不存在 | 报告缺口，待确认后再执行，不编造路径 |
        | 版本锚点不对齐 | 运行 `verify_version_anchors.py`，修复后继续 |

        ## 验收检查清单

        - [ ] `employee.yaml.depends_on` 与 manifest 根级一致
        - [ ] `actions.handlers` 三方一致（yaml / manifest / `_DISPATCH`）
        - [ ] scope_globs 路径存在（或标注规划中）
        - [ ] `employee_pack_consistency_warnings` 无 handler warning
        - [ ] echo smoke 测试通过

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
