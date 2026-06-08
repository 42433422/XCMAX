        # Runbook：Vibe-Coding 维护员 (`vibe-coding-maintainer`)

        ## 职责摘要

        全权维护 vibe-coding 平台核心库（代码工厂、工作流工厂、自然语言解析、运行时校验器、Agent 层、安全模块）、配套测试、文档、示例代码；为 employee-pack-curator 提供稳定的 vibe_eskill_adapter 接口。

        ## 上游 Handoff 契约

        （无上游依赖，直接接受 intake 派发）

        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `vibe_edit` | Vibe 代码编辑任务 |
| `direct_python` | 直接执行 Python 片段 |
| `agent` | 启动多步 agent 执行链 |
| `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `vibe-coding/src/vibe_coding/**`
- `vibe-coding/tests/**`
- `vibe-coding/scripts/**`
- `vibe-coding/pyproject.toml`
- `vibe-coding/setup.py`
- `vibe-coding/requirements*.txt`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:vibe-coding-maintainer` |
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
