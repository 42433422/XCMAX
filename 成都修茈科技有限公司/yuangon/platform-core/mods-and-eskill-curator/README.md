        # Mods/ESkill 策展员 (`mods-and-eskill-curator`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/mods-and-eskill-curator/`

        ## 职责

        管理 mods/ 目录中的 Mod 包与 eskill-prototype/ 原型；负责 .xcemp 上架审核流程与 ESkill 标准文档维护；所有上线须经 CI 审批，不直接操作生产 DB。

        ## 上游依赖 (`depends_on`)

        - `employee-pack-curator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `mods/**`
- `eskill-prototype/**`
- `MODstore_deploy/modstore_server/market_files/**`
- `MODstore_deploy/modstore_server/market_files/REGISTRY.json`
- `MODstore_deploy/modman/**`
- `ESkill.md`

        ## 相关链接

        - manifest：`FHD/mods/_employees/mods-and-eskill-curator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
