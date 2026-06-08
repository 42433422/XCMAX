        # 测试员工 (`sandbox-tester`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/sandbox-tester/`

        ## 职责

        对员工工作流执行沙箱测试，包括结构校验与 Mock 执行验证

        ## 上游依赖 (`depends_on`)

        - `pack-registrar`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/sandbox/*`
- `yuangon/craft-workshop/sandbox-tester/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/sandbox-tester/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
