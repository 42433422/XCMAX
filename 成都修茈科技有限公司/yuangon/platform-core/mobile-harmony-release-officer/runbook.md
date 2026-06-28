# Runbook：鸿蒙发版员 (`mobile-harmony-release-officer`)

| 字段 | 值 |
|------|----|
| 员工 ID | `mobile-harmony-release-officer` |
| 负责区域 | `platform-core` |
| 最后更新 | 2026-06-28 |
| 应急联系 | admin |

## 一条龙全自动发版

```bash
bash FHD/mobile-harmony/scripts/release-harmony.sh --version 10.0.0
```

执行步骤：

1. **倒序证书链**：AGC 给的是「根→中间→叶子」，`hap-sign-tool` 要「叶子→中间→根」。
2. **`hvigor assembleApp -p buildMode=release`** → 产出 unsigned `.app`。
3. **`hap-sign-tool sign-app`** 用 AGC 发布证书签名，zip 换回 `.app`。
   - 签名材料：`~/XCMAX-runtime/harmony/signing/xcagi-release.{p12,cer,p7b}`
4. **硬质量门 `verify-app`**：不通过即中止，绝不推坏包（此为工程校验，非人工审批）。
5. **`publish-agc-harmony.sh` 调 AGC Publishing API**：
   1. `POST /api/oauth2/v1/token`（client_credentials）→ token
   2. `GET /api/publish/v2/upload-url/for-obs?appId=&fileName=&contentLength=&releaseType=1` → OBS 预签名 PUT 地址 + objectId
   3. `PUT` `.app` 到 OBS（带返回的 AWS4 签名头 + Content-Length）
   4. `PUT /api/publish/v2/app-file-info` body `{fileType:5, files:[{fileName, fileDestUrl:objectId}]}` → 绑定，返回 pkgVersion
   5. `POST /api/publish/v2/app-submit?appId=&releaseType=1` → 自动提交审核

只上传不提交：`release-harmony.sh --no-submit`。

## AGC API 鉴权坑（2026-06 已实测通过）

- 凭证类型必须是「**API客户端**」（给 Client ID + 密钥字符串），**不是** Service Account（JWT 私钥那种，发布接口不认）。
- ⚠️ **403 坑**：API 客户端必须能访问目标 app（app 须在该客户端所属**项目**下）；否则 token 有效也 403。首个客户端 403，新建客户端 `1980171939389399488` 后 403 消失。
- 鸿蒙用 `for-obs`，**不是**旧的多段 `upload-url`。

## 首跑前置（只需一次）

1. `~/XCMAX-runtime/harmony/signing/agc-api.env` 填 `AGC_CLIENT_ID` / `AGC_CLIENT_SECRET` / `AGC_APP_ID` / `HARMONY_KEY_PWD`（已配好）。
2. AGC「应用信息」填齐（名称/介绍/图标/隐私政策 HTTPS/截图）—— **submit 的前置**，否则 `app-submit` 报应用信息不全。
3. ✅ 上传+绑定已实测通（包已挂上版本）；**只剩 submit 待首次成功**（需上面第 2 步）。

## 固定执行顺序

1. 检查 `FHD/mobile-harmony/entry/src/main/module.json5` 中的 `bundleName` 与 `versionName` / `versionCode`。
2. 校验 `~/XCMAX-runtime/harmony/signing/xcagi-release.{p12,cer,p7b}` 是否齐全且未过期。
3. 校验 `agc-api.env` 中的 4 个变量是否齐全。
4. dry_run 模式跑 `release-harmony.sh --dry-run`，验证编译与签名路径。
5. 正式发版跑 `release-harmony.sh --version <X.Y.Z>`，必须给真实 build log 与 AGC 返回的 pkgVersion 作为证据。

## 关键门禁

- `verify-app` 必须通过，否则中止。
- AGC 应用信息必须齐全（名称/介绍/图标/隐私政策/截图），否则 `app-submit` 报错。
- 备案号 `蜀ICP备2026014056号-3A` 必须与鸿蒙公钥/MD5 绑定（若上传校验备案签名报错，把鸿蒙公钥/MD5 补登同一备案号）。
- 严禁在 dry_run 模式下产生签名 / 上传副作用。

## 故障处置

| 场景 | 处置 |
|------|------|
| `hvigor assembleApp` 失败 | 拉编译日志定位缺包/版本不兼容；不重试到死，3 次失败升级 admin |
| `hap-sign-tool` 签名失败 | 检查证书链倒序、p12 密码、证书过期；与 `security-secrets-guard` 联动轮换 |
| `verify-app` 不通过 | 立即中止，绝不推坏包；报告缺包/缺资源/缺权限 |
| AGC 403 | 检查 API 客户端是否在目标 app 所属项目下；新建客户端解决 |
| AGC `app-submit` 报应用信息不全 | 在 AGC 控制台补齐名称/介绍/图标/隐私政策/截图后重试 |
| 备案签名校验失败 | 把鸿蒙公钥/MD5 补登到同一备案号 |
| 上游依赖未完成 | 等待 `employee.task.done:test-qa-runner` + `employee.task.done:deploy-release-officer` 事件，不自行推进 |

## 验收检查清单

- [ ] `employee.yaml.depends_on` 与 manifest 根级一致（`test-qa-runner` / `deploy-release-officer`）
- [ ] `actions.handlers` 三方一致（yaml / manifest / `_DISPATCH`）
- [ ] scope_globs 路径存在（`FHD/mobile-harmony/**` 等）
- [ ] `employee_pack_consistency_warnings` 无 handler warning
- [ ] echo smoke 测试通过

---
*本文件由 admin 在 2026-06-28 录入 yuangon 编制，对齐 mobile-ios / mobile-android 口径。*
