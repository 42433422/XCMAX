# 覆盖率分阶段提升与补测清单

本文档与根目录及 `XCAGI/pyproject.toml` 中的 `tool.coverage.report.fail_under` 对齐。

## 阶段目标

| 阶段 | `fail_under` 目标 | 说明 |
|------|-------------------|------|
| M1 | ~~40~~ | 已完成 |
| M2 | ~~55~~ | 已完成（扩展 `app/infrastructure/templates/*`） |
| **M3（当前）** | **70** | CI 窄包 + `app/application` / `app/domain/shipment` / `app/http` |
| M4（计划） | **80** | 逐步缩减 `omit`（`mod_sdk` / `shell` 最后） |

每进入下一阶段前：在本地与 CI 执行 `pytest tests/ --cov=app --cov-report=term-missing`，确认全绿后再改 `fail_under`。

## 补测优先级（建议顺序）

### P0 — 变更频繁、故障代价高

1. **`app/application/`** — 应用服务编排
2. **`app/neuro_bus/bus.py`** — 发布、队列满、可靠性层

### P1 — 领域与基础设施

3. **`app/domain/shipment`**
4. **`app/infrastructure/templates/`**
5. **`app/http/response_envelope.py`** — API 信封 SSOT

### P2 — 路由与集成

6. **`app/fastapi_routes/`** — RouteRegistry、冲突检测

## 配置位置

- 根目录：[`pyproject.toml`](../../pyproject.toml) → `[tool.coverage.report]` → `fail_under`
- CI：[`/.github/workflows/ci-cd.yml`](../../.github/workflows/ci-cd.yml) → `--cov-fail-under=70`

## pytest 与路径说明

```bash
CI_STABLE_ONLY=1 python -m pytest tests/ \
  --cov=app.neuro_bus --cov=app.middleware --cov=app.fastapi_routes \
  --cov=app.application --cov=app.domain.shipment --cov=app.http \
  --cov=app.utils.rate_limiter --cov=app.utils.password_hash --cov=app.config \
  --cov=app.db.session_cache --cov=app.utils.redis_cache \
  --cov=app.infrastructure.templates \
  --cov-fail-under=70
```

前端 Vitest 门槛：**50%** lines/statements（见 `frontend/vitest.config.js`；gate 聚焦已有单测的 constants/stores/utils/composables 子集，视图由 Playwright 覆盖）。

## 本地 pytest + coverage 排障（2026-06-07）

此前「66 个 SQLAlchemy 采集错误」实为 **pytest-cov 预 import + ORM 重复注册** 与 **缺失/错误 re-export**，并非数据库本身故障。

| 现象 | 根因 | 处理 |
|------|------|------|
| `Table 'ai_tool_categories' is already defined`（带 `--cov`） | cov 采集多次 import model | `tests/conftest.py` 顶部 `import app.db.models`；`pytest.ini` 勿设 `coverage:run source=app` |
| `No module named app.db.models.miniprogram` | 模型文件缺失 | `app/db/models/miniprogram.py` |
| `cannot import _business_mod_json_block` | `domains/db/*` 星号 export 不含 `_` 前缀 | `domains/db/{base,queries,writes,product_queries}.py` 显式 mirror |
| 未落地模块 `ImportError` | coverage ramp 超前 | `tests/conftest.py` → `collect_ignore` |

本地验证（2026-06-07）：`1733` 用例可采集；全量跑通约 **30%** 窄包覆盖率（M3 70% 门槛仍待补测）。
