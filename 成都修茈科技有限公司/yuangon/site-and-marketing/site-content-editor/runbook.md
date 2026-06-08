        # Runbook：静态站内容编辑员 (`site-content-editor`)

        ## 职责摘要

        维护 xiu-ci.com 营销静态页面的内容、文案、图片引用与数据 JSON；不涉及服务器配置或后端逻辑。

        ## 上游 Handoff 契约

        ### handoff: seo-sitemap-curator → 本岗
- **触发条件**：`employee.task.done:seo-sitemap-curator`
- **输入**：待补充（参见 `yuangon/**/seo-sitemap-curator/runbook.md`）
- **门禁**：依赖完成前本岗不得继续


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `index.html`
- `about.html`
- `cases.html`
- `services.html`
- `solutions.html`
- `news.html`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:site-content-editor` |
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
