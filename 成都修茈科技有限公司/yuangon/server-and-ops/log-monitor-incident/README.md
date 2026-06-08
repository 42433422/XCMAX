        # 日志监控与事故响应员 (`log-monitor-incident`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/log-monitor-incident/`

        ## 职责

        归并和分析 xiu-ci.com 所有运行日志、测试报告与覆盖率数据；生成告警摘要并推动事故处置；不修改源码。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `shell_exec`：执行预批准的 shell 命令

        ## Scope（核心文件范围）

        - `coverage/**`
- `playwright-report/**`
- `test-results/**`
- `.cursor_*_log.txt`
- `.cursor/contracts/error-code-map.yaml`
- `MODstore_deploy/.pytest_cache/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/log-monitor-incident/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
