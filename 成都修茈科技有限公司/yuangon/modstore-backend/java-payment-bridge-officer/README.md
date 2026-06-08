        # Java 支付桥接员 (`java-payment-bridge-officer`)

        **area**：`modstore-backend`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/modstore-backend/java-payment-bridge-officer/`

        ## 职责

        P-W MODstore Java 支付面：PaymentController、OrderService、PAYMENT_CONTRACT 与 Python 代理对齐。

        ## 上游依赖 (`depends_on`)

        - `modstore-backend-api`
- `payment-billing-reconciler`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/java/**`
- `MODstore_deploy/modstore_server/payment_*.py`
- `MODstore_deploy/docs/PAYMENT_CONTRACT.md`
- `yuangon/modstore-backend/java-payment-bridge-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/java-payment-bridge-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
