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

## 🔒 v10 锁定规则

产品大版本锁死在 **v10**，全产品线版本锚点恒为 **`10.0.0`**。企业桌面端、AI 员工商店、移动 AI 协同 App 的后续交付只使用阶段名、channel、Git tag、`git_sha`、`sha256` 和制品 manifest 区分，不使用 `v10.1`、`v10.2`、`v10.3` 或 `v11` 作为路线承诺。

任何主版本解锁或锚点变更都必须先修改本文件，并同步 README、CHANGELOG、CI 发布约定和 `specs/product-lines-3-plus-2.md`；未完成同步前不得发布。

## 🎯 当前定位（v10.0）

**跨平台企业 AI 员工桌面平台** — Windows/macOS 桌面版 + Web 版并行交付，保留 Neuro-DDD + FastAPI + Mod 生态 + Token 认证钱包。

## 📱 各端交付等级（对外口径 SSOT）

| 端 | 等级 | 说明 |
|----|------|------|
| **Windows 桌面** | 签约级 | 主交付面 |
| **macOS 桌面** | 签约级 | arm64 + x64 dmg |
| **Web / 后端** | 签约级 | FastAPI + Vue SPA |
| **Android** | **签约级** | Kotlin Compose 双 SKU；登录（密码/OTP/扫码）· SSE 对话 · 4 Tab · 工作台 WebView |
| **iOS** | **工程级（编译验证级）** | SwiftUI 全量对标 Android；`ci-mobile-ios` 每次 push 跑 xcodegen + xcodebuild 免签编译验证；`release-ios` 签名→导出 ipa（含 TestFlight 钩子）流水线已就位。**待真机/上架**：填 `IOS_DIST_CERT_*`/`IOS_PROVISION_PROFILE_*`/`IOS_TEAM_ID` secret + APNs 密钥；占位 AppIcon 待替换正式图标。见 `mobile-ios/README.md`「发版与签名」 |
| **HarmonyOS（鸿蒙）** | **工程级（离线构建级）** | ArkTS 全量对标 Android；`hvigor assembleHap` 离线可构建；`release-harmony` 经 `configure-harmony-signing.sh` 注入华为签名 secret→产出签名 HAP 的发版链路已就位。**待上架**：填 `HARMONY_SIGN_*` secret（.p12/.cer/.p7b + 口令）+ AppGallery 账号 + DevEco runner。见 `mobile-harmony/docs/BUILD_HARMONY.md`「生产签名」 |

声称 vs 实测差距见 [`docs/CLAIMED_VS_ACTUAL.md`](docs/CLAIMED_VS_ACTUAL.md)。

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

*最后更新：2026-06-17（v10 锁定 · 版本锚点恒 10.0.0）*
