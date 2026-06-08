        # 配置绑定员工 (`script-binder`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/script-binder/`

        ## 职责

        将生成的脚本工作流嵌入员工包，更新 manifest 能力声明与目录结构

        ## 上游依赖 (`depends_on`)

        - `miniapp-builder`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `yuangon/**`
- `yuangon/craft-workshop/script-binder/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/script-binder/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
