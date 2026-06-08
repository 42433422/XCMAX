        # 静态站内容编辑员 (`site-content-editor`)

        **area**：`site-and-marketing`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/site-and-marketing/site-content-editor/`

        ## 职责

        维护 xiu-ci.com 营销静态页面的内容、文案、图片引用与数据 JSON；不涉及服务器配置或后端逻辑。

        ## 上游依赖 (`depends_on`)

        - `seo-sitemap-curator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `index.html`
- `about.html`
- `cases.html`
- `services.html`
- `solutions.html`
- `news.html`

        ## 相关链接

        - manifest：`FHD/mods/_employees/site-content-editor/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
