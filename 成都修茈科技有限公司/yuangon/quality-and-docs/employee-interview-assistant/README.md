        # 员工信息访谈员 (`employee-interview-assistant`)

        **area**：`quality-and-docs`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/quality-and-docs/employee-interview-assistant/`

        ## 职责

        面向内部编制与协作场景：通过结构化提问与表单补全，帮助其他员工（及岗位包）补全元数据、能力说明、
运行依赖与风险字段；不替代 HR 正式录用流程，不存储敏感个人身份信息于未授权位置。

        ## 上游依赖 (`depends_on`)

        - `doc-knowledge-curator`
- `employee-pack-curator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `yuangon/**/README.md`
- `yuangon/**/employee.yaml`
- `yuangon/**/runbook.md`
- `yuangon/**/skills/*.md`
- `yuangon/**/tasks/**`
- `yuangon/quality-and-docs/employee-interview-assistant/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/employee-interview-assistant/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
