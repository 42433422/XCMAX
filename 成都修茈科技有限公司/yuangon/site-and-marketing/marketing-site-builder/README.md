        # 营销站点构建员 (`marketing-site-builder`)

        **area**：`site-and-marketing`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/site-and-marketing/marketing-site-builder/`

        ## 职责

        维护 marketing-site/ Nunjucks 模板与构建脚本（build.mjs、package.json）；与根静态站 site-content-editor 分工：本岗只管独立营销站子项目，不碰 MODstore 与市场 Vue 源码。

        ## 上游依赖 (`depends_on`)

        - `site-content-editor`
- `seo-sitemap-curator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `marketing-site/**`
- `yuangon/site-and-marketing/marketing-site-builder/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/marketing-site-builder/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
