# XCAGI Android

> **交付状态（2026-06）**：**实验骨架** — Kotlin + Jetpack Compose 可本地构建与单测；**非**签约级移动产品。对外口径以 [`docs/CLAIMED_VS_ACTUAL.md`](../docs/CLAIMED_VS_ACTUAL.md) 与 [`VERSION.md`](../VERSION.md) 为准。

成都修茈科技有限公司 XCAGI 原生 Android 客户端（个人版 / 企业版双 SKU）。

- 技术栈：Kotlin、Jetpack Compose、Hilt、Retrofit、Room、WorkManager
- 完整说明：[docs/guides/MOBILE_ANDROID.md](../docs/guides/MOBILE_ANDROID.md)

## 快速开始

1. 云端：企业版默认手机号 + 6 格验证码登录 → **对话 Tab** 空态即开聊（Kimi 风推荐问题）
2. 局域网：PC 运行 FHD `python XCAGI/run.py --host 0.0.0.0 --port 5000` → 应用内连接电脑 → FHD 账号登录 → 同步与原生 AI 对话

**导航**：登录后 4 Tab（对话 · 工作 · 发现 · 我的）；对话工具栏主行仅「模式 + 联网 + 更多」，深度思考/工作台等收入 BottomSheet。

```bat
gradlew.bat assemblePersonalDebug assembleEnterpriseDebug
```

## Release 正式签名

```powershell
cd ..
powershell -File scripts/package/new-android-release-keystore.ps1
powershell -File scripts/package/build-android-release-signed.ps1 -Stage -Version 8.0.0 -AndroidVersion 1.3.0
```

详见 `signing/README.md` 与 `keystore.properties.example`。

产出：`release/packages-v8.0.0/personal|enterprise/` 下的 Windows 安装包与 Android APK。
