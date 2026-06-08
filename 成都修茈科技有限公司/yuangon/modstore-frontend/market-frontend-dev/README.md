        # 市场前端开发员 (`market-frontend-dev`)

        **area**：`modstore-frontend`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/modstore-frontend/market-frontend-dev/`

        ## 职责

        维护 MODstore 市场前端（非工作台视图）：路由视图、API 对接层、Pinia store、HTTP client；严格遵守 Vue 3 Only，禁止引入 React。

        ## 上游依赖 (`depends_on`)

        - `modstore-backend-api`
- `workbench-ux-stylist`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/market/src/views/*.vue`
- `MODstore_deploy/market/src/views/workflow/**`
- `MODstore_deploy/market/src/views/WorkbenchHomeView.vue`
- `MODstore_deploy/market/src/api.ts`
- `MODstore_deploy/market/src/infrastructure/http/client.ts`
- `MODstore_deploy/market/src/App.vue`

        ## 相关链接

        - manifest：`FHD/mods/_employees/market-frontend-dev/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
