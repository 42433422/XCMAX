        # Runbook：FHD 核心应用维护员 (`fhd-core-maintainer`)

        ## 职责摘要

        维护 FHD 宿主核心 app/ 与 tests/：应用服务、路由、NeuroBus 集成；产出经 CR Git 管线提交 PR，由 FHD test.yml 与 ci-auto-merge 门控。

        ## 上游 Handoff 契约

        ### handoff: test-qa-runner → 本岗
- **触发条件**：`employee.task.done:test-qa-runner`（pytest 全绿 + coverage gate 通过）
- **输入**：CI 测试报告路径、覆盖率摘要
- **门禁**：测试红灯时本岗不得继续；回滚上游修复后重触发


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `FHD/app/**`
- `FHD/tests/**`
- `FHD/frontend/src/**`
- `FHD/pyproject.toml`
- `FHD/alembic/**`
- `FHD/docs/api/openapi.json`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:fhd-core-maintainer` |
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
