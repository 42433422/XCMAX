        # 生态交付回传员 (`ecosystem-delivery-reporter`)

        **area**：`partner-ecosystem`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/partner-ecosystem/ecosystem-delivery-reporter/`

        ## 职责

        O-B B3 联合包交付遥测 · 里程碑回写 O-A CRM 快照 · 生态进度事件。

        ## 上游依赖 (`depends_on`)

        - `enterprise-adoption-officer`
- `deploy-release-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/**/production_line*`
- `MODstore_deploy/modstore_server/**/operations*`
- `FHD/app/**/telemetry/**`
- `yuangon/partner-ecosystem/ecosystem-delivery-reporter/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/ecosystem-delivery-reporter/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
