        # FHD 核心应用维护员 (`fhd-core-maintainer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/fhd-core-maintainer/`

        ## 职责

        维护 FHD 宿主核心 app/ 与 tests/：应用服务、路由、NeuroBus 集成；产出经 CR Git 管线提交 PR，由 FHD test.yml 与 ci-auto-merge 门控。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/app/**`
- `FHD/tests/**`
- `FHD/frontend/src/**`
- `FHD/pyproject.toml`
- `FHD/alembic/**`
- `FHD/docs/api/openapi.json`

        ## 相关链接

        - manifest：`FHD/mods/_employees/fhd-core-maintainer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
