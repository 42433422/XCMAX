        # 代码校验员工 (`code-validator`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/code-validator/`

        ## 职责

        对员工包体进行轻量校验，包括 manifest 合规性、Python 编译检查、包体一致性、独立可执行验证

        ## 上游依赖 (`depends_on`)

        - `sandbox-tester`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/validation/*`
- `yuangon/craft-workshop/code-validator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/code-validator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
