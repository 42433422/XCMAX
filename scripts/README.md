# 仓库脚本与临时工具

根目录下若长期堆积一次性 `.bat` / `.py` / 日志与样例数据，会让仓库难以浏览，也不利于 CI 与新人上手。

**约定（建议）**

- 新的**可重复使用的**启动脚本、迁移工具：优先放在对应子项目内（例如 [MODstore/start-modstore.bat](../MODstore/start-modstore.bat)）。
- 个人或实验用**临时脚本**：放在本目录 `scripts/` 下，并在文件名或本 README 中写一句用途与是否可删。
- 大体积样例、数据库导出、截图：不要提交到 Git；若必须共享，考虑 `misc/` + `.gitignore` 或外部网盘链接。

历史文件若已在根目录且被业务依赖，移动前请全局搜索引用并更新路径。

## 目录布局（`fix_` / `check_` / `final_`）

| 目录 | 用途 |
|------|------|
| [`ci/`](ci/) | CI/发版门禁（OpenAPI 一致性、Neuro 迁移阈值、覆盖规则、**Tier 1 文档路径**） |
| [`dev/diagnostics/`](dev/diagnostics/) | 本地 DB/API 探针（一次性排障） |
| [`dev/checks/`](dev/checks/) | 微信/模板等历史检查脚本 |
| [`db_ops/`](db_ops/) | 员工 manifest / DB 运维类可重复脚本 |
| [`debug/`](debug/) | 本地排障脚本（`debug_*` 等，2026-06-05 从 `scripts/` 根迁入） |
| [`_archived/`](_archived/) | 已退役的一次性 `fix_*` / `final_*` 迁移脚本，以及 2026-06 从根目录迁入的探针/冒烟脚本（`analyze_db.py`、`smoke_test.py`、`test_backend.py` 等 15 个） |

**禁止**在仓库根或 `scripts/` 根目录新增 `fix_*.py` / `check_*.py` / `final_*.py`（见 `.github/workflows/test.yml`）。

## Launchers

- [`launchers/test_port.ps1`](launchers/test_port.ps1) — PowerShell TCP 探测（默认 `127.0.0.1:8000`）；可用 `-TargetHost localhost -Port 8000` 等参数。

环境变量盘点见 [`docs/ENV_FILES.md`](../docs/ENV_FILES.md)。
