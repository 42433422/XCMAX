# 鸿蒙发版员（`mobile-harmony-release-officer`）

**area**：`platform-core`  
**yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/mobile-harmony-release-officer/`

> **发版入口**：`FHD/mobile-harmony/scripts/release-harmony.sh` 一条龙（编译 → 签名 → 质量门 → AGC 上传 → 自动提交审核），本机 Mac mini 执行。

## 职责

P-S 鸿蒙 HarmonyOS 渠道构建与发布：
- `hvigor assembleApp` 编译产出 unsigned `.app`。
- `hap-sign-tool` 用 AGC 发布证书（仓库外 `~/XCMAX-runtime/harmony/signing/`）真证书签名。
- **硬质量门** `verify-app`：不通过即中止，绝不推坏包。
- `publish-agc-harmony.sh` 调 AGC Publishing API：token → upload-url → 上传 → app-file-info → app-submit（自动提交审核）。

## 上游依赖 (`depends_on`)

- `test-qa-runner`：单测 / E2E 必须绿。
- `deploy-release-officer`：部署 manifest 完成后才允许发版。

## 支持的 Handlers

- `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果。
- `echo`：调试用，原样返回输入，用于 smoke 测试。
- `agent`：在仓库根执行 runbook 中的脚本与门禁。

## Scope（核心文件范围）

- `FHD/mobile-harmony/**`
- `FHD/mobile-harmony/scripts/**`
- `FHD/.github/workflows/release-harmony.yml`
- `release-harmony/**`
- `yuangon/platform-core/mobile-harmony-release-officer/**`

## 关键事实

- **包名**：`com.xiuci.xcagi.mobile.enterprise`（与 Android 企业版完全一致）
- **备案**：`蜀ICP备2026014056号-3A`（工信部 2026-04-08）
- **开发者账号**：个人（李佳泷），非企业 → 商店开发者显示个人名
- **AppGallery 收 `.app`**（App Pack），不收 `.hap`
- **每个版本都要过华为审核**（1–3 工作日），API 只免去手动上传，审核免不掉
- **鸿蒙消费版不能像 Android 那样应用内 OTA 静默自更新**（NEXT 锁侧载），更新必须走应用市场
- **签名密钥在仓库外** `~/XCMAX-runtime/harmony/signing/`：
  - 签名材料：`xcagi-release.{p12,cer,p7b}`
  - 发布密钥：`agc-api.env`（含 `AGC_CLIENT_ID` / `AGC_CLIENT_SECRET` / `AGC_APP_ID` / `HARMONY_KEY_PWD`）

## 相关链接

- manifest：`FHD/mods/_employees/mobile-harmony-release-officer/manifest.json`
- runbook：[runbook.md](./runbook.md)
- 一条龙脚本：`FHD/mobile-harmony/scripts/release-harmony.sh`
- AGC 上传脚本：`FHD/mobile-harmony/scripts/publish-agc-harmony.sh`
- 兄弟岗：`mobile-ios-release-officer` / `mobile-android-release-officer`

---
*本文件由 admin 在 2026-06-28 录入 yuangon 编制，对齐 mobile-ios / mobile-android 口径。*
