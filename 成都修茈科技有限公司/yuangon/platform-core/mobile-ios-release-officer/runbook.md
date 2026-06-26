# Runbook：iOS 发版员 (`mobile-ios-release-officer`)

## iOS 已落地状态

`FHD/mobile-ios/` 已具备 SwiftUI 原生工程源码、XcodeGen `project.yml`、AppIcon 生成脚本、模拟器构建脚本与 App Store archive/export 脚本。本岗当前职责：

1. 维护 `FHD/mobile-ios/project.yml`、Bundle ID、entitlements、版本号与 AppIcon。
2. 维护 `FHD/.github/workflows/release-ios.yml` 的 simulator build、主线 profile secret 选取、IPA 导出和 App Store Connect 上传门禁；兼容线仅在明确需要时启用。
3. 使用 `scripts/create-app-store-profile.sh` 与 `scripts/sync-ios-signing-secrets.sh` 管理 Apple Developer profile 和 GitHub Secrets。
4. 在 Apple 账号密钥缺失时明确报告 `IOS_TEAM_ID`、证书、enterprise profile、App Store Connect API Key 等缺口；如涉及兼容线，再单独补报 personal profile 缺口。


        ## 职责摘要

        XCAGI iOS 渠道发布：主线上架、冻结兼容 SKU、Apple Developer profile、GitHub Secrets、XcodeGen 工程、签名、TestFlight / App Store Connect 上传与 release 门禁。

        ## 上游 Handoff 契约

        ### handoff: deploy-release-officer → 本岗
- **触发条件**：`ops.change_request.approved` → deploy 执行完成
- **输入**：部署 manifest、环境 URL、健康检查结果
- **门禁**：deploy 失败时自动 rollback；本岗等待 `/healthz` 返回 200

### handoff: mobile-android-release-officer → 本岗（iOS 岗专用）
- **触发条件**：Android 双 SKU APK/AAB 产物就绪 + `verify_version_anchors.py` 绿
- **输入**：`release-apk/` 产物路径、build.gradle.kts 版本锚点、smoke 通过报告
- **门禁**：Android 发版未完成时 iOS 发版只允许 dry-run；版本锚点必须 10.0.0 对齐
- **当前状态**：`FHD/mobile-ios/` 已落地；`release-ios.yml` 负责 XcodeGen / simulator build / dual-profile archive-export


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `FHD/mobile-ios/**`
- `FHD/.github/workflows/release-ios.yml`
- `FHD/XCAGI/resources/**`
- `yuangon/platform-core/mobile-ios-release-officer/**`

## 固定执行顺序

1. 先检查 `project.yml`、当前 scheme、Bundle ID、entitlements 和 workflow secret 映射；默认主线是 `XCAGIMobile`。
2. 如果缺少 profile，用 `bash FHD/mobile-ios/scripts/create-app-store-profile.sh --scheme ... --profile-name ...` 创建并下载。
3. 用 `bash FHD/mobile-ios/scripts/sync-ios-signing-secrets.sh --dry-run ...` 先校验 `.p12`、enterprise `.mobileprovision`、`.p8` 是否一致；只有兼容线任务才额外带 `--profile-personal`。
4. 校验通过后再同步 GitHub Secrets，并保留 secret 名称、profile UUID、证书 serial 作为证据。
5. 最后执行 simulator build / archive-export / App Store Connect 上传。

## 关键门禁

- `XCAGIMobile` 只能使用企业版 profile secret。
- `XCAGIMobilePersonal` 只有在明确兼容任务下才允许使用个人版 profile secret。
- 企业版 profile 的证书 serial 必须等于 `.p12` 内证书 serial；若传入个人版 profile，也必须一致。
- 只有读权限的 App Store Connect API key 不能代替 Apple Developer 门户 profile 创建。

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:mobile-ios-release-officer` |
        | 上游依赖未完成 | 等待 `employee.task.done:<dep>` 事件，不自行推进 |
        | scope 文件不存在 | 报告缺口，待确认后再执行，不编造路径 |
        | 版本锚点不对齐 | 运行 `verify_version_anchors.py`，修复后继续 |
        | Apple API 只能读不能写 | 改走已登录浏览器会话与 Accessibility 自动化，不停在口头说明 |
        | profile / p12 不匹配 | 重新下载正确 profile，直到 serial 一致后才允许同步 secret |

        ## 验收检查清单

        - [ ] `employee.yaml.depends_on` 与 manifest 根级一致
        - [ ] `actions.handlers` 三方一致（yaml / manifest / `_DISPATCH`）
        - [ ] scope_globs 路径存在（或标注规划中）
        - [ ] `employee_pack_consistency_warnings` 无 handler warning
        - [ ] echo smoke 测试通过

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
