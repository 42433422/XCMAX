        # Runbook：文档知识管理员 (`doc-knowledge-curator`)

        ## 职责摘要

        维护 xiu-ci.com 与 MODstore 平台的全部文档资产：README、ESkill.md、docs/ 目录、需求/方案 Markdown，以及 yuangon/ 各员工 README 同步；可调用 py-doc-generator.xcemp 与 project-doc-generator.xcemp 辅助生成文档；不修改源码。员工包专属文档（fhd-employee-composition.md、员工制作增强设计方案.md、employee_publish_wizard.md、0003-artifacts-bundles-employee-packs.md）由 employee-pack-curator 全权负责，本员工不主动修改。

        ## 上游 Handoff 契约

        ### handoff: mods-and-eskill-curator → 本岗
- **触发条件**：`employee.task.done:mods-and-eskill-curator`
- **输入**：待补充（参见 `yuangon/**/mods-and-eskill-curator/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: vibe-coding-maintainer → 本岗
- **触发条件**：`employee.task.done:vibe-coding-maintainer`
- **输入**：待补充（参见 `yuangon/**/vibe-coding-maintainer/runbook.md`）
- **门禁**：依赖完成前本岗不得继续

### handoff: employee-pack-curator → 本岗
- **触发条件**：`employee.task.done:employee-pack-curator`
- **输入**：待补充（参见 `yuangon/**/employee-pack-curator/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `doc_sync` | 文档同步任务 |
| `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |

        ## 核心 Scope

        - `README.md`
- `ESkill.md`
- `docs/**`
- `*.md`
- `*.docx`
- `yuangon/**/README.md`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:doc-knowledge-curator` |
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
