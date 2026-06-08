        # 生态分润对账员 (`ecosystem-revenue-share-reconciler`)

        **area**：`partner-ecosystem`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/partner-ecosystem/ecosystem-revenue-share-reconciler/`

        ## 职责

        O-B B5 渠道分润 · 联合 GMV 对账 · 与 payment-billing-reconciler 分工（本岗偏伙伴分润）。

        ## 上游依赖 (`depends_on`)

        - `payment-billing-reconciler`
- `java-payment-bridge-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/**/reconciliation*`
- `MODstore_deploy/java_payment_service/**/Order*`
- `FHD/app/**/payment*`
- `yuangon/partner-ecosystem/ecosystem-revenue-share-reconciler/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/ecosystem-revenue-share-reconciler/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
