        # Vibe-Coding 维护员 (`vibe-coding-maintainer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/vibe-coding-maintainer/`

        ## 职责

        全权维护 vibe-coding 平台核心库（代码工厂、工作流工厂、自然语言解析、运行时校验器、Agent 层、安全模块）、配套测试、文档、示例代码；为 employee-pack-curator 提供稳定的 vibe_eskill_adapter 接口。

        ## 上游依赖 (`depends_on`)

        - （无上游依赖）

        ## 支持的 Handlers

        - `vibe_edit`：Vibe 代码编辑任务
- `direct_python`：直接执行 Python 片段
- `agent`：启动多步 agent 执行链
- `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `vibe-coding/src/vibe_coding/**`
- `vibe-coding/tests/**`
- `vibe-coding/scripts/**`
- `vibe-coding/pyproject.toml`
- `vibe-coding/setup.py`
- `vibe-coding/requirements*.txt`

        ## 相关链接

        - manifest：`FHD/mods/_employees/vibe-coding-maintainer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
