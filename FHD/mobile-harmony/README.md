# 移动鸿蒙模块目录（企业版发布链路）

本目录落地鸿蒙版本产物的最小发布模块，专供企业版手机端。

## 目录约定

- `artifacts/`：落地可签名鸿蒙安装包（`.hap` / `.hsp`）；
- `scripts/stage-release-packages.sh`：按统一命名规则生成 release 分发目录；
- `docs/`：后续扩展文档占位；

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

## 发版动作

- 手动触发：仓库根工作流 `fhd-release-android.yml`（或 FHD 源文件 `FHD/.github/workflows/release-android.yml`）
- 参考脚本：`mobile-harmony/scripts/stage-release-packages.sh`
- 产物上传规范：见 [RELEASE_UPLOAD_SPEC.md](docs/RELEASE_UPLOAD_SPEC.md)
