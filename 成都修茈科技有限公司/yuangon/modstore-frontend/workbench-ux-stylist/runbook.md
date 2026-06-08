        # Runbook：工作台 UX 设计员 (`workbench-ux-stylist`)

        ## 职责摘要

        专注维护 MODstore 工作台（Workbench）的 UX 与交互：画布、右侧边栏、工作台 Shell、AI 草稿审核组件与整体暗色设计系统；严格遵守 Vue 3 Only。

        ## 上游 Handoff 契约

        ### handoff: market-frontend-dev → 本岗
- **触发条件**：`employee.task.done:market-frontend-dev`
- **输入**：待补充（参见 `yuangon/**/market-frontend-dev/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `MODstore_deploy/market/src/views/workbench/**`
- `MODstore_deploy/market/src/components/workbench/**`
- `MODstore_deploy/market/src/components/admin/**`
- `MODstore_deploy/market/src/views/WorkbenchHomeView.vue`
- `MODstore_deploy/market/src/views/Admin*View.vue`
- `MODstore_deploy/market/src/views/admin/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:workbench-ux-stylist` |
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
