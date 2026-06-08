        # 档案清理员 (`retention-officer`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/retention-officer/`

        ## 职责

        周期性清理 workbench_script_runs、上传分片、旋转日志、知识缓存等过期文件，并把每次清理结果写回员工执行流水，作为「定时档案清理」岗位在员工大会上发言。

        ## 上游依赖 (`depends_on`)

        - `log-monitor-incident`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `shell_exec`：执行预批准的 shell 命令

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/workbench_script_runs/**`
- `MODstore_deploy/modstore_server/market_files/.tmp_chunks/**`
- `MODstore_deploy/modstore_server/webhook_events/**`
- `.cursor_*_log.txt`
- `.cursor_paths_check*.txt`
- `.cursor_*.txt`

        ## 相关链接

        - manifest：`FHD/mods/_employees/retention-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
