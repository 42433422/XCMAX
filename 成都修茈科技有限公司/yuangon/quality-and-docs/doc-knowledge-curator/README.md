        # 文档知识管理员 (`doc-knowledge-curator`)

        **area**：`quality-and-docs`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/quality-and-docs/doc-knowledge-curator/`

        ## 职责

        维护 xiu-ci.com 与 MODstore 平台的全部文档资产：README、ESkill.md、docs/ 目录、需求/方案 Markdown，以及 yuangon/ 各员工 README 同步；可调用 py-doc-generator.xcemp 与 project-doc-generator.xcemp 辅助生成文档；不修改源码。员工包专属文档（fhd-employee-composition.md、员工制作增强设计方案.md、employee_publish_wizard.md、0003-artifacts-bundles-employee-packs.md）由 employee-pack-curator 全权负责，本员工不主动修改。

        ## 上游依赖 (`depends_on`)

        - `mods-and-eskill-curator`
- `vibe-coding-maintainer`
- `employee-pack-curator`

        ## 支持的 Handlers

        - `doc_sync`：文档同步任务
- `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果

        ## Scope（核心文件范围）

        - `README.md`
- `ESkill.md`
- `docs/**`
- `*.md`
- `*.docx`
- `yuangon/**/README.md`

        ## 相关链接

        - manifest：`FHD/mods/_employees/doc-knowledge-curator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
