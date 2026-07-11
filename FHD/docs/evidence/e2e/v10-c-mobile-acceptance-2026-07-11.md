# v10-C 移动 AI 协同 App · 验收底稿（2026-07-11 · 非正式终稿）

> **状态：工程可交付骨架已齐，真机终验未签 → PL3 暂不勾选**  
> **版本锚点**：10.0.0  
> **主线**：`FHD/mobile-flutter-poc`（Kotlin/iOS 原生已归档）

## 已落地（代码 / CI）

| 项 | 状态 |
|----|------|
| LAN/云路由 `preferCloudIfLanUnreachable` | 代码 + 单测文件 |
| 探索 Tab 审批入口 | 代码 |
| 通知诚实空态；审批驳回推送 | 代码 |
| CI/发版切 Flutter | `fhd-ci-mobile-flutter` / `fhd-release-android` |
| Release 签名接线 | `key.properties` / `XCAGI_ANDROID_*`（无密钥仍 debug） |

## 仍阻塞正式签字

| 项 | 说明 |
|----|------|
| 本机 `flutter test` / 正式 APK | 本机构建机无 Flutter SDK |
| 正式 keystore 签名包 | 需配置 `key.properties` 且 `XCAGI_REQUIRE_RELEASE_SIGNING=1` |
| 真机 E2E | 登录 / 扫码 / 5G / 审批闭环录屏或报告 |

升格 `*-final.md` 并勾 PL3 的条件：上述三项至少「真机 E2E + 非 debug 签名包」完成。
