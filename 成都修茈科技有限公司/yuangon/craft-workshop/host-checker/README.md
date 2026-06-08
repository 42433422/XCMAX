        # 运维员工 (`host-checker`)

        **area**：`craft-workshop`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/craft-workshop/host-checker/`

        ## 职责

        探测宿主环境连通性，验证 LLM 密钥状态、API 版本兼容性与服务可达性

        ## 上游依赖 (`depends_on`)

        - `self-checker`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `workbench/sessions/*`
- `workbench/hostcheck/*`
- `yuangon/craft-workshop/host-checker/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/host-checker/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
