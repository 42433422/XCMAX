        # Runbook：员工包质询员 (`employee-pack-quality-interviewer`)

        ## 职责摘要

        对候选 employee_pack（.xcemp）做结构化「入职面试」：基于用户粘贴的 manifest 节选、同步测试日志或
沙盒 JSON，对照职责边界与平台契约给出录用/有条件录用/驳回结论与可执行修改清单。
不替代渗透测试、法务合规或正式 HR 录用；不编造未出现在输入中的文件路径、接口或密钥。

        ## 上游 Handoff 契约

        ### handoff: employee-interview-assistant → 本岗
- **触发条件**：`employee.task.done:employee-interview-assistant`
- **输入**：待补充（参见 `yuangon/**/employee-interview-assistant/runbook.md`）
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

        ## 核心 Scope

        - `yuangon/**/employee.yaml`
- `yuangon/**/prompts/*.md`
- `yuangon/**/skills/*.md`
- `yuangon/quality-and-docs/employee-pack-quality-interviewer/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:employee-pack-quality-interviewer` |
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
