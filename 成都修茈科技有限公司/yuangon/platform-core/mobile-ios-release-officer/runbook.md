        # Runbook：iOS 发版员 (`mobile-ios-release-officer`)

## iOS 规划中状态

`FHD/mobile-ios/` 目录尚未创建，`release-ios.yml` 待建。本岗当前职责：

1. 监控 Android 岗（`mobile-android-release-officer`）产物就绪信号
2. 维护 `FHD/XCAGI/resources/` 公共资源层（scope 中已声明）
3. 当 iOS 工程建立后，按 `MOBILE_ANDROID.md` 模式补充 TestFlight/App Store 发版流程


        ## 职责摘要

        P-S iOS 渠道发布（规划中）：TestFlight / App Store 工程、notarize 协同与 release 门禁。

        ## 上游 Handoff 契约

        ### handoff: deploy-release-officer → 本岗
- **触发条件**：`ops.change_request.approved` → deploy 执行完成
- **输入**：部署 manifest、环境 URL、健康检查结果
- **门禁**：deploy 失败时自动 rollback；本岗等待 `/healthz` 返回 200

### handoff: mobile-android-release-officer → 本岗（iOS 岗专用）
- **触发条件**：Android 双 SKU APK/AAB 产物就绪 + `verify_version_anchors.py` 绿
- **输入**：`release-apk/` 产物路径、build.gradle.kts 版本锚点、smoke 通过报告
- **门禁**：Android 发版未完成时 iOS 工程暂停；版本锚点必须 10.0.0 对齐
- **当前状态**：FHD/mobile-ios/ 规划中，release-ios.yml 待建


        ## Handlers

        | Handler | 说明 |
        |---------|------|
        | `llm_md` | 接收 Markdown 任务描述，调用 LLM 输出结构化结果 |
| `echo` | 调试用：原样返回输入，用于 smoke 测试 |

        ## 核心 Scope

        - `FHD/mobile-ios/**`
- `FHD/.github/workflows/release-desktop.yml`
- `FHD/XCAGI/resources/**`
- `yuangon/platform-core/mobile-ios-release-officer/**`

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:mobile-ios-release-officer` |
        | 上游依赖未完成 | 等待 `employee.task.done:<dep>` 事件，不自行推进 |
        | scope 文件不存在 | 报告缺口，待确认后再执行，不编造路径 |
        | 版本锚点不对齐 | 运行 `verify_version_anchors.py`，修复后继续 |

        ## 验收检查清单

        - [ ] `employee.yaml.depends_on` 与 manifest 根级一致
        - [ ] `actions.handlers` 三方一致（yaml / manifest / `_DISPATCH`）
        - [ ] scope_globs 路径存在（或标注规划中）
        - [ ] `employee_pack_consistency_warnings` 无 handler warning
        - [ ] echo smoke 测试通过

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
