        # Runbook：生态伙伴接入员 (`ecosystem-partner-onboard-officer`)

        ## 职责摘要

        O-B B1 生态伙伴 onboarding · 租户隔离 · 联合 SSO 与伙伴档案建档。

        ## 上游 Handoff 契约

        ### handoff: modstore-backend-api → 本岗
- **触发条件**：`employee.task.done:modstore-backend-api`
- **输入**：API 端点变更 diff、OpenAPI schema 增量
- **门禁**：schema 破坏性变更需 change-request-auditor 审批后才继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `MODstore_deploy/modstore_server/**/partner*`
- `MODstore_deploy/modstore_server/**/tenant**`
- `FHD/app/**/external_crm*`
- `yuangon/partner-ecosystem/ecosystem-partner-onboard-officer/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:ecosystem-partner-onboard-officer` |
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
