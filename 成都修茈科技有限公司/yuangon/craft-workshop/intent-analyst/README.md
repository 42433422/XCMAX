        # 需求分析员工 (`intent-analyst`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/intent-analyst/`

        ## 职责

        解析用户自然语言需求，提取结构化意图、领域关键词与建议能力；识别用户身份与权限

        ## 上游依赖 (`depends_on`)

        - （无上游依赖）

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/intent/*`
- `yuangon/craft-workshop/intent-analyst/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/intent-analyst/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
