# XCAGI 子工程

- **HTTP 入口**：[`run.py`](./run.py) → `app.fastapi_app:get_fastapi_app`，默认 **5000**。
- **Python 包 `app/`**：权威代码仅在仓库根 [`../app`](../app)。本地可在 `XCAGI/` 下生成指向它的 **junction / 符号链接**（便于 IDE 打开 `XCAGI/app`）：在仓库根执行 `powershell -File scripts/ensure_xcagi_app_link.ps1` 或 `bash scripts/ensure_xcagi_app_link.sh`。链接目录已被 [`XCAGI/.gitignore`](./.gitignore) 的 `/app` 规则忽略，勿提交到 **XCAGI** 子仓库。
- **前端**：仅维护仓库根 [`../frontend`](../frontend），见 [`FRONTEND.md`](./FRONTEND.md)。
- **数据库迁移（SSOT）**：修订文件**只**在仓库根 [`../alembic/versions/`](../alembic/versions/) 维护。本目录 [`alembic.ini`](./alembic.ini) 的 `script_location` 指向 `../alembic`，与在 `FHD/` 根执行 `alembic -c alembic.ini upgrade head` **完全等价**。详见 [`alembic/README.md`](./alembic/README.md) 与 [`../docs/DB_DUAL_TARGET_STRATEGY.md`](../docs/DB_DUAL_TARGET_STRATEGY.md)。**禁止**在 `XCAGI/alembic/versions/` 新增修订。

环境变量清单见仓库根 [`.env.example`](../.env.example)。
