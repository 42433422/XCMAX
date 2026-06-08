        # 测试质量运行员 (`test-qa-runner`)

        **area**：`quality-and-docs`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/quality-and-docs/test-qa-runner/`

        ## 职责

        负责全站测试套件的维护与执行：pytest 单元/集成测试、vitest 前端单测、Playwright E2E 测试、pre-commit hooks、覆盖率门禁、CI 工作流测试步骤、TypeScript 类型检查；输出测试结果并推动覆盖率达标；不修改被测源码。

        ## 上游依赖 (`depends_on`)

        - `modstore-backend-api`
- `vibe-coding-maintainer`
- `market-frontend-dev`
- `deploy-release-officer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `.cursor/contracts/error-code-map.yaml`
- `MODstore_deploy/tests/**`
- `vibe-coding/tests/**`
- `playwright.config.ts`
- `playwright.global-setup.ts`
- `MODstore_deploy/market/playwright.config.ts`

        ## 相关链接

        - manifest：`FHD/mods/_employees/test-qa-runner/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
