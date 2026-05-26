# XCAGI Android 原生客户端

## 概述

`mobile-android/` 为 **成都修茈科技有限公司** XCAGI 的 Android 原生客户端（Kotlin + Jetpack Compose），与 [FHD](../) 电脑端（Electron + FastAPI）及公网 [MODstore](https://xiu-ci.com) 互联。

- **品牌图标**：与 Windows 相同，源文件 [`desktop/branding/app-icon-source.png`](../../desktop/branding/app-icon-source.png)，由 `scripts/package/generate-android-icons.py` 生成各密度 `mipmap`。
- **启动流程（混合）**：已保存电脑主机或完成引导 → 直达登录/工作台；仅首次显示「进入云端」引导（电脑连接可折叠）。
- **产品壳**：登录后主 Tab 为 **MODstore 工作台 WebView**（`https://xiu-ci.com/workbench/home`），与官网一致；「我的」集中账号、连接电脑与高级功能。
- **双 SKU**：`personal` / `enterprise` 两个独立安装包，可同时安装。

| Flavor | applicationId | 说明 |
|--------|---------------|------|
| **personal** | `com.xiuci.xcagi.mobile.personal` | 个人版 |
| **enterprise** | `com.xiuci.xcagi.mobile.enterprise` | 企业版（含审批/ERP 底栏） |

## 图标生成（打包前）

```bat
cd FHD
python scripts/package/generate-android-icons.py
```

## 构建 APK

```bat
cd mobile-android
gradlew.bat assemblePersonalDebug assembleEnterpriseDebug
```

整理到分发目录（含 Windows exe + Android apk）：

```powershell
cd FHD
python scripts/package/generate-android-icons.py
powershell -File scripts/package/stage-sku-download-folders.ps1 -Version 8.0.0
```

产出：`release/packages-v8.0.0/personal/` 与 `enterprise/`（或已重命名为 `个人版` / `企业版`）。

## 架构

| 模式 | 基址 | 用途 |
|------|------|------|
| 局域网 FHD | `http://<PC_IP>:5000/` | SSE 对话、审批、ERP、LAN、Mod |
| 云端 MODstore | `https://xiu-ci.com/` | 手机验证码、市场 |

移动端 API：`/api/mobile/v1/*`

## 底栏信息架构

| SKU | 底栏 Tab |
|-----|----------|
| 个人版 | 工作台 · 对话 · 我的 |
| 企业版 | 工作台 · 对话 · 审批 · 业务 · 我的 |

- **工作台**：WebView 加载公网工作台；登录后将 `modstore_token` / `modstore_refresh_token` 注入 `localStorage`（与官网 [`tokenStore`](../../成都修茈科技有限公司/MODstore_deploy/market/src/infrastructure/storage/tokenStore.ts) 一致）。
- **电脑端账号登录**：FHD 登录成功后调用 `GET /api/market/session-handoff` 同步市场 token。
- **手机号登录**：直接写入 `SessionStore` 市场 token。

## 前台体验说明

- 默认 **不** 后台扫描局域网；可在「我的」打开「后台自动发现电脑」。
- 「连接 / 更换电脑」仅在「我的」内进入，不出现在首屏底栏。
- 深色 Material3 主题，与工作台视觉一致。

## 阶段二（体验补齐）

| 模块 | 内容 |
|------|------|
| 对话 | 左右气泡布局；顶栏 **云端 / 局域网** 状态 Chip；空状态提示 |
| 企业 Tab | 审批 / 业务统一 TopAppBar；骨架屏、空状态、错误重试 |
| 工作台 WebView | URL 带 `?client=android`；注入 `__XCAGI_CLIENT__` 后 market 端 `useBreakpoint` 强制移动布局 |

Release 签名 APK、应用商店物料仍按发布流程单独处理。

## 相关文档

- [RELEASE_TWO_SKUS.md](./RELEASE_TWO_SKUS.md)
- [PLATFORM_SHELL.md](./PLATFORM_SHELL.md)
