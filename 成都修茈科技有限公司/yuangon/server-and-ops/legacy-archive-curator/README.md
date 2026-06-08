        # 工作区归档管理员 (`legacy-archive-curator`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/legacy-archive-curator/`

        ## 职责

        S-R R3 工作区与 legacy 归档：_archive/、FHD/.archive/、LEGACY_CLEANUP_TRACKING、xcmax-tree 排除项治理。

        ## 上游依赖 (`depends_on`)

        - `retention-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `_archive/**`
- `FHD/.archive/**`
- `FHD/docs/reports/LEGACY_CLEANUP_TRACKING.md`
- `scripts/cleanup_archive_secrets.py`
- `scripts/build-xcmax-tree-data.py`
- `yuangon/server-and-ops/legacy-archive-curator/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/legacy-archive-curator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
