        # 小程序员工 (`miniapp-builder`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/miniapp-builder/`

        ## 职责

        为员工包生成配套脚本工作流（小程序），将自然语言需求转化为可执行的脚本逻辑

        ## 上游依赖 (`depends_on`)

        - `quality-validator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/scripts/*`
- `yuangon/craft-workshop/miniapp-builder/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/miniapp-builder/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
