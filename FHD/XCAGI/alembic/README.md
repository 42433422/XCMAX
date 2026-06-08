# Alembic（XCAGI 目录）

`XCAGI/alembic.ini` 的 `script_location` 已指向仓库根 [`../alembic`](../alembic)。**迁移版本文件唯一来源**为 `alembic/versions/`。

在 `XCAGI/` 下执行：

```bash
alembic -c alembic.ini current
alembic -c alembic.ini upgrade head
```

与在仓库根执行 `alembic -c alembic.ini ...` 等价（使用同一套 `env.py` 与 `versions/`）。

本目录下遗留的 `env.py` / `versions/` 仅为历史副本，**不应再新增修订**；新增迁移请只在仓库根 `alembic/versions/` 添加。
