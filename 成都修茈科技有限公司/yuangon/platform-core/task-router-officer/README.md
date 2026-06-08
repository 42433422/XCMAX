        # 任务派发员 (`task-router-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/task-router-officer/`

        ## 职责

        把 `intake-dispatcher` 产出的结构化 task 派发给最合适的员工：基于 task.files_hint 与各员工 scope_globs 做匹配，命中多人时按仲裁规则选一人，无人匹配则升级 admin；本岗只做路由决策，不直接改业务代码、不执行任务。

        ## 上游依赖 (`depends_on`)

        - `intake-dispatcher`
- `employee-pack-curator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `agent`：启动多步 agent 执行链

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/eventing/router/**`
- `MODstore_deploy/modstore_server/api/router_api.py`
- `MODstore_deploy/modstore_server/scripts/build_routing_table.py`
- `MODstore_deploy/scripts/build_routing_table.py`
- `MODstore_deploy/docs/routing-table.md`
- `yuangon/platform-core/task-router-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/task-router-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
