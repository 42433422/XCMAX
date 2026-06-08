        # 产物生成员工 (`artifact-generator`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/artifact-generator/`

        ## 职责

        根据规划蓝图生成员工包产物（manifest、Python 实现、资产文件）；支持 LLM 驱动和资产驱动两种模式

        ## 上游依赖 (`depends_on`)

        - `employee-planner`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/artifacts/*`
- `yuangon/**`
- `yuangon/craft-workshop/artifact-generator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/artifact-generator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
