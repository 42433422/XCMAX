        # 六维质检员工 (`hex-quality-assessor`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/hex-quality-assessor/`

        ## 职责

        对制作车间产物执行六维质量评估与放行建议

        ## 上游依赖 (`depends_on`)

        - `quality-validator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/mods/_employees/hex-quality-assessor/**`
- `yuangon/craft-workshop/hex-quality-assessor/**`
- `workbench/sessions/*`
- `workbench/validation/*`

        ## 相关链接

        - manifest：`FHD/mods/_employees/hex-quality-assessor/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
