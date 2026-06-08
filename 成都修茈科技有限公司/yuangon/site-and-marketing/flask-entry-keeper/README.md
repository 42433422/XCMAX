        # Flask 入口维护员 (`flask-entry-keeper`)

        **area**：`site-and-marketing`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/site-and-marketing/flask-entry-keeper/`

        ## 职责

        维护根目录 Flask 应用 app.py 的路由、表单处理、excel-to-ai 动态页与依赖 requirements.txt；对接静态站，不涉及 MODstore 或 Nginx 配置。

        ## 上游依赖 (`depends_on`)

        - `nginx-config-engineer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `app.py`
- `requirements.txt`
- `public/**`
- `uploads/**`
- `site/**`
- `excel-to-ai.html`

        ## 相关链接

        - manifest：`FHD/mods/_employees/flask-entry-keeper/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
