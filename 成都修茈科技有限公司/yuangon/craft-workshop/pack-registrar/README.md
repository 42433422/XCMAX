        # 打包登记员工 (`pack-registrar`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/pack-registrar/`

        ## 职责

        将员工包登记到 Catalog 目录，执行五维审核，生成 .xcemp 发布包

        ## 上游依赖 (`depends_on`)

        - `workflow-automator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `catalog/*`
- `yuangon/craft-workshop/pack-registrar/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/pack-registrar/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
