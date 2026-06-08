        # Runbook：测试质量运行员 (`test-qa-runner`)

        ## 职责摘要

        负责全站测试套件的维护与执行：pytest 单元/集成测试、vitest 前端单测、Playwright E2E 测试、pre-commit hooks、覆盖率门禁、CI 工作流测试步骤、TypeScript 类型检查；输出测试结果并推动覆盖率达标；不修改被测源码。

        ## 上游 Handoff 契约

        ### handoff: modstore-backend-api → 本岗
- **触发条件**：`employee.task.done:modstore-backend-api`
- **输入**：API 端点变更 diff、OpenAPI schema 增量
- **门禁**：schema 破坏性变更需 change-request-auditor 审批后才继续

### handoff: vibe-coding-maintainer → 本岗
- **触发条件**：`employee.task.done:vibe-coding-maintainer`
- **输入**：待补充（参见 `yuangon/**/vibe-coding-maintainer/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: market-frontend-dev → 本岗
- **触发条件**：`employee.task.done:market-frontend-dev`
- **输入**：待补充（参见 `yuangon/**/market-frontend-dev/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: deploy-release-officer → 本岗
- **触发条件**：`ops.change_request.approved` → deploy 执行完成
- **输入**：部署 manifest、环境 URL、健康检查结果
- **门禁**：deploy 失败时自动 rollback；本岗等待 `/healthz` 返回 200


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `.cursor/contracts/error-code-map.yaml`
- `MODstore_deploy/tests/**`
- `vibe-coding/tests/**`
- `playwright.config.ts`
- `playwright.global-setup.ts`
- `MODstore_deploy/market/playwright.config.ts`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:test-qa-runner` |
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
