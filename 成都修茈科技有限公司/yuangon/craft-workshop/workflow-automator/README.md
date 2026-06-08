        # 流程自动化员工 (`workflow-automator`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/workflow-automator/`

        ## 职责

        为员工包创建自动化工作流（Skill 组），通过自然语言生成画布节点与连线

        ## 上游依赖 (`depends_on`)

        - `script-binder`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/workflows/*`
- `yuangon/craft-workshop/workflow-automator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/workflow-automator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
