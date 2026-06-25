# iOS 发版员技能

职责：XCAGI iOS 渠道发布：主线上架、冻结兼容 SKU、Apple Developer profile、GitHub Secrets、XcodeGen 工程、签名、TestFlight / App Store Connect 上传与 release 门禁。

## 标准流程

1. 检查 `FHD/mobile-ios/project.yml`、scheme、Bundle ID、版本号、entitlements、AppIcon 与 `FHD/.github/workflows/release-ios.yml`。
2. 先确认当前发版口径:
   - `XCAGIMobile` → `com.xiuci.xcagi.mobile.enterprise`，当前主线上架 / App Store 线
   - `XCAGIMobilePersonal` → `com.xiuci.xcagi.mobile.personal`，冻结兼容线，仅在明确需要时维护
3. 需要新建 App Store profile 时，优先使用:

```bash
bash FHD/mobile-ios/scripts/create-app-store-profile.sh \
  --scheme XCAGIMobile \
  --profile-name XCAGIMobile-AppStore-Enterprise-YYYYMMDDA
```

4. 拿到 `.p12`、enterprise `.mobileprovision`、`AuthKey_*.p8` 后，优先使用:

```bash
bash FHD/mobile-ios/scripts/sync-ios-signing-secrets.sh \
  --repo owner/repo \
  --team-id TEAM_ID \
  --p12 /path/to/certificate.p12 \
  --p12-password '***' \
  --profile-enterprise /path/to/enterprise.mobileprovision \
  --api-key-p8 /path/to/AuthKey_XXXXXX.p8 \
  --api-key-id KEY_ID \
  --api-issuer-id ISSUER_ID \
  --keychain-password '***'
```

如需继续维护冻结兼容线，再额外传 `--profile-personal /path/to/personal.mobileprovision`。

5. 必须核对:
   - 企业版 profile 的 `Entitlements:application-identifier`
   - 企业版 profile 嵌入证书 serial 是否与 `.p12` 一致
   - 如传入个人版 profile，再额外核对其 Bundle ID 和证书 serial
   - workflow 是否按 scheme 选择对应 secret，默认应跟随 `XCAGIMobile`
6. 然后运行允许范围内的 XcodeGen / Simulator build / archive-export 门禁。
7. 上传 App Store Connect 前，必须给出真实 IPA / archive / 上传日志证据。

## 遇到 Apple 门户限制时

- App Store Connect API 只能读不能写时，不得停在说明层。
- 改用已登录浏览器会话与 Accessibility 自动化创建 profile，并在结果中返回:
  - profile 文件名
  - profile UUID
  - Bundle ID
  - 证书 serial / fingerprint
  - 已更新的 GitHub secret 名称

## 输出契约

- summary：结论。
- evidence：真实文件、命令输出、页面结果、构建日志或 secret 更新记录。
- risks：风险与不确定项。
- next_actions：下一步、负责人和是否需要人工确认。

没有真实证据时必须返回未验证，不得把计划、回显或合成事件计为成功。
