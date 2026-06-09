# FHD 子目录 GitHub Actions（已迁根仓）

**CI SSOT 在仓根** [`.github/workflows/`](../../.github/workflows/)，本目录 workflow **不再由 GitHub 调度**。

| 历史文件 | 根仓 SSOT |
|----------|-----------|
| `ci-cd.yml` | [`fhd-ci-cd.yml`](../../.github/workflows/fhd-ci-cd.yml) |
| `release-gate-ci.yml` | [`fhd-release-gate-ci.yml`](../../.github/workflows/fhd-release-gate-ci.yml) |
| `ci-mobile-android.yml` | 见 [`android-build.yml`](../../.github/workflows/android-build.yml)（仓根优先） |
| `deploy.yml` | [`fhd-deploy.yml`](../../.github/workflows/fhd-deploy.yml) |
| `release-desktop.yml` | [`fhd-release-desktop.yml`](../../.github/workflows/fhd-release-desktop.yml) |
| `release-web.yml` | [`fhd-release-web.yml`](../../.github/workflows/fhd-release-web.yml) |
| `release-android.yml` | [`fhd-release-android.yml`](../../.github/workflows/fhd-release-android.yml) |
| 其余 `*.yml` | 同名加 `fhd-` 前缀，见根 `.github/workflows/` |
| `test.yml` | [`fhd-test.yml`](../../.github/workflows/fhd-test.yml) — 轻量 smoke（Ruff / 路由 pytest / 前端 lint+Vitest / 仓卫生） |

重新生成根 workflow：`python scripts/dev/publish_ci_workflows_to_root.py`

## Python 格式化 / lint

FHD CI 仅跑 **Ruff**（`ruff check` + `ruff format --check`）。**black / isort 不在 CI 中执行**（与 Ruff 规则冲突；勿重新加入除非有统一配置）。

Issue / PR 模板仍保留在本目录（`.github/ISSUE_TEMPLATE/`、`CONTRIBUTING.md`）。
