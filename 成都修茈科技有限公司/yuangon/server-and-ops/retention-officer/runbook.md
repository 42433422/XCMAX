        # Runbook：档案清理员 (`retention-officer`)

        ## 职责摘要

        周期性清理 workbench_script_runs、上传分片、旋转日志、知识缓存等过期文件，并把每次清理结果写回员工执行流水，作为「定时档案清理」岗位在员工大会上发言。

        ## 上游 Handoff 契约

        ### handoff: log-monitor-incident → 本岗
- **触发条件**：`employee.task.done:log-monitor-incident`
- **输入**：待补充（参见 `yuangon/**/log-monitor-incident/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |
| `shell_exec` | 执行预批准的 shell 命令 |

        ## 核心 Scope

        - `MODstore_deploy/modstore_server/workbench_script_runs/**`
- `MODstore_deploy/modstore_server/market_files/.tmp_chunks/**`
- `MODstore_deploy/modstore_server/webhook_events/**`
- `.cursor_*_log.txt`
- `.cursor_paths_check*.txt`
- `.cursor_*.txt`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:retention-officer` |
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
