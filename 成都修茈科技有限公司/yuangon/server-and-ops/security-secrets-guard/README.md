        # 安全密钥守卫 (`security-secrets-guard`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/security-secrets-guard/`

        ## 职责

        保护 xiu-ci.com 所有密钥、证书与敏感配置；进行依赖 CVE 扫描、CSP/Headers 审计；发现问题时告警，不自动修改生产配置。

        ## 上游依赖 (`depends_on`)

        - （无上游依赖）

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `shell_exec`：执行预批准的 shell 命令

        ## Scope（核心文件范围）

        - `_local_secrets/**`
- `.cursor_admin_token.txt`
- `alipay_package/**`
- `requirements.txt`
- `MODstore_deploy/modstore_server/requirements*.txt`
- `MODstore_deploy/keys/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/security-secrets-guard/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
