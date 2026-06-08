# XCAGI 当前版本

> 本文件只记录**单一事实来源**。完整发布说明请看 [`CHANGELOG.md`](CHANGELOG.md)。
> [`README.md`](README.md) 中的 **「版本与发布约定」** 与本文件以下各节对齐；若出现不一致，**以本文件为准**并应通过 PR 修正 README。

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
| **FastAPI 应用** | `10.0.0` | `app/fastapi_app/factory.py`（`FastAPI(version=...)`） |
| **Mod 依赖校验基线** | `10.0.0` | `app/infrastructure/mods/manifest.py` |

> 独立子工程保留自己的版本号：`MODstore/pyproject.toml`（`0.2.0`）、`MODstore/web/package.json`（`0.2.0`）、`MODstore/market/package.json`（`1.0.0`）。

## 🎯 当前定位（v10.0）

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
  frontend/package.json desktop/package.json package.json
rg -n 'version\s*=\s*"[0-9]' app/fastapi_app/factory.py app/infrastructure/mods/manifest.py
```

---

*最后更新：2026-04-30（补充 `desktop`/`package.json` 锚点行；与 README「版本与发布约定」交叉引用）*
