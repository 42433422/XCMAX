        # 企业使用跟踪员 (`enterprise-adoption-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/enterprise-adoption-officer/`

        ## 职责

        跟踪 O6 企业使用阶段：租户激活、功能采纳、用量遥测与回访触发；与 user-customer-service-officer 分工（本岗偏数据与里程碑，客服偏交互）。

        ## 上游依赖 (`depends_on`)

        - `user-customer-service-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/app/**/telemetry/**`
- `FHD/app/**/crm/**`
- `MODstore_deploy/modstore_server/**/tenant**`
- `yuangon/platform-core/enterprise-adoption-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/enterprise-adoption-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
