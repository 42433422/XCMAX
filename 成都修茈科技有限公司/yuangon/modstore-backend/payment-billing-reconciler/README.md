        # 支付账单对账员 (`payment-billing-reconciler`)

        **area**：`modstore-backend`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/modstore-backend/payment-billing-reconciler/`

        ## 职责

        维护 MODstore 支付与账单模块：支付宝接口、订单管理、LLM 计费与订阅续费；对账只读为主，禁止直接写生产 DB。

        ## 上游依赖 (`depends_on`)

        - `security-secrets-guard`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/reconciliation.py`
- `MODstore_deploy/modstore_server/payment_api.py`
- `MODstore_deploy/modstore_server/payment_orders.py`
- `MODstore_deploy/modstore_server/payment_common.py`
- `MODstore_deploy/modstore_server/payment_*.py`
- `MODstore_deploy/modstore_server/payment_orders/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/payment-billing-reconciler/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
