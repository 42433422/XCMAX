        # Runbook：Mods/ESkill 策展员 (`mods-and-eskill-curator`)

        ## 职责摘要

        管理 mods/ 目录中的 Mod 包与 eskill-prototype/ 原型；负责 .xcemp 上架审核流程与 ESkill 标准文档维护；所有上线须经 CI 审批，不直接操作生产 DB。

        ## 上游 Handoff 契约

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

        - `mods/**`
- `eskill-prototype/**`
- `MODstore_deploy/modstore_server/market_files/**`
- `MODstore_deploy/modstore_server/market_files/REGISTRY.json`
- `MODstore_deploy/modman/**`
- `ESkill.md`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:mods-and-eskill-curator` |
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
