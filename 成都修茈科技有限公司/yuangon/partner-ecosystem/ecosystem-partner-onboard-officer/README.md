        # 生态伙伴接入员 (`ecosystem-partner-onboard-officer`)

        **area**：`partner-ecosystem`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/partner-ecosystem/ecosystem-partner-onboard-officer/`

        ## 职责

        O-B B1 生态伙伴 onboarding · 租户隔离 · 联合 SSO 与伙伴档案建档。

        ## 上游依赖 (`depends_on`)

        - `modstore-backend-api`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/**/partner*`
- `MODstore_deploy/modstore_server/**/tenant**`
- `FHD/app/**/external_crm*`
- `yuangon/partner-ecosystem/ecosystem-partner-onboard-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/ecosystem-partner-onboard-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
