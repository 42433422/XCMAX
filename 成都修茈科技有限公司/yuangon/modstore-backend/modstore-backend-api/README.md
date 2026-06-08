        # MODstore 后端 API 员 (`modstore-backend-api`)

        **area**：`modstore-backend`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/modstore-backend/modstore-backend-api/`

        ## 职责

        维护 MODstore 平台的 Flask 蓝图 API：工作台、市场目录、工作流、LLM 代理与 WebSocket 实时通道；不触碰前端 Vue 文件。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`
- `log-monitor-incident`
- `deploy-release-officer`
- `dbops-engineer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/workbench_api.py`
- `MODstore_deploy/modstore_server/market_api.py`
- `MODstore_deploy/modstore_server/market_catalog_api.py`
- `MODstore_deploy/modstore_server/script_workflow_api.py`
- `MODstore_deploy/modstore_server/realtime_ws.py`
- `MODstore_deploy/modstore_server/llm_api.py`

        ## 相关链接

        - manifest：`FHD/mods/_employees/modstore-backend-api/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
