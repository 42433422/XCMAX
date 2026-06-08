        # Runbook：MODstore 后端 API 员 (`modstore-backend-api`)

        ## 职责摘要

        维护 MODstore 平台的 Flask 蓝图 API：工作台、市场目录、工作流、LLM 代理与 WebSocket 实时通道；不触碰前端 Vue 文件。

        ## 上游 Handoff 契约

        ### handoff: test-qa-runner → 本岗
- **触发条件**：`employee.task.done:test-qa-runner`（pytest 全绿 + coverage gate 通过）
- **输入**：CI 测试报告路径、覆盖率摘要
- **门禁**：测试红灯时本岗不得继续；回滚上游修复后重触发

### handoff: log-monitor-incident → 本岗
- **触发条件**：`employee.task.done:log-monitor-incident`
- **输入**：待补充（参见 `yuangon/**/log-monitor-incident/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: deploy-release-officer → 本岗
- **触发条件**：`ops.change_request.approved` → deploy 执行完成
- **输入**：部署 manifest、环境 URL、健康检查结果
- **门禁**：deploy 失败时自动 rollback；本岗等待 `/healthz` 返回 200

### handoff: dbops-engineer → 本岗
- **触发条件**：`employee.task.done:dbops-engineer`
- **输入**：待补充（参见 `yuangon/**/dbops-engineer/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `MODstore_deploy/modstore_server/workbench_api.py`
- `MODstore_deploy/modstore_server/market_api.py`
- `MODstore_deploy/modstore_server/market_catalog_api.py`
- `MODstore_deploy/modstore_server/script_workflow_api.py`
- `MODstore_deploy/modstore_server/realtime_ws.py`
- `MODstore_deploy/modstore_server/llm_api.py`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:modstore-backend-api` |
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
