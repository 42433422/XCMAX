        # iOS 发版员 (`mobile-ios-release-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/mobile-ios-release-officer/`

> **发版入口**：`FHD/mobile-ios/` 已落地，`FHD/.github/workflows/release-ios.yml` 负责 XcodeGen、模拟器构建、主线签名、IPA 导出与 App Store Connect 上传。

        ## 职责

        XCAGI iOS 渠道发布：主线上架、冻结兼容 SKU、Apple Developer profile、GitHub Secrets、XcodeGen 工程、签名、TestFlight / App Store Connect 上传与 release 门禁。

        ## 上游依赖 (`depends_on`)

        - `deploy-release-officer`
- `mobile-android-release-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/mobile-ios/**`
- `FHD/.github/workflows/release-ios.yml`
- `FHD/XCAGI/resources/**`
- `yuangon/platform-core/mobile-ios-release-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/mobile-ios-release-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)
        - Apple profile 自动化：`FHD/mobile-ios/scripts/create-app-store-profile.sh`
        - GitHub Secrets 同步：`FHD/mobile-ios/scripts/sync-ios-signing-secrets.sh`

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
