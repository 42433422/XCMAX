# 架构基线证据（Wave 0）

> v10 线内迭代 · Tier C 术债与高并发规划基线

## 文件

| 文件 | 生成命令 |
|------|----------|
| `route_inventory_baseline.json` | `python scripts/route_inventory_diff.py --json-out docs/evidence/arch/route_inventory_baseline.json` |
| `openapi_consistency_baseline.json` | `python scripts/check_openapi_consistency.py --json-out docs/evidence/arch/openapi_consistency_baseline.json` |
| `openapi_consistency_baseline.md` | 同上 `--md-out docs/evidence/arch/openapi_consistency_baseline.md` |
| `openapi_warning_baseline.json` | `python scripts/check_openapi_consistency.py --update-warning-baseline` |

## PR 门禁

每波路由变更后：

```bash
python scripts/route_inventory_diff.py --json-out /tmp/routes.json
# 与 baseline 对比 method+path 集合应为 0 diff
python scripts/check_openapi_consistency.py
python scripts/check_openapi_consistency.py --strict
python scripts/arch_fitness.py
```

## 关联

- [`docs/reports/services_import_matrix.md`](../../reports/services_import_matrix.md)
- [`docs/reports/COMPAT_LAYER_INVENTORY.md`](../../reports/COMPAT_LAYER_INVENTORY.md)
