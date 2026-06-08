        # Runbook：变更评审员 (`change-request-auditor`)

        ## 职责摘要

        对员工提交到「待邮件审批」队列的补丁/PR 做自动评审：跑测试 → 静态规则审 → 自动放行低风险 / 升级高风险给 admin；不直接改业务源码、不直接合并到主干。

        ## 上游 Handoff 契约

        ### handoff: test-qa-runner → 本岗
- **触发条件**：`employee.task.done:test-qa-runner`（pytest 全绿 + coverage gate 通过）
- **输入**：CI 测试报告路径、覆盖率摘要
- **门禁**：测试红灯时本岗不得继续；回滚上游修复后重触发

### handoff: employee-pack-quality-interviewer → 本岗
- **触发条件**：`employee.task.done:employee-pack-quality-interviewer`
- **输入**：待补充（参见 `yuangon/**/employee-pack-quality-interviewer/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: security-secrets-guard → 本岗
- **触发条件**：secrets 扫描通过（gitleaks clean）
- **输入**：扫描报告、豁免列表更新
- **门禁**：新增 secret 泄露阻断本岗所有操作


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |
| `agent` | 启动多步 agent 执行链 |

        ## 核心 Scope

        - `MODstore_deploy/modstore_server/api/change_request_api.py`
- `MODstore_deploy/modstore_server/eventing/audit/**`
- `MODstore_deploy/scripts/audit_*.py`
- `MODstore_deploy/docs/runbooks/change-request-audit.md`
- `yuangon/platform-core/change-request-auditor/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:change-request-auditor` |
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
