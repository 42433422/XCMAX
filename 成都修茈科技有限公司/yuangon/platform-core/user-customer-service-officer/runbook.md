        # Runbook：用户客服员工 (`user-customer-service-officer`)

        ## 职责摘要

        面向终端用户的客服 AI 员工：绑定微信账号资产，在 Mac 本地协助沟通；首要能力为需求采集（询问客户需求并推送表单链接）。

        ## 上游 Handoff 契约

        ### handoff: intake-dispatcher → 本岗
- **触发条件**：`employee.task.done:intake-dispatcher`
- **输入**：待补充（参见 `yuangon/**/intake-dispatcher/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `customer-service/sessions/**`
- `customer-service/wechat/**`
- `FHD/mods/_employees/user-customer-service-officer/**`
- `yuangon/platform-core/user-customer-service-officer/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:user-customer-service-officer` |
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
