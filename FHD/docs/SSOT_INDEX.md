# SSOT 索引（唯一真相源登记表）

> **本文件为 SSOT 索引的 SSOT**。任何文档声称 SSOT 必须在此登记。
> 最后更新：2026-06-20

## 登记规则

1. 每个领域只允许一个 SSOT 文档
2. 新增 SSOT 声明必须先在此登记
3. `scripts/dev/docs_ssot_lint.py` 会扫描所有 md 文件中的 SSOT 声明，与本文件比对
4. 冲突时以本文件为准

## 领域 SSOT 登记表

| 领域 | SSOT 文档 | 说明 |
|------|----------|------|
| coverage（覆盖率） | [reports/COVERAGE_RAMP.md](reports/COVERAGE_RAMP.md) | 后端/前端覆盖率基线、目标、棘轮 floor |
| ci（CI/CD） | [../../docs/CI_SSOT.md](../../docs/CI_SSOT.md) | 根仓 .github/workflows/ 唯一调度入口 |
| mod（Mod 开发） | [guides/MOD_AUTHORING_GUIDE.md](guides/MOD_AUTHORING_GUIDE.md) | Mod 开发规范、mods/ 为唯一编辑源 |
| version（产品版本） | [VERSION.md](../VERSION.md) | v10 锁定、版本锚点 10.0.0 |
| route（路由） | [reports/WAVE2_ROUTE_SSOT.md](reports/WAVE2_ROUTE_SSOT.md) | RouteRegistry + mounts/* 路由 SSOT |
| git（Git 仓库） | [reports/GIT_WORKTREE_RECOVERY.md](reports/GIT_WORKTREE_RECOVERY.md) | 根仓 XCMAX/ 为 Git SSOT |
| mypy（类型检查） | [../pyproject.toml](../pyproject.toml) | [tool.mypy] 配置 |
| deps（依赖锁定） | [guides/DEPENDENCY_LOCKS.md](guides/DEPENDENCY_LOCKS.md) | Python/Node 依赖锁定策略 |
| auth（授权市场） | [guides/AUTH_MARKET_CONTRACT.md](guides/AUTH_MARKET_CONTRACT.md) | 授权与市场契约 |
| compliance（合规） | [evidence/compliance-tier2/00-control-matrix.md](evidence/compliance-tier2/00-control-matrix.md) | Tier2 合规控制矩阵 |
| ssot-framework（SSOT 框架） | [SSOT_FRAMEWORK.md](SSOT_FRAMEWORK.md) | 统一注册表 ssot.yaml + ssot_cli 编排器 |
| claimed-vs-actual（对外声称 vs 实测） | [CLAIMED_VS_ACTUAL.md](CLAIMED_VS_ACTUAL.md) | 对外声称 vs 实测对照，由 scripts/dev/gen_claimed_vs_actual.py 自动生成 |
| coverage-metrics（覆盖率唯一数字） | [../metrics/coverage-dual-summary.json](../metrics/coverage-dual-summary.json) | 覆盖率唯一数字 SSOT（committed_head / 棘轮 floor / 目标 / 退役口径） |

## 已退役 SSOT（指针化）

| 原文档 | 指向 | 原因 |
|--------|------|------|
| reports/COVERAGE_GAP.md | reports/COVERAGE_RAMP.md | 覆盖率 SSOT 收敛 |
| reports/FHD_DEPTH_ASSESSMENT_REVISED_2026-05-03.md（覆盖率章节） | reports/COVERAGE_RAMP.md | 覆盖率 SSOT 收敛 |
