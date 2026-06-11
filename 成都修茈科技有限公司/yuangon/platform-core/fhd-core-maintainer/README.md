# FHD 核心应用维护员（fhd-core-maintainer）

维护 [`FHD/app/`](../../../FHD/app/) 与 [`FHD/tests/`](../../../FHD/tests/)：修复 CI 失败、实现遥测 backlog 任务、承接运营线 O7→P2 编码需求。

## 边界

| 允许 | 禁止 |
|------|------|
| `FHD/app/**`、`FHD/tests/**`、`pyproject.toml` | `MODstore_deploy/**`、营销仓、vibe-coding 源码 |

## 闭环

1. `plan_and_dispatch` / `marketing-content-loop` 同类 API 指定 `target_employee_id=fhd-core-maintainer`
2. 变更经 `cr_git_pipeline` → 分支 `employees/fhd-core-maintainer/cr-*`
3. PR 带 `auto-merge` + `ai-employee` → [`ci-auto-merge.yml`](../../../.github/workflows/ci-auto-merge.yml)

## 相关

- [`FHD/.github/workflows/fhd-core-coding-loop.yml`](../../../FHD/.github/workflows/fhd-core-coding-loop.yml)
- [`test-qa-runner`](../quality-and-docs/test-qa-runner/)（测试守门）
