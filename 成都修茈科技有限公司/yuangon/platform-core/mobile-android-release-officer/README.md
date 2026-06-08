        # Android 发版员 (`mobile-android-release-officer`)

        **area**：`platform-core`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/mobile-android-release-officer/`

        ## 职责

        P-S Android 渠道构建与发布：ci-mobile-android.yml、release-android.yml、APK/AAB 产出与 smoke。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`
- `deploy-release-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `FHD/mobile-android/**`
- `FHD/.github/workflows/ci-mobile-android.yml`
- `FHD/.github/workflows/release-android.yml`
- `release-apk/**`
- `yuangon/platform-core/mobile-android-release-officer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/mobile-android-release-officer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
