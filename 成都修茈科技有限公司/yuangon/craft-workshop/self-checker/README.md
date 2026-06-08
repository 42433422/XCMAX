        # 自检员工 (`self-checker`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/self-checker/`

        ## 职责

        执行员工包独立可执行自检，验证 .xcemp 包在隔离环境下可正常加载与运行

        ## 上游依赖 (`depends_on`)

        - `code-validator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/selfcheck/*`
- `yuangon/craft-workshop/self-checker/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/self-checker/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
