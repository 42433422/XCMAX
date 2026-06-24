# 鸿蒙企业版构建说明

`mobile-harmony` 现在是企业版 HarmonyOS ArkTS 工程，不再只是发布占位目录。

## 入口策略

- Bundle ID：`com.xiuci.xcagi.mobile.enterprise`
- 入口页：`https://xiu-ci.com/login?sku=enterprise&platform=harmony&mobile=1`
- 后端来源：企业版 Web 部署应继续把 API 基址注入为 `/fhd-api`，与桌面企业版登录后端保持同源。
- 权限：当前只声明 `ohos.permission.INTERNET`。

## 离线编译验证(无需联网、无需 DevEco IDE)

本机已带命令行工具链(`~/XCMAX-runtime/harmony/`：hvigor + SDK + ohos 插件)。
改动 ArkTS 后用下面命令做**真实编译验证**(约 4 秒，`CompileArkTS` 全量类型检查 + 打包 HAP)：

```bash
export PATH="$HOME/XCMAX-runtime/harmony/bin:$PATH"
cd FHD/mobile-harmony
hvigor --no-daemon assembleHap -p product=default -p buildMode=debug
```

期望末尾 `BUILD SUCCESSFUL`，无 `ArkTS:ERROR`(warning 可接受)。
注意：**不要**跑 `ohpm install`(华为仓在隔离网络下 404)；全局 hvigor 会从 command-line-tools 离线解析 ohos 插件。
真机行为(推送/摄像头扫码/OCR/生物识别/WebSocket 实时)需在 HarmonyOS 设备上验证，见 `PARITY_MATRIX.md`。

## 本地构建

需要先安装 DevEco Studio / HarmonyOS SDK，并确保以下命令在 `PATH` 内：

- `ohpm`
- `hvigor` 或 `hvigorw`

如当前环境没有配置华为仓库，先执行：

```bash
ohpm config set registry https://repo.harmonyos.com/ohpm/
npm config set @ohos:registry https://repo.harmonyos.com/npm/
```

构建：

```bash
bash FHD/mobile-harmony/scripts/build-hap.sh --version 10.0.0 --mode release
```

输出：

```text
FHD/mobile-harmony/artifacts/XCAGI-Enterprise-Harmony-10.0.0.hap
```

诊断当前机器是否具备构建条件：

```bash
bash FHD/mobile-harmony/scripts/doctor.sh
```

如 CI 镜像使用不同 hvigor task，可传入：

```bash
HARMONY_BUILD_COMMAND='hvigor assembleHap --mode release -p product=default' \
  bash FHD/mobile-harmony/scripts/build-hap.sh --version 10.0.0
```

## 发布要求

`stage-release-packages.sh` 默认要求必须存在鸿蒙 `.hap/.hsp`，否则退出失败。临时只验证 Android 分发目录时才允许显式使用 `--allow-missing-harmony`。

真实发布到 `FHD/v10.0.0`：

```bash
bash FHD/mobile-harmony/scripts/publish-release-harmony.sh \
  --version 10.0.0 \
  --tag FHD/v10.0.0 \
  --harmony-artifact FHD/mobile-harmony/artifacts/XCAGI-Enterprise-Harmony-10.0.0.hap
```

只验证打包，不上传：

```bash
bash FHD/mobile-harmony/scripts/publish-release-harmony.sh \
  --version 10.0.0 \
  --tag FHD/v10.0.0 \
  --harmony-artifact FHD/mobile-harmony/artifacts/XCAGI-Enterprise-Harmony-10.0.0.hap \
  --dry-run
```
