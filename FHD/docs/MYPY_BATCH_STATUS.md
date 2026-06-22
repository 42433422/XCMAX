# mypy 分批解禁状态（v10 线内）

配置源：[pyproject.toml](../pyproject.toml) `[tool.mypy]`。

## 当前策略（Phase 9 · 2026-06-13）

| 范围 | `ignore_errors` |
|------|-----------------|
| `tests.*` | **true**（保留） |
| `app.application.shipment*`、`app.domain.shipment.*`、`app.http.*`、`app.schemas.*`、`app.di.*`、`app.middleware.*` 等严格岛 | **false** |
| `app.services.*`、`app.fastapi_routes.*`、`app.infrastructure.*`、`app.db.*`、`app.security.*` 等宽口径 | **true**（待 B2–B4 逐批移除） |

`mypy app/ --no-error-summary` 在严格岛 + 宽口径 ignore 组合下 **绿**。

## 批次进度

| 批次 | 模块前缀 | 状态 |
|------|----------|------|
| B1 | `app.schemas.*` + 根模块 | 严格岛 |
| B2 | `app.security.*`、`app.db.*` | pending（仍宽口径 ignore） |
| B3 | `app.application.*`（除 shipment） | pending |
| B4 | `app.fastapi_routes.*` → `app.services.*` → `app.infrastructure.*` | pending |
| — | `app.mod_sdk.*`、`app.neuro_bus.*`、`app.routes.*`、`app.legacy.*` | **done** |
| tests | `tests.*` | ignore（保留） |

## inline `# type: ignore`

终态：**0**（`python3 scripts/dev/count_type_debt.py --max-type-ignore 0`）。

## Ruff ANN201

`[tool.ruff.lint] select` 含 `ANN`；公共 API 返回注解逐步补齐。

## 验收

```bash
cd FHD && python3 -m mypy app/ --no-error-summary
python3 scripts/dev/count_type_debt.py --max-type-ignore 0
```
