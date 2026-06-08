        # 每日编排员 (`daily-orchestrator`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/daily-orchestrator/`

        ## 职责

        每日定时：在独立分支上做最小修复（测试失败、日志告警），提交后进入「待邮件审批」队列；不触达用户数据目录与 ORM 模型定义。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`
- `dbops-engineer`

        ## 支持的 Handlers

        - `agent`：启动多步 agent 执行链

        ## Scope（核心文件范围）

        - `MODstore_deploy/market/src/**`
- `MODstore_deploy/modstore_server/**`
- `MODstore_deploy/tests/**`
- `MODstore_deploy/pyproject.toml`
- `yuangon/platform-core/daily-orchestrator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/daily-orchestrator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
