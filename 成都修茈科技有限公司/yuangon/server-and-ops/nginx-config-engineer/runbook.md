        # Runbook：Nginx 配置工程师 (`nginx-config-engineer`)

        ## 职责摘要

        维护 xiu-ci.com 所有 Nginx 配置文件，包含虚拟主机、TLS、反代规则；不碰任何业务代码。

        ## 上游 Handoff 契约

        ### handoff: security-secrets-guard → 本岗
- **触发条件**：secrets 扫描通过（gitleaks clean）
- **输入**：扫描报告、豁免列表更新
- **门禁**：新增 secret 泄露阻断本岗所有操作


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |
| `shell_exec` | 执行预批准的 shell 命令 |

        ## 核心 Scope

        - `nginx-xiu-ci.conf`
- `nginx-xiu-ci-root.conf`
- `nginx-default.conf`
- `xiu-ci.com_nginx.zip`
- `_nginx_extract/**`
- `MODstore_deploy/docs/nginx-*.conf`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:nginx-config-engineer` |
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
