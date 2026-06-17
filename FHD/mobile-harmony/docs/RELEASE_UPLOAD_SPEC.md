# 鸿蒙企业版发布上传规范（v10）

本文档定义鸿蒙企业版移动端发布在 GitHub Release 的上传规范。

## 一、产物来源（企业版-only）

- 产物来源脚本：`mobile-harmony/scripts/stage-release-packages.sh`
- 目标版本：`v10.0.0`（可通过参数 `--version` 覆盖）

## 二、必须上传到 Release 的文件

> 以下命名来自 CI 工作流 `fhd-release-android.yml` 的上传路径。

1. `XCAGI-Enterprise-Android-<VERSION>.apk`
   - 来源：`FHD/mobile-android/app/build/outputs/apk/enterprise/release/app-enterprise-release.apk`
   - 说明：企业版 Android 安装包，仅企业账号使用

2. `release/packages-v<VERSION>/enterprise/`
   - 至少包含：
     - `XCAGI-Enterprise-Android-<VERSION>.apk`
     - `MOBILE_VERSION.md`
     - `README.txt`
     - 若提供鸿蒙包：`XCAGI-Enterprise-Harmony-<VERSION>.<hap|hsp>`
   - 不得包含个人版文件

3. `release/XCAGI-Enterprise-Mobile-Packages-v<VERSION>.zip`
   - 压缩内容：`release/packages-v<VERSION>/enterprise` 与 `release/packages-v<VERSION>/企业版`

## 三、发布链路要求

- `fhd-release-android.yml` 调度 `mobile-harmony/scripts/stage-release-packages.sh`
- 工作流上传到 Release 时，**仅上传企业版资源**
- 个人版产物（`personal` / `个人版` / `XCAGI-Personal-*`）不得参与该链路
- 鸿蒙输入支持：
  - 手工参数 `harmony_artifact`（Workflow 字段）
  - 环境变量 `FHD_HARMONY_HAP_PATH`
  - 无显式输入时自动扫描 `mobile-harmony/artifacts/` 后回退 `mobile-harmony/`

## 四、验收点

- 运行 `bash FHD/mobile-harmony/scripts/stage-release-packages.sh --version 10.0.0 --android-version 10.0.0`
- 检查 `release/packages-v10.0.0/enterprise` 中不出现 `personal` 目录（脚本会主动清理旧目录）
- 检查 zip 内文件清单包含企业版目录且不包含个人版目录
