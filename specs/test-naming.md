# 活跃树测试命名规范

> SSOT：与 [specs/spec.md](spec.md)、[FHD/tests/README_COVERAGE.md](../FHD/tests/README_COVERAGE.md) 对齐。  
> 范围：FHD、MODstore_deploy、vibe-coding、packages（**不含** `_archive/`）。

## 文件命名

| 类型 | 模式 | 示例 |
|------|------|------|
| Python 单测 | `test_<domain>_<behavior>.py` | `test_shipment_app_service.py` |
| Python 路由冒烟 | `tests/routes/test_<domain>_routes.py`（**一文件一域**） | `test_inventory_routes.py` |
| Vitest | 与源码同目录 `<name>.test.ts` | `useChatView.test.ts` |
| Playwright E2E | `e2e/<flow>.spec.ts` | `login-flow.spec.ts` |
| vibe-coding Agent | `tests/agent/test_<component>.py` | `test_orchestration.py` |

**域（domain）** 与源码包对齐：`app/application/shipment_*` → `shipment`；`modstore_server/workflow_engine.py` → `workflow`。

## 禁止（新 PR）

- `test_coverage_ramp_phase*.py` 或任意 `test_coverage_ramp_*` 新文件
- 无域前缀的泛名新文件：`test_misc.py`、`test_utils.py`（根目录）
- 在 `_archive/**` 下新增或修改测试
- **`tests/routes/` 合并多模块**：一个文件不得覆盖 2 个及以上 FastAPI 路由域（如同时测 `inventory` + `purchase` + `customer`）。历史 `test_routes_<a>_<b>_…py` 仅允许删测例迁出，**禁止新增**同模式文件。
- **`FHD/app/**/*_v[0-9]+.py`**：禁止新增版本后缀源文件（pre-commit：`guard-no-new-v2-files`）；见 [`docs/MIGRATION_v2_DROP_PLAN.md`](../docs/MIGRATION_v2_DROP_PLAN.md)

修改**已有** ramp 文件内用例以修 bug 时允许，但不得扩大文件职责；应尽快迁出后删除该 ramp 文件。

## FHD 目录结构

| 目录 | 用途 |
|------|------|
| `tests/unit/<layer>/` | application / services / infrastructure 单测 |
| `tests/routes/` | FastAPI `TestClient` |
| `tests/integration/` | 多模块或 DB；`@pytest.mark.integration` |
| `tests/regression/` | 专名回归（可选） |
| `tests/neuro/` | NeuroBus 策略与路由 |

历史 ramp 文件见 [FHD/tests/unit/MIGRATION_RAMP.md](../FHD/tests/unit/MIGRATION_RAMP.md)；新用例只写入上表目录。

## 用例函数命名

- 描述行为：`test_<action>_<expected_outcome>`
- 避免无意义编号：`test_TC_VEC_EMB_001`（仅遗留向量测试文档对照时保留）

## 各子树入口

见根 [README.md](../README.md)「活跃测试入口」与 [FHD/tests/INDEX.md](../FHD/tests/INDEX.md)。

## `tests/routes/` 拆分（P0-5）

- 工具：`FHD/scripts/dev/split_routes_tests.py`（`--list` / `--dry-run` / `--apply`）
- 目标：与 `app/fastapi_routes/` 或 `domains/<x>/` **一一对应**；共享 fixture 迁到 `tests/routes/conftest.py` 或域内 `conftest.py`（T16 手工）
- 验收：`pytest tests/routes/ -q` 全绿；`test_routes_*` 巨文件数量单调递减

## PR 自检

- [ ] 新测试文件名符合上表
- [ ] 未新增 `test_coverage_ramp_phase*`
- [ ] `tests/routes/` 新文件未合并多路由域
- [ ] 未新增 `FHD/app/**/*_vN.py`
- [ ] 改动路由/应用服务时有对应 `routes/` 或 `unit/` 用例
- [ ] 覆盖率 PR 描述使用全量 `source=[app]` 口径（[`FHD/docs/reports/COVERAGE_RAMP.md`](../FHD/docs/reports/COVERAGE_RAMP.md) · `metrics/coverage-dual-summary.json`）
