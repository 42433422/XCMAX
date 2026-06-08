        # 需求接入员 (`intake-dispatcher`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/intake-dispatcher/`

        ## 职责

        把外部输入（admin 自然语言下达、邮件、微信、客服工单、`mianshi/` 候补包、外部 webhook）规整成结构化 task，写入「待派发」队列；本岗只做语义解析与归一化，不直接选员工、不直接改业务代码。

        ## 上游依赖 (`depends_on`)

        - `doc-knowledge-curator`
- `task-router-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `agent`：启动多步 agent 执行链

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/eventing/intake/**`
- `MODstore_deploy/modstore_server/api/intake_api.py`
- `MODstore_deploy/modstore_server/webhook_events/intake/**`
- `mianshi/**`
- `yuangon/platform-core/intake-dispatcher/**`
- `MODstore_deploy/docs/yuangon-process-loop.md`

        ## 相关链接

        - manifest：`FHD/mods/_employees/intake-dispatcher/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
