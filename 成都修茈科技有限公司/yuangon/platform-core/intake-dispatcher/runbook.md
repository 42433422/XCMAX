        # Runbook：需求接入员 (`intake-dispatcher`)

        ## 职责摘要

        把外部输入（admin 自然语言下达、邮件、微信、客服工单、`mianshi/` 候补包、外部 webhook）规整成结构化 task，写入「待派发」队列；本岗只做语义解析与归一化，不直接选员工、不直接改业务代码。

        ## 上游 Handoff 契约

        ### handoff: doc-knowledge-curator → 本岗
- **触发条件**：`employee.task.done:doc-knowledge-curator`
- **输入**：待补充（参见 `yuangon/**/doc-knowledge-curator/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: task-router-officer → 本岗
- **触发条件**：`employee.task.done:task-router-officer`
- **输入**：待补充（参见 `yuangon/**/task-router-officer/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |
| `agent` | 启动多步 agent 执行链 |

        ## 核心 Scope

        - `MODstore_deploy/modstore_server/eventing/intake/**`
- `MODstore_deploy/modstore_server/api/intake_api.py`
- `MODstore_deploy/modstore_server/webhook_events/intake/**`
- `mianshi/**`
- `yuangon/platform-core/intake-dispatcher/**`
- `MODstore_deploy/docs/yuangon-process-loop.md`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:intake-dispatcher` |
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
