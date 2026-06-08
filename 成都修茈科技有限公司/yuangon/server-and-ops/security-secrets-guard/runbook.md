        # Runbook：安全密钥守卫 (`security-secrets-guard`)

        ## 职责摘要

        保护 xiu-ci.com 所有密钥、证书与敏感配置；进行依赖 CVE 扫描、CSP/Headers 审计；发现问题时告警，不自动修改生产配置。

        ## 上游 Handoff 契约

        （无上游依赖，直接接受 intake 派发）

        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |
| `shell_exec` | 执行预批准的 shell 命令 |

        ## 核心 Scope

        - `_local_secrets/**`
- `.cursor_admin_token.txt`
- `alipay_package/**`
- `requirements.txt`
- `MODstore_deploy/modstore_server/requirements*.txt`
- `MODstore_deploy/keys/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:security-secrets-guard` |
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
