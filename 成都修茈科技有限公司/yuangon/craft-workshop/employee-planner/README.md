        # 规划设计员工 (`employee-planner`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/employee-planner/`

        ## 职责

        根据结构化需求规划员工包架构，拆分员工职责、脚本工作流与 Skill 组；输出一站式员工蓝图

        ## 上游依赖 (`depends_on`)

        - `intent-analyst`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/plans/*`
- `yuangon/craft-workshop/employee-planner/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/employee-planner/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
