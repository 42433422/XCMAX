# 仓库脚本与临时工具

根目录下若长期堆积一次性 `.bat` / `.py` / 日志与样例数据，会让仓库难以浏览，也不利于 CI 与新人上手。

**约定（建议）**

- 新的**可重复使用的**启动脚本、迁移工具：优先放在对应子项目内（例如 [MODstore/start-modstore.bat](../MODstore/start-modstore.bat)）。
- 个人或实验用**临时脚本**：放在本目录 `scripts/` 下，并在文件名或本 README 中写一句用途与是否可删。
- 大体积样例、数据库导出、截图：不要提交到 Git；若必须共享，考虑 `misc/` + `.gitignore` 或外部网盘链接。

历史文件若已在根目录且被业务依赖，移动前请全局搜索引用并更新路径。

## Archive（归档原则）

- 一次性 / 实验 / 迁移脚本（`import_*`、`verify_*`、`read_*`、`extract_*`、`analyze_*`、`find_*`、`copy_*`、`grid_*`、`migrate_*` 等）一律移入 `archive/<YYYY-MM>/`，顶层只保留被 CI / tests / 文档引用的长期工具。
- 允许目录：`tools/`、`launchers/`、`archive/`（与 `guard-temp-scripts` 门禁一致）。
- 归档前先全仓 grep 确认无业务代码 / workflow / tests 引用，再 `git mv`。

### Archive 2026-08

- 归档到 `archive/2026-08/`：`analyze_db.py`、`copy_label.py`、`detailed_test.py`、`extract_pdf.py`、`find_label.py`、`grid_analyzer.py`、`import_424_dbs.py`、`read_pdf.py`、`read_pdf.ps1`、`smoke_test.py`、`verify_db_copy.py`、`verify_import.py`
- 保留在顶层：`arch_fitness.py`、`build_mod.py`、`deploy.sh`、`health-check.sh`、`frontend_smoke_test.py`

## Launchers

- [`launchers/test_port.ps1`](launchers/test_port.ps1) — PowerShell TCP 探测（默认 `127.0.0.1:5000`）；可用 `-TargetHost localhost -Port 5000` 等参数。
