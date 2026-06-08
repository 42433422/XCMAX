        # 工作台 UX 设计员 (`workbench-ux-stylist`)

        **area**：`modstore-frontend`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/modstore-frontend/workbench-ux-stylist/`

        ## 职责

        专注维护 MODstore 工作台（Workbench）的 UX 与交互：画布、右侧边栏、工作台 Shell、AI 草稿审核组件与整体暗色设计系统；严格遵守 Vue 3 Only。

        ## 上游依赖 (`depends_on`)

        - `market-frontend-dev`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/market/src/views/workbench/**`
- `MODstore_deploy/market/src/components/workbench/**`
- `MODstore_deploy/market/src/components/admin/**`
- `MODstore_deploy/market/src/views/WorkbenchHomeView.vue`
- `MODstore_deploy/market/src/views/Admin*View.vue`
- `MODstore_deploy/market/src/views/admin/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/workbench-ux-stylist/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
