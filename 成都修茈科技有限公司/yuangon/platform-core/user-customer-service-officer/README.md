        # 用户客服员工 (`user-customer-service-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/user-customer-service-officer/`

        ## 职责

        面向终端用户的客服 AI 员工：绑定微信账号资产，在 Mac 本地协助沟通；首要能力为需求采集（询问客户需求并推送表单链接）。

        ## 上游依赖 (`depends_on`)

        - `intake-dispatcher`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `customer-service/sessions/**`
- `customer-service/wechat/**`
- `FHD/mods/_employees/user-customer-service-officer/**`
- `yuangon/platform-core/user-customer-service-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/user-customer-service-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
