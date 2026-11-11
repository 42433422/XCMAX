# XCAGI 启动与运行资源

业务后端维护在 [`FHD/app`](../app)，前端维护在 [`FHD/frontend`](../frontend)。本目录保留桌面入口、运行资源与兼容命令。

| 内容 | 当前职责 |
|------|----------|
| `run.py` / `run_fastapi.py` | Electron 开发入口 / PyInstaller 打包入口；调用同一 `app.fastapi_app:create_fastapi_app` 工厂，保留桌面初始化和迁移 |
| `alembic.ini` | 指向 [`../alembic`](../alembic)，迁移只维护一份 |
| `mods/attendance-industry` | 考勤引擎与视图的维护正本；其他 Mod 规则见 [`mods_ssot.py`](../scripts/dev/mods_ssot.py) |
| `kb/fixes` / `kb/patterns` | 由现行知识检索器加载的运行知识；Odoo 来源边界材料仍由专用校验器验证 |
| `rasa/` | 转发 [`../rasa`](../rasa/README.md) 的训练命令，并保留已有模型发现路径 |
| `package.json` | 委派到真实前端的测试与检查命令，保留工具链版本镜像 |

启动、部署与打包命令复用 `FHD/` 根维护源；现行前端资产来源见 [`FRONTEND.md`](FRONTEND.md)。开发/桌面监听策略由应用启动参数和共享监听配置决定。

环境变量见 [`../.env.example`](../.env.example)，迁移规则见 [`ALEMBIC_MIGRATION_GUIDE.md`](../docs/guides/ALEMBIC_MIGRATION_GUIDE.md)。历史占位代码、静态副本和文档的恢复入口见 [`ARCHIVE_POINTER.md`](../../ARCHIVE_POINTER.md)。
