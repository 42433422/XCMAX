        # iOS 发版员 (`mobile-ios-release-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/mobile-ios-release-officer/`

> **注意**：`FHD/mobile-ios/` 目录规划中，`release-ios.yml` 待建。当前岗位处于待命状态。

        ## 职责

        P-S iOS 渠道发布（规划中）：TestFlight / App Store 工程、notarize 协同与 release 门禁。

        ## 上游依赖 (`depends_on`)

        - `deploy-release-officer`
- `mobile-android-release-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/mobile-ios/**`
- `FHD/.github/workflows/release-desktop.yml`
- `FHD/XCAGI/resources/**`
- `yuangon/platform-core/mobile-ios-release-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/mobile-ios-release-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
