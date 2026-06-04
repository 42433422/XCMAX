# XCAGI 当前版本

> 本文件只记录**单一事实来源**。完整发布说明请看 [`CHANGELOG.md`](CHANGELOG.md)。  
> [`README.md`](README.md) 中的版本链接与本文件对齐；若出现不一致，**以本文件为准**并应通过 PR 修正 README。  
> **GitHub 主库默认分支**：**`master`**（`ai-excel-helper` 克隆后默认检出；CI/发版请以该分支与 `v10.*` 标签为准）。

---

## 📦 版本号（必须同步的锚点）

| 组件 | 版本 | 文件 |
|------|------|------|
| **XCAGI 总版本** | `10.0.0` | `CHANGELOG.md`、`README.md` |
| **Python 包（根）** | `10.0.0` | `pyproject.toml` |
| **Python 包（XCAGI 子树）** | `10.0.0` | `XCAGI/pyproject.toml` |
| **前端 SPA** | `10.0.0` | `frontend/package.json` |
| **桌面壳 npm** | `10.0.0` | `desktop/package.json` |
| **根级 npm（脚本/测试入口）** | `10.0.0` | `package.json` |
| **FastAPI 应用** | `10.0.0` | `app/version.py` + `app/fastapi_app/factory.py` |
| **Mod 依赖校验基线** | `10.0.0` | `app/infrastructure/mods/manifest.py` |

> 独立子工程保留自己的版本号：`MODstore/pyproject.toml`（`0.2.0`）、`MODstore/web/package.json`（`0.2.0`）、`MODstore/market/package.json`（`1.0.0`）。

## 🎯 当前定位（v10.0）

**跨平台企业 AI 员工桌面平台** — Windows/macOS 桌面版 + Web 版并行交付；**14 域 FastAPI 路由 SSOT**（`domains/*`）；已拆除 legacy/compat shim；**LLM Provider Registry** 与 SLO/Canary 闭环（见 [`docs/V10_ROADMAP_COMPLETE.md`](docs/V10_ROADMAP_COMPLETE.md)）。

## 🔗 相关文档

- 📝 [完整变更日志 CHANGELOG.md](CHANGELOG.md)
- 📖 [项目 README](README.md)
- 🏗️ [架构设计 docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 🗺️ [功能边界 docs/FEATURE_MAP.md](docs/FEATURE_MAP.md)
- 🧭 [迁移登记册 docs/MIGRATION_REGISTRY.md](docs/MIGRATION_REGISTRY.md)

## 🔄 版本同步约定（发版前自检）

当主版本号变更时，必须**同步修改**上表中的所有锚点文件，并在 `CHANGELOG.md` 顶部新增一节。建议在 PR 描述里贴一段 diff 摘要。

```bash
# 快速全仓对齐扫描（PowerShell）
rg -n --hidden -g '!node_modules' -g '!.archive' -g '!XCAGI/node_modules' \
  'version\s*=\s*"[0-9]' pyproject.toml XCAGI/pyproject.toml \
  frontend/package.json desktop/package.json package.json
rg -n 'version\s*=\s*"[0-9]' app/fastapi_app.py app/infrastructure/mods/manifest.py
python scripts/dev/verify_version_anchors.py
```

---

*最后更新：2026-06-04（v10.0.0 GA）*
