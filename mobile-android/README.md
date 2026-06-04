# XCAGI Android

> **状态：规划中（实验性骨架）**  
> 本目录已有 Kotlin / Compose / Hilt 代码与 `assembleDebug` CI，但**尚未作为签约级移动产品交付**；功能与发版节奏以 [`docs/guides/MOBILE_ANDROID.md`](../docs/guides/MOBILE_ANDROID.md) 与产品路线图为准。  
> CI：仓根 [`.github/workflows/android-build.yml`](../../.github/workflows/android-build.yml) · FHD 内 [`ci-mobile-android.yml`](../.github/workflows/ci-mobile-android.yml)。

## 当前范围

- 技术栈：Kotlin、Jetpack Compose、Hilt、Retrofit、Room、WorkManager
- 入口：`app/src/main/java/com/xiuci/xcagi/mobile/MainActivity.kt`（Compose 壳 + 导航骨架）
- 双 SKU：`assemblePersonalDebug` / `assembleEnterpriseDebug`

## 本地构建（Debug）

```bash
cd FHD/mobile-android
./gradlew assemblePersonalDebug assembleEnterpriseDebug
```

Windows：`gradlew.bat assemblePersonalDebug assembleEnterpriseDebug`

## 联调（规划目标）

1. 云端：手机号登录 → 工作台 / 首页 MODstore 推荐  
2. 局域网：PC 运行 FHD `python XCAGI/run.py --host 0.0.0.0 --port 5000` → 应用内连接电脑 → FHD 账号登录  

## Release 正式签名（未默认启用）

```powershell
cd FHD
powershell -File scripts/package/new-android-release-keystore.ps1
powershell -File scripts/package/build-android-release-signed.ps1 -Stage -Version 10.0.0 -AndroidVersion 1.3.0
```

详见 `signing/README.md` 与 `keystore.properties.example`。
