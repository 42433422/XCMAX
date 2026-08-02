# XCAGI 当前版本

> 本文件是版本域的**单一事实来源（SSOT）**。完整发布说明见 [`CHANGELOG.md`](CHANGELOG.md)。
> 若 README、发布工作流或下载清单与本文件不一致，必须先修正再发布。

---

## 📦 稳定版本

| 口径 | 版本 | 用途 |
|------|------|------|
| **XCAGI 稳定产品版本** | `1.0.0.1` | 对外版本、发布目录、下载清单、Windows 文件/产品版本、Python/FastAPI、Android `versionName` |
| **工具链兼容版本** | `1.0.0` | npm/Electron、Dart/Flutter、iOS/macOS `MARKETING_VERSION` |

四段产品版本 `1.0.0.1` 是稳定上线版本的唯一对外口径。npm SemVer、Electron、Dart pub 和 Apple 市场版本只接受三段版本，因此这些锚点使用等价映射 `1.0.0`；它们不代表另一个产品版本。

## 🔗 必须同步的锚点

| 组件 | 版本 | 文件 |
|------|------|------|
| **Python 包（根）** | `1.0.0.1` | `pyproject.toml` |
| **Python 包（XCAGI 子树）** | `1.0.0.1` | `XCAGI/pyproject.toml` |
| **FastAPI 应用** | `1.0.0.1` | `app/fastapi_app/factory.py` |
| **Mod 依赖校验基线** | `1.0.0.1` | `app/infrastructure/mods/manifest.py` |
| **Android versionName** | `1.0.0.1` | Flutter Android Runner Gradle 配置 |
| **前端 SPA** | `1.0.0` | `frontend/package.json` |
| **桌面壳 npm** | `1.0.0` | `desktop/package.json` |
| **根级 npm** | `1.0.0` | `package.json` |
| **Flutter / Apple 市场版本** | `1.0.0` | `mobile-flutter-poc/pubspec.yaml`、`ios/Flutter/Version.xcconfig` |

> 独立子工程保留自己的包版本；其产品下载路径和发布清单仍必须引用稳定产品版本 `1.0.0.1`。

## 🔒 稳定版规则（本文件即动态 SSOT）

上表「稳定产品版本 / 工具链兼容版本」是现行口径；规则与脚本必须**动态读取本文件**，不得在 `.cursor/rules` 或其他说明里写死某一代版本号。所有新制品、下载清单、发布目录和对外说明必须使用上表产品版本；工具链内部按上表三段映射。构建号、Git SHA、SHA-256 和签名状态用于区分同一稳定版本下的不同构建。

历史制品、证据和发布记录属于历史事实，不回写、不伪造；不得把已退役口径当作新的稳定上线制品继续发布。

任何版本变更都必须先修改本文件，再执行 `version_sync.py --apply` / `verify_version_anchors.py`，并同步 README、CHANGELOG、CI 发布约定、下载清单和 `specs/product-lines-3-plus-2.md`；未完成同步前不得发布。

## 🎯 当前定位（1.0 稳定版）

**跨平台企业 AI 员工桌面平台** — Windows/macOS 桌面版 + Web 版并行交付，保留 Neuro-DDD + FastAPI + Mod 生态 + Token 认证钱包。

## 📱 各端交付等级（对外口径 SSOT）

| 端 | 等级 | 说明 |
|----|------|------|
| **Windows 桌面** | 签约级 | 主交付面 |
| **macOS 桌面** | 签约级 | arm64 + x64 dmg |
| **Web / 后端** | 签约级 | FastAPI + Vue SPA |
| **Android** | **实验骨架·非签约级** | Flutter 主线已具备登录、SSE 对话、4 Tab、审批和通知；真机二维码/深链、真实审批与签名发布证据未闭环 |

声称 vs 实测差距见 [`docs/CLAIMED_VS_ACTUAL.md`](docs/CLAIMED_VS_ACTUAL.md)。

## 🔗 相关文档

- [完整变更日志 CHANGELOG.md](CHANGELOG.md)
- [项目 README](README.md)
- [架构设计 docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [功能边界 docs/FEATURE_MAP.md](docs/FEATURE_MAP.md)
- [迁移登记册 docs/MIGRATION_REGISTRY.md](docs/MIGRATION_REGISTRY.md)

## 🔄 版本同步约定（发版前自检）

```bash
python scripts/dev/version_sync.py --apply
python scripts/dev/verify_version_anchors.py
```

---

*最后更新：2026-08-03（稳定产品版本 1.0.0.1；工具链映射 1.0.0）*
