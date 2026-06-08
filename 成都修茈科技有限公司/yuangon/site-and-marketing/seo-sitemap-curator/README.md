        # SEO 站点地图管理员 (`seo-sitemap-curator`)

        **area**：`site-and-marketing`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/site-and-marketing/seo-sitemap-curator/`

        ## 职责

        维护 xiu-ci.com 的 SEO 资产：sitemap.xml、robots.txt、百度/必应站长校验文件与结构化数据，确保收录与排名质量。

        ## 上游依赖 (`depends_on`)

        - `site-content-editor`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `sitemap.xml`
- `robots.txt`
- `baidu_urls.txt`
- `BingSiteAuth.xml`
- `baidu_verify_*.html`
- `yuangon/site-and-marketing/seo-sitemap-curator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/seo-sitemap-curator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
