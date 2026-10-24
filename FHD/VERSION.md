# XCAGI 当前版本

> 本文件是版本域的**单一事实来源（SSOT）**。完整发布说明见 [`CHANGELOG.md`](CHANGELOG.md)。
> 若 README、发布工作流或下载清单与本文件不一致，必须先修正再发布。

---

## 📦 当前构建候选与工具链映射

| 口径 | 版本 | 用途 |
|------|------|------|
| **XCAGI 稳定产品版本** | `1.0.0.6` | 对外版本、发布目录、下载清单、Windows 文件/产品版本、Python/FastAPI、Android `versionName` |
| **工具链兼容版本** | `1.0.0` | npm/Electron、Dart/Flutter、iOS/macOS `MARKETING_VERSION` |

四段产品版本 `1.0.0.6` 是本轮候选目标，尚未发布；已发布版本只认线上 `/download-release.json`。npm SemVer、Electron、Dart pub 和 Apple 市场版本只接受三段版本，因此这些锚点使用等价映射 `1.0.0`；它们不代表另一个产品版本。

## 🔗 必须同步的锚点

完整锚点以 [`verify_version_anchors.py`](scripts/dev/verify_version_anchors.py) 的 `ANCHORS` 为准，由 `version_sync.py --apply` 同步，禁止另维护重复版本表。独立子工程保留自己的包版本。

## 🔒 稳定版规则（本文件即动态 SSOT）

上表「稳定产品版本 / 工具链兼容版本」是现行口径；规则与脚本必须**动态读取本文件**，不得在 `.cursor/rules` 或其他说明里写死某一代版本号。所有新制品、下载清单、发布目录和对外说明必须使用上表产品版本；工具链内部按上表三段映射。构建号、Git SHA、SHA-256 和签名状态用于区分同一稳定版本下的不同构建。

每版 Windows x64、Mac arm64/x64 必须冻结同一 main 完整源码 SHA、产品版本与发布组合；各平台二进制 SHA-256 独立记录。先保留私有候选，再用原包跑实机安装、升级、业务、数据保留及失败恢复；证据齐全并获发布授权后才晋级原字节，禁止验收后重打包。
Windows 使用 `release-desktop` 的 `windows_installer_only=true,candidate_only=true`；Mac 使用 `release-desktop-mac-ota` 的 `candidate_only=true` 分别原生构建两架构。不得用会部署生产的大编排代替候选构建。
Windows 五模式必须同候选全部通过；未签名交付仍保持 stable OTA 关闭。历史制品、证据和发布记录不回写、不跨 SHA 继承；候选通过不等于客户验收或已发布。

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

相关说明：[README](README.md)、[CHANGELOG](CHANGELOG.md)、[架构](docs/ARCHITECTURE.md)、[能力边界](docs/FEATURE_MAP.md)、[迁移](docs/MIGRATION_REGISTRY.md)。

*最后更新：2026-10-13（统一桌面候选目标；工具链映射不变）*
