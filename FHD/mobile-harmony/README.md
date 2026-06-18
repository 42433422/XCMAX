# 移动鸿蒙模块（企业版发布链路）

本目录是 XCAGI 企业版 HarmonyOS 手机端 ArkTS 工程与发布模块。

## 目录约定

- `AppScope/`、`entry/`、`build-profile.json5`、`oh-package.json5`：HarmonyOS 工程；
- `artifacts/`：落地已构建/签名鸿蒙安装包（`.hap` / `.hsp`）；
- `scripts/build-hap.sh`：调用本机 DevEco/HarmonyOS SDK 构建 `.hap`；
- `scripts/doctor.sh`：检查当前机器是否具备鸿蒙构建工具链；
- `scripts/publish-release-harmony.sh`：用真实 `.hap/.hsp` 重新生成移动 zip 并上传到 GitHub Release；
- `scripts/stage-release-packages.sh`：按统一命名规则生成 release 分发目录；
- `docs/`：构建与上传规范。

## 命名约定

- 企业版鸿蒙：`XCAGI-Enterprise-Harmony-${VERSION}.${ext}`（`ext` 为 `hap` 或 `hsp`）
- 如目录内同时存在多个鸿蒙包，优先使用：带版本号 `v${VERSION}` 的文件；无版本号则按构建时间取最新；同分数下 `hap` 优先于 `hsp`。

## 目标产物

- `release/packages-v${VERSION}/enterprise/XCAGI-Enterprise-Android-${VERSION}.apk`
- `release/packages-v${VERSION}/enterprise/XCAGI-Enterprise-Harmony-${VERSION}.${ext}`
- `release/packages-v${VERSION}/企业版/`（中文同名目录）
- `release/XCAGI-Enterprise-Mobile-Packages-v${VERSION}.zip`（可选）

每个企业版目录同时额外写入：
- `MOBILE_VERSION.md`：记录手机端软件版本与鸿蒙状态，便于下载自检。

## 说明

- 本链路是**企业版-only**，不打包/上传个人版鸿蒙与 Android 安装产物。
- 发布打包默认必须存在企业版鸿蒙 `.hap/.hsp`。没有鸿蒙包会直接失败，避免把缺少鸿蒙版的手机版发布成完整版本。
- 本地构建要求安装 DevEco Studio / HarmonyOS SDK，详见 [BUILD_HARMONY.md](docs/BUILD_HARMONY.md)。

## 发版动作

- 手动触发：仓库根工作流 `fhd-release-android.yml`（或 FHD 源文件 `FHD/.github/workflows/release-android.yml`）
- 鸿蒙单独补发：仓库根工作流 `fhd-release-harmony.yml`（或本地脚本 `scripts/publish-release-harmony.sh`）
- 参考脚本：`mobile-harmony/scripts/stage-release-packages.sh`
- 产物上传规范：见 [RELEASE_UPLOAD_SPEC.md](docs/RELEASE_UPLOAD_SPEC.md)
