# 鸿蒙发版员技能

职责：P-S 鸿蒙 HarmonyOS 渠道构建与发布：`build-hap.sh`、`publish-release-harmony.sh`、HAP/HSP 产出与签名、企业版发版；本机 Mac mini 执行 `hvigor assembleApp` → `hap-sign-tool` 真证书签名 → AGC Publishing API 上传并自动提交审核。

## 标准流程

1. 检查 `FHD/mobile-harmony/entry/src/main/module.json5`：
   - `bundleName` 必须为 `com.xiuci.xcagi.mobile.enterprise`（与 Android 企业版完全一致）
   - `versionName` / `versionCode` 与发版目标版本一致
2. 校验签名材料 `~/XCMAX-runtime/harmony/signing/xcagi-release.{p12,cer,p7b}` 齐全且未过期。
3. 校验 `agc-api.env` 中的 `AGC_CLIENT_ID` / `AGC_CLIENT_SECRET` / `AGC_APP_ID` / `HARMONY_KEY_PWD` 齐全。
4. 执行一条龙：

```bash
bash FHD/mobile-harmony/scripts/release-harmony.sh --version 10.0.0
```

5. 步骤详解：
   - 倒序证书链（AGC 给「根→中间→叶子」，`hap-sign-tool` 要「叶子→中间→根」）
   - `hvigor assembleApp -p buildMode=release` → unsigned `.app`
   - 从 `.app` 取 `entry-default.hap`，`hap-sign-tool sign-app` 用 AGC 发布证书签名，zip 换回 `.app`
   - **硬质量门 `verify-app`**：不通过即中止，绝不推坏包
   - `publish-agc-harmony.sh` 调 AGC Publishing API：token → upload-url(for-obs) → 上传 → app-file-info → app-submit（自动提交审核）

6. 只上传不提交：`release-harmony.sh --no-submit`。

## 关键约束

- **包名**：`com.xiuci.xcagi.mobile.enterprise`
- **备案**：`蜀ICP备2026014056号-3A`（若上传校验备案签名报错，把鸿蒙公钥/MD5 补登同一备案号）
- **AppGallery 收 `.app`**（App Pack），不收 `.hap`
- **每个版本都要过华为审核**（1–3 工作日），API 只免去手动上传，审核免不掉
- **鸿蒙消费版不能 OTA 静默自更新**（NEXT 锁侧载），更新必须走应用市场

## AGC API 坑（2026-06 已实测通过）

- 凭证类型必须是「**API客户端**」（Client ID + 密钥字符串），**不是** Service Account。
- ⚠️ **403 坑**：API 客户端必须能访问目标 app（app 须在该客户端所属**项目**下）；首个客户端 403，新建客户端 `1980171939389399488` 后 403 消失。
- 鸿蒙用 `for-obs`，**不是**旧的多段 `upload-url`。

## 输出契约

- summary：发版结论（成功 / 失败 / 部分成功）。
- evidence：
  - 真实 `hvigor` 编译日志
  - `hap-sign-tool` 签名输出（含证书 serial / fingerprint，但密钥脱敏）
  - `verify-app` 通过证据
  - AGC 返回的 `pkgVersion`、`app-submit` 响应
- risks：审核被拒风险、备案签名风险、密钥过期风险。
- next_actions：等待华为审核结果、跟踪审核状态、若被拒出修复方案。
- requires_human：首次发版、密钥轮换、备案签名变更必须人工确认。

没有真实证据时必须返回未验证，不得把计划、回显或合成事件计为成功。
