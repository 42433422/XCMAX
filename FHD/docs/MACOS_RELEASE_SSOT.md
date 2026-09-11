# macOS 发布交付 SSOT（唯一事实来源）

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「macos-release」域。**每次 macOS 发版必须复用本文件**：更新第 1–5 节事实，重跑第 6 节全部 Gate，无证据不得标 GREEN，CI 通过 ≠ 验收通过。
> 状态取值仅限：`GREEN`（有完整真机证据）/ `YELLOW`（部分证据或以替代证据佐证）/ `RED`（真机验证失败，须记录复现步骤+日志+截图）/ `UNKNOWN`（无法静态证明，须生成实机验收任务）。
> 判据协议：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；证据模板：[desktop-acceptance-template.md](e2e/templates/desktop-acceptance-template.md)。
> RED 处理规则：只修真正阻断闭环的问题，修复后重测，不得直接改状态。

## 1. 当前版本信息

| 字段 | 值 | 证据 |
|------|-----|------|
| 稳定产品版本 | `1.0.0.1` | [VERSION.md](../VERSION.md)（版本域 SSOT） |
| 工具链兼容版本 | `1.0.0`（npm/Electron/Apple 三段映射） | 同上 |
| 发布 SKU | `enterprise`（personal 冻结） | [download_release.json](../config/download_release.json) |
| 发布产物 gitSha | `99854233c5d4ea05a96b1f6ae1e3b7edfe03b526` | latest-mac.yml `buildSha`（= main 合并 #1713，2026-09-05） |
| manifest git_sha | `2e6f03bf67b88965e450721e5b8432ab6395782b`（= main 合并 #1685，2026-09-02） | manifest.json ⚠ 与构建 gitSha 不同（见 §7 偏差-1） |
| 构建时间 | `2026-09-04T16:48:33Z`（feed）/ 本机安装副本 `2026-09-07`（非发布产物，见 §7 偏差-3） | latest-mac.yml / build-info.json |
| release_train 内部流水 | `1.0.0.3`（服务器无 v1.0.0.2/3/4 目录，仅内部号） | [release_train.json](../config/release_train.json) |
| `release_ready` | `false` | download_release.json + manifest.json |

## 2. 构建产物（线上实测）

| 产物 | URL | 大小（字节） | 指纹 |
|------|-----|------------|------|
| DMG（arm64，官方下载） | `https://xiu-ci.com/xcagi-v1.0.0.1/enterprise/XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg` | 290,432,409 | SHA256 `7ab4fdc1de1974e69695fde08e82047b5a8eef9c01ecc15dfa8c360fb8a62796`（manifest） |
| ZIP（arm64，OTA 载荷） | `https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-1.0.0.1-mac-arm64.zip` | 257,302,899 | SHA512 `ma1SqVskHoL/O3e85w4OQ3jKpn40dUxCwoxDugI2WwMb1X1VvQhKxAjINvcRG/bYZKeDhZ4Xddu8wfAd22eMnA==`（latest-mac.yml，附 ed25519 二次签名） |

x64 dmg：download_release.json 声明 `mac_x64`，但 manifest 无 x64 条目——**x64 产物未进 manifest，按未发布对待**（偏差-4）。

## 3. 构建环境

| 字段 | 值 |
|------|-----|
| 构建 CI | GitHub Actions `macos-latest`，workflow [release-desktop-mac-ota.yml](../.github/workflows/release-desktop-mac-ota.yml)（`macos-ota` job） |
| 构建脚本 | `scripts/package/build-installer.sh <version> enterprise`（版本动态读 VERSION.md） |
| 代码签名 | Developer ID Application（Team `G26WSH472M`），证书 `CSC_LINK` secret；hardened runtime；时间戳 `timestamp.apple.com/ts01` |
| 公证 | `build/notarize.cjs`（afterSign），App Store Connect API（`APP_STORE_CONNECT_API_*` secrets） |
| 更新元数据签名 | Ed25519（`XCAGI_UPDATE_ED25519_PRIVATE_KEY`，`scripts/dev/sign_update_metadata.py`），公钥内置于 [desktop-config.ts](../desktop/desktop-config.ts) |
| 发布脚本 | [publish-macos-download-center.sh](../scripts/package/publish-macos-download-center.sh)（DMG 双目录落盘 + 远端 SHA256 核验 + manifest 生成 + latest-mac.yml 验签断言） |

## 4. 下载与更新服务

| 项 | 地址 |
|----|------|
| 官方下载页（版本化） | `https://xiu-ci.com/xcagi-v<version>/enterprise/` |
| 官方 manifest | `https://xiu-ci.com/xcagi-v<version>/manifest.json`（历史兜底 `/releases/stable/manifest.json`） |
| 自动更新 feed（mac） | `https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml` |
| 自动更新 feed（win） | `https://xiu-ci.com/releases/stable/enterprise/latest.yml` |
| 服务器 | nginx 本机直供：`/xcagi-v{version}/` → `/var/www/update/releases/stable/`；dl.xiu-ci.com(COS) 备用待启用 |
| 应用内 feed URL SSOT | [desktop-config.ts](../desktop/desktop-config.ts) `SKU_UPDATE_URL.enterprise` |

## 5. 测试机（当前实跑）

| 字段 | 值 |
|------|-----|
| 机型 / 芯片 | Mac mini (Mac16,10) / Apple M4 (arm64) |
| OS | macOS 26.3 (25D125) |
| 内存 / 可用磁盘 | 24 GB / 70 GB |
| 序列号 | LK7W1TVPX1 |
| 环境性质 | ⚠ **非干净环境**：开发机（有 Xcode/Python/仓库），userData `~/Library/Application Support/XCAGI/` 已有 ~11GB 历史数据与多份旧安装副本 |

## 6. Release Gate 状态（2026-09-11 实跑）

| # | Gate | 状态 | 现有证据 | 缺失证据 | 阻断 | 对应 PR | 下一步 |
|---|------|------|---------|---------|------|---------|--------|
| G1 | 构建（产物+身份） | YELLOW | feed/manifest/DMG 在线可下；buildSha=#1713；SHA256 实测一致 | manifest git_sha(#1685,09-02)≠构建 gitSha(#1713,09-05) 的构建 run 链接 | 无 | #1713 / #1685 | 记录 release run URL 与产物对应关系，修正 manifest 生成时点 |
| G2 | 干净环境安装 | YELLOW | 验收脚本真实下载→SHA256→挂载→安装 `~/Applications/acceptance/` 全链 PASS | 非干净机（dev 机+存量数据）；未在全新用户/VM 验证 | 无 | #1870 | 实机任务 T1：干净环境（新账户或 VM）重跑 |
| G3 | macOS 安全项 | 待实跑回填 | 服务器产物 TeamID G26WSH472M | — | — | — | — |
| G4 | 首次启动 | 待实跑回填 | — | — | — | — | — |
| G5 | 登录绑定 | UNKNOWN | 历史证据（旧版本） | 1.0.0.1 真机登录绑定截图/日志 | 无 | — | 实机任务 T2 |
| G6 | Mod / AI 员工加载 | 待实跑回填 | — | — | — | — | — |
| G7 | 真实业务任务 | UNKNOWN | 历史业务证据（旧版本 `docs/evidence/e2e/01~07-*.png`） | 1.0.0.1 真机业务用例证据 | 无 | — | 实机任务 T3 |
| G8 | 更新发现 | YELLOW | feed 可达+ed25519 签名字段存在；本版=最新无升级目标（协议 4.4 SKIP）；历史闭环 [desktop-ota-closed-loop-20260724](evidence/e2e/desktop-ota-closed-loop-20260724/) | 无更高版本可触发真实"发现" | 无 | #583 | 下次发版 T4 触发真实发现 |
| G9 | 更新安装 | YELLOW | 历史闭环：checkForUpdates+downloadUpdate 验签+提取 buildSha 一致；`quitAndInstall` 未执行 | 真机完整"重启安装"动作从未执行过 | 无 | #583 | T4：下版发后真机全链 OTA |
| G10 | 数据保留（升级后） | UNKNOWN | userData 备份目录存在；Windows 覆盖升级比对已落地 | macOS 覆盖升级数据保留比对脚本缺失（#1870 仅 Windows）；真机升级数据基线缺失 | 无 | #1870 | T5：补 macOS 覆盖升级验收（对齐 acceptance-windows.ps1） |
| G11 | 更新后重新执行业务 | UNKNOWN | — | 依赖 G9/G10 | 无 | — | T4/T5 后执行 |
| G12 | 重启 Mac 后核心功能复验 | UNKNOWN | — | 未执行真实重启（避免中断在用会话） | 无 | — | T6：发版后重启复验 |

## 7. 已知偏差与缺陷

1. **版本身份三分叉**：manifest git_sha `2e6f03bf`(09-02) / feed buildSha `99854233`(09-05) / 本机 `/Applications` 安装副本 `1532f843`(09-07，不在本地 main 历史，疑似本地开发构建)。发布产物以 feed buildSha 为准；`/Applications` 副本不是发布产物。
2. **`/Applications/XCAGI.app` spctl 报 `a sealed resource is missing or invalid`**：本地副本被改或本地构建签名不完整；与发布产物无关（以验收实例对新鲜 DMG 的 spctl 结果为准，见 G3）。
3. x64 dmg 在 download_release.json 声明但 manifest 无条目（§2）。
4. 仓库根 `release/VERSION`（=0.0.1）为 legacy 暂存目录，不在 version 域锚点内；版本域锚点 `FHD/release/VERSION`=1.0.0.1 已验证同步（`verify_version_anchors.py` OK）。

## 8. 实机验收任务（UNKNOWN 项 → 待执行）

| ID | 任务 | Gate | 环境 |
|----|------|------|------|
| T1 | 全新 macOS 用户账户（或干净 VM）跑 `acceptance-macos.sh`，验证无开发依赖 | G2 | 干净机 |
| T2 | 真机登录绑定（市场账号），截图+日志 | G5 | 任意真机 |
| T3 | 真机完成 1 单真实业务（订单/考勤/对话），按模板留证 | G7 | 任意真机 |
| T4 | 下次发版后：旧版真机→检查更新→下载→安装→观察期→复验 | G8/G9/G11 | 真机 |
| T5 | 对齐 Windows：macOS 覆盖升级数据保留比对（升级前业务基线→升级后比对） | G10 | 真机 |
| T6 | 重启 Mac 后复验登录/Mod/业务 | G12 | 真机 |

## 9. 发版复用 Runbook（每次 macOS 发版照此执行）

1. `VERSION.md` 升版 → `version_sync.py --apply` + `verify_version_anchors.py`；
2. CI `release-desktop-mac-ota` 构建+签名+公证+发布 → `publish-macos-download-center` 更新下载中心/manifest/feed；
3. 真机跑 `bash FHD/scripts/package/acceptance-macos.sh --version <v>`（下载→SHA256→签名→安装→冷启动→健康检查）；
4. 有新版本时真机走完整 OTA 链（G8→G12），按协议 4.1–4.2 判定；
5. 按模板填写 `FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本>-macos.md`，截图入 `assets/`；
6. 回填本文件 §1–§6；全部 Gate 无 RED 且 G1–G4 GREEN、G5–G12 无 UNKNOWN 遗留方可宣布闭环；
7. RED：只修阻断项→重测→重写状态，禁止直接改状态。
5. **dmg/manifest 漂移 live 实锤（2026-09-11）**：dmg 实测 293,401,820 B（09-05 重构建 `99854233c`）≠ manifest `7ab4fdc1…/290,432,409 B` → §6-G1「SHA256 实测一致」已失效，须重发布或重生成 manifest（修复归属本域，对应 Windows 域 B3）。
6. **x64 dmg live 404**（2026-09-11 探测）：`xcagi-v1.0.0.1/enterprise/XCAGI-Enterprise-1.0.0.1-mac-x64.dmg` → 404（偏差-4 的 live 确认）。
7. **隔离测试通道 latest.yml Ed25519 验签 INVALID**（2026-09-11，生产公钥实测）：双平台共用测试通道，需以正确密钥重签。
8. **本域缺回滚门**：Windows 域 G13（回滚/恢复）为交付目标强制项，建议本域补 G13 并列入 T 任务。
