# mypy 分批解禁状态（v10 线内）

SSOT：[pyproject.toml](../pyproject.toml) `[tool.mypy]`。

## 当前严格岛

| 模块 | `ignore_errors` |
|------|-----------------|
| `app.application.shipment*` | false |
| `app.application.facades.shipment_event_primary` | false |
| `app.domain.shipment.*` | false |
| `app.http.*` | false |
| `app.schemas.*`、根模块 `app/*.py` | 基线检查（未列入宽口径 ignore） |

## 宽口径 ignore（待分批移除）

| 批次 | 模块前缀 | 状态 |
|------|----------|------|
| B1 | `app.schemas.*` + 根模块补注解 | pending |
| B2 | `app.security.*`、`app.db.*` | pending |
| B3 | `app.application.*`（除 shipment） | pending |
| B4 | `app.fastapi_routes.*` → `app.services.*` → `app.infrastructure.*` | pending |
| — | `app.mod_sdk.*`、`app.neuro_bus.*`、`app.routes.*`、`app.legacy.*` | **done（2026-06-13）** |
| tests | `tests.*` | ignore（保留） |

## inline `# type: ignore`

基线：**69** 处 / **41** 文件（`python scripts/dev/count_type_debt.py`）。

Top 文件：`domain/services/unified_intent_recognizer.py`、`extensions.py`、`utils/printer_automation.py`。

## 验收

```bash
cd FHD && mypy app/ --no-error-summary
python scripts/dev/count_type_debt.py --max-type-ignore 0  # 终态目标
```
