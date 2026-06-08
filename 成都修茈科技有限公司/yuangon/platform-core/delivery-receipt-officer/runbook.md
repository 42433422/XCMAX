        # Runbook：交付签收员 (`delivery-receipt-officer`)

        ## 职责摘要

        O8 里程碑签收与交付确认：对接 OPS_CLOSURE、签收工单、test-qa-runner 门禁与 receipt 工作流。

        ## 上游 Handoff 契约

        ### handoff: test-qa-runner → 本岗
- **触发条件**：`employee.task.done:test-qa-runner`（pytest 全绿 + coverage gate 通过）
- **输入**：CI 测试报告路径、覆盖率摘要
- **门禁**：测试红灯时本岗不得继续；回滚上游修复后重触发

### handoff: change-request-auditor → 本岗
- **触发条件**：`employee.task.done:change-request-auditor`
- **输入**：待补充（参见 `yuangon/**/change-request-auditor/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `FHD/app/**/ops_closure/**`
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/**`
- `MODstore_deploy/modstore_server/**/delivery**`
- `yuangon/platform-core/delivery-receipt-officer/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:delivery-receipt-officer` |
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
