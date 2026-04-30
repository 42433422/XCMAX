# XCAGI 当前版本

> 本文件只记录**单一事实来源**。完整发布说明请看 [`CHANGELOG.md`](CHANGELOG.md)。

---

## 📦 版本号（必须同步的锚点）

| 组件 | 版本 | 文件 |
|------|------|------|
| **XCAGI 总版本** | `7.0.0` | `CHANGELOG.md`、`README.md` |
| **Python 包（根）** | `7.0.0` | `pyproject.toml` |
| **Python 包（XCAGI 子树）** | `7.0.0` | `XCAGI/pyproject.toml` |
| **前端 SPA** | `7.0.0` | `frontend/package.json` |
| **FastAPI 应用** | `7.0.0` | `app/fastapi_app.py`（`FastAPI(version=...)`） |
| **Mod 依赖校验基线** | `7.0.0` | `app/infrastructure/mods/manifest.py` |

> 独立子工程保留自己的版本号：`MODstore/pyproject.toml`（`0.2.0`）、`MODstore/web/package.json`（`0.2.0`）、`MODstore/market/package.json`（`1.0.0`）。

## 🎯 当前定位（v7.0）

**跨平台企业 AI 员工桌面平台** — Windows/macOS 桌面版 + Web 版并行交付，保留 Neuro-DDD + FastAPI + Mod 生态 + Token 认证钱包。

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
   frontend/package.json package.json
rg -n 'version\s*=\s*"[0-9]' app/fastapi_app.py app/infrastructure/mods/manifest.py
```

---

*最后更新：2026-04-29*
