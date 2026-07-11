# v10-C 移动 AI 协同 App · 验收底稿（2026-07-11）

> **状态：真机终验已签 → 见 [`v10-c-mobile-acceptance-2026-07-11-final.md`](./v10-c-mobile-acceptance-2026-07-11-final.md)**  
> **版本锚点**：10.0.0  
> **主线**：`FHD/mobile-flutter-poc`（Kotlin/iOS 原生已归档）

## 已落地（代码 / CI）

| 项 | 状态 |
|----|------|
| LAN/云路由 `preferCloudIfLanUnreachable` | 代码 + 单测文件 |
| 探索 Tab 审批入口 | 代码 + 真机「审批中心」可打开 |
| 通知诚实空态；审批驳回推送 | 代码 |
| CI/发版切 Flutter | `fhd-ci-mobile-flutter` / `fhd-release-android` |
| Release 签名接线 | 机上包 `CN=XCAGI` v2 已验（非 debug） |

## 真机终验（2026-07-11）

| 项 | 说明 |
|----|------|
| 小米 `25113PN0EC` USB | 登录态 / 四 Tab / 探索工具 / 审批中心 / NR_SA+Wi‑Fi |
| 非 debug 签名 | `apksigner` 通过；证书 `成都修茈科技有限公司` |
| 证据 | `v10-c-phone-20260711/` + `*-final.md` |

剩余产品补测（不挡 PL3 技术签）：真实 QR 绑定成功录屏、审批通过/驳回写操作、本机 Flutter SDK 构建复验。
