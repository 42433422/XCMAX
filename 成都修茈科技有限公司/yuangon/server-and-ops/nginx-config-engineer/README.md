        # Nginx 配置工程师 (`nginx-config-engineer`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/nginx-config-engineer/`

        ## 职责

        维护 xiu-ci.com 所有 Nginx 配置文件，包含虚拟主机、TLS、反代规则；不碰任何业务代码。

        ## 上游依赖 (`depends_on`)

        - `security-secrets-guard`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `shell_exec`：执行预批准的 shell 命令

        ## Scope（核心文件范围）

        - `nginx-xiu-ci.conf`
- `nginx-xiu-ci-root.conf`
- `nginx-default.conf`
- `xiu-ci.com_nginx.zip`
- `_nginx_extract/**`
- `MODstore_deploy/docs/nginx-*.conf`

        ## 相关链接

        - manifest：`FHD/mods/_employees/nginx-config-engineer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
