        # 联合 Catalog 策展员 (`ecosystem-joint-catalog-officer`)

        **area**：`partner-ecosystem`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/partner-ecosystem/ecosystem-joint-catalog-officer/`

        ## 职责

        O-B B2 生态联合 SKU · MODstore catalog 扩展 · 伙伴商品挂载与可见性策略。

        ## 上游依赖 (`depends_on`)

        - `employee-pack-curator`
- `modstore-backend-api`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/catalog*`
- `MODstore_deploy/modstore_server/**/packages.json`
- `MODstore_deploy/market/src/**/catalog*`
- `yuangon/partner-ecosystem/ecosystem-joint-catalog-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/ecosystem-joint-catalog-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
