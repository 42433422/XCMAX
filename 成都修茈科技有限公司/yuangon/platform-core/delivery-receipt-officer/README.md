        # 交付签收员 (`delivery-receipt-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/delivery-receipt-officer/`

        ## 职责

        O8 里程碑签收与交付确认：对接 OPS_CLOSURE、签收工单、test-qa-runner 门禁与 receipt 工作流。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`
- `change-request-auditor`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/app/**/ops_closure/**`
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/**`
- `MODstore_deploy/modstore_server/**/delivery**`
- `yuangon/platform-core/delivery-receipt-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/delivery-receipt-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
