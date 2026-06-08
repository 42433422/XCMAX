        # 投资方只读门户员 (`ecosystem-investor-portal-officer`)

        **area**：`partner-ecosystem`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/partner-ecosystem/ecosystem-investor-portal-officer/`

        ## 职责

        O-B B4 投资方/伙伴只读 Portal · 里程碑与风险视图 · 进度只读 API。

        ## 上游依赖 (`depends_on`)

        - `market-frontend-dev`
- `ecosystem-delivery-reporter`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/market/src/**/admin/**`
- `MODstore_deploy/market/src/views/**/Investor*`
- `MODstore_deploy/modstore_server/**/investor*`
- `yuangon/partner-ecosystem/ecosystem-investor-portal-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/ecosystem-investor-portal-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
