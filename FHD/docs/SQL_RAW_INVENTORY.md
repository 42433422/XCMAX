# 原生 SQL 清单（FHD/app）

棘轮脚本：`python scripts/dev/count_raw_sql.py --verbose`

## 基线（2026-06）

| 指标 | 数量 |
|------|------|
| `text(f"...")` | 0（allowlist 外） |
| f-string SQL（SELECT/INSERT/…） | 0 |
| sqlalchemy `text()` 总计 | ~76 |
| DB `.execute(` | ~317 |

棘轮默认：`--max-text-f 0 --max-fstring-sql 0`（`count_raw_sql.py`）。

## Allowlist（bootstrap / vector，不计入棘轮）

- `app/db/init_db.py`
- `app/infrastructure/persistence/pg_vector_store.py`
- `app/infrastructure/persistence/sqlite_vector_store.py`
- `app/infrastructure/persistence/user_memory_vector_store.py`
- `app/security/license_store.py`

## 高风险（P0）

| 文件 | 问题 |
|------|------|
| `app/services/wechat_contact_service.py` | 动态表名 `msg_table` |
| `app/application/unit_products_import_app_service.py` | PRAGMA 列/表名 |
| `app/application/file_analysis_app_service.py` | 动态 products 表 |

## 高密度（P1 compat）

| 文件 | 分数 |
|------|------|
| `infrastructure/persistence/compat_db/writes.py` | ~41 |
| `infrastructure/persistence/compat_db/product_queries.py` | ~16 |
| `infrastructure/persistence/compat_db/queries.py` | ~8 |

路由层重复 SQL 已收敛至 `compat_db/`：`fastapi_routes/domains/product/compat_routes.py`、`xcagi_compat_product.py` 均调用 `writes.products_pg_*`。

## 迁移策略

1. 新代码：ORM / SQLAlchemy Core + bound params only
2. compat 读写：单点 `compat_db/`，路由调 port
3. CI：`count_raw_sql.py` 基线只降不升；Bandit B608 阻断
