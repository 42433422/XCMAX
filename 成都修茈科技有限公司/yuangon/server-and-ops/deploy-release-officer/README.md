        # 发布部署主管 (`deploy-release-officer`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/deploy-release-officer/`

        ## 职责

        编排 xiu-ci.com 全站的构建与发布流程，包含 Docker 镜像、腾讯云 Pages 部署、脚本维护；不写业务逻辑。

        ## 上游依赖 (`depends_on`)

        - `nginx-config-engineer`
- `security-secrets-guard`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `shell_exec`：执行预批准的 shell 命令
- `ssh_exec`：通过 SSH 在远端执行命令

        ## Scope（核心文件范围）

        - `deploy/**`
- `scripts/**`
- `docker/**`
- `dist/**`
- `setup-alipay.sh`
- `stop_ports.py`

        ## 相关链接

        - manifest：`FHD/mods/_employees/deploy-release-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
