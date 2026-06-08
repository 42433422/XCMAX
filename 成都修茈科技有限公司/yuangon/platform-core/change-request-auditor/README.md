        # 变更评审员 (`change-request-auditor`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/change-request-auditor/`

        ## 职责

        对员工提交到「待邮件审批」队列的补丁/PR 做自动评审：跑测试 → 静态规则审 → 自动放行低风险 / 升级高风险给 admin；不直接改业务源码、不直接合并到主干。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`
- `employee-pack-quality-interviewer`
- `security-secrets-guard`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `agent`：启动多步 agent 执行链

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/api/change_request_api.py`
- `MODstore_deploy/modstore_server/eventing/audit/**`
- `MODstore_deploy/scripts/audit_*.py`
- `MODstore_deploy/docs/runbooks/change-request-audit.md`
- `yuangon/platform-core/change-request-auditor/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/change-request-auditor/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
