        # 质检员工 (`quality-validator`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/quality-validator/`

        ## 职责

        对生成的产物进行服务端校验，包括 manifest 合规性、Python 语法、资产完整性与一致性检查

        ## 上游依赖 (`depends_on`)

        - `artifact-generator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/validation/*`
- `yuangon/craft-workshop/quality-validator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/quality-validator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
