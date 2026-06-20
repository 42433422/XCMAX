# Android Release 签名

本目录用于存放 **正式 Release 密钥库**(`xcagi-release.jks`),文件已加入 `.gitignore`,请勿提交到 Git。

## 首次生成

在 `FHD/mobile-android` 目录执行:

```bash
bash signing/generate-keystore.sh
```

脚本会交互式提示输入密码,完成后生成:
- `signing/xcagi-release.jks`(RSA 4096,有效期 100 年)
- `keystore.properties`(已填入密码,已 gitignore)

## 备份

请将 `.jks` 与密码存入公司密钥管理(密码管理器 / 离线保险柜)。**丢失后无法为同一 `applicationId` 发布更新包。**

## 构建已签名 Release

配置好 `keystore.properties` 后,直接运行 Gradle 即可(签名配置会自动读取):

```bash
cd FHD/mobile-android
./gradlew assembleEnterpriseRelease
```

也可通过环境变量覆盖(优先级高于 `keystore.properties`):

```bash
XCAGI_ANDROID_KEYSTORE=signing/xcagi-release.jks \
XCAGI_ANDROID_KEYSTORE_PASSWORD=*** \
XCAGI_ANDROID_KEY_ALIAS=xcagi_release \
XCAGI_ANDROID_KEY_PASSWORD=*** \
./gradlew assembleEnterpriseRelease
```

强制要求正式签名(无 keystore 时硬失败,而非 fallback 到 debug key):

```bash
XCAGI_REQUIRE_RELEASE_SIGNING=1 ./gradlew assembleEnterpriseRelease
```

## CI 自动签名(GitHub Actions)

在仓库 **Settings → Secrets and variables → Actions** 配置以下 4 个 Secret:

| Secret 名 | 值 | 获取方式 |
|-----------|-----|---------|
| `ANDROID_KEYSTORE_BASE64` | keystore 文件的 base64 编码 | `base64 -i signing/xcagi-release.jks \| tr -d '\n'` |
| `ANDROID_KEYSTORE_PASSWORD` | storePassword | 生成时设置的密码 |
| `ANDROID_KEY_ALIAS` | `xcagi_release` | 固定值 |
| `ANDROID_KEY_PASSWORD` | keyPassword | 生成时设置的密码 |

配置后,`fhd-release-android.yml` 会自动解码 keystore 并用正式签名构建;未配置时发警告并 fallback 到 debug key(仅适用于测试)。
