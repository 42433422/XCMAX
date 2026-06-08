        # 推送更新员工 (`push-update-context-officer`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/push-update-context-officer/`

        ## 职责

        在合并、推送与发布前汇总当前 Git 状态与设备/部署档位；不直接执行生产发布，不修改业务源码。

        ## 上游依赖 (`depends_on`)

        - `deploy-release-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `shell_exec`：执行预批准的 shell 命令

        ## Scope（核心文件范围）

        - `.gitignore`
- `.gitleaks.toml`
- `.github/**`
- `MODstore_deploy/.gitignore`
- `MODstore_deploy/.github/**`
- `MODstore_deploy/git-push.sh`

        ## 相关链接

        - manifest：`FHD/mods/_employees/push-update-context-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
