# 三端无障碍和视觉质量专项检查报告

日期：2026-11-25；集成入口 [#3605](https://github.com/42433422/XCMAX/pull/3605)。
基准审计 SHA: `7efb9ab40c62de6be1e56013a9ec1e9ee276e170`；
静态复核 SHA: `9ec2eed0c72ed7e28a6745d08f89e850acb71252`。
范围：适用的 [WCAG 2.2 AA](https://www.w3.org/TR/WCAG22/) 设计目标，不是合规认证。
**总体 BLOCKED**。只有源码静态检查及提交回执；没有真实浏览器/Flutter/桌面/手机执行结果和截图，不继承旧 SHA 的结论。

## 责任边界与复现
协调评论：[7161895550](https://github.com/42433422/XCMAX/pull/3605#issuecomment-7161895550)。
Token 组负责 SSOT、生成器和全局主题；弹层/动效组负责共享确认框、滑杆、焦点管理和动效；聊天与任务组负责相应运行时组件。无障碍组修改独立审批页面和测试文件，使用 blob SHA 检查共享视觉文件。暂无相应负责人明确回复，不视为交接完成。

在 FHD 仓库树运行：
```sh
node FHD/scripts/design/audit-accessibility-contrast.mjs
```
审计脚本已读取上述静态复核 SHA 的实际 SSOT 和 ConfirmDialog 源文件，在 JS 运行环境执行算法（文件读取由连接器返回的同一 SHA 内容注入，而非本地 Node 文件系统）。公式自检：黑白 21:1，相同颜色 1:1；最终 exitCode=1，15 个不透明明确色对中 3 个通过、12 个失败。仅计算指定纯色对；渐变、透明合成、真实背景、禁用/焦点/选中状态均需运行时测量。颜色作为装饰时不能直接据此判定 WCAG 失败；下表失败是按普通文本用途的目标判定。

| ID | 源码色对（前景 / 背景） | 比值 | 结果 / 责任 |
|---|---|---:|---|
| C01 | Flutter onPrimary #FFFFFF / #6366F1 | 4.4669 | FAIL / Token |
| C02 | Flutter onSecondary #FFFFFF / #10B981 | 2.5367 | FAIL / Token |
| C03 | Flutter onError #FFFFFF / #EF4444 | 3.7631 | FAIL / Token |
| C04 | Flutter 浅色三级文本 #8F959E / #FFFFFF | 3.0170 | FAIL / Token |
| C05 | Flutter 深色三级文本 #7A7F87 / #1F2124 | 4.0061 | FAIL / Token |
| C06 | Flutter 浅色审批标签 #312E81 / #EAEBFE | 9.6895 | PASS_STATIC_PAIR / 已改源码，待 widget |
| C07 | Flutter 深色审批标签 #B8CCFF / #1A3A80 | 6.6906 | PASS_STATIC_PAIR / 已改源码，待 widget |
| C08 | Desktop ConfirmDialog primary #FFFFFF / #3498db | 3.1531 | FAIL / 弹层 |
| C09 | Desktop ConfirmDialog primary:hover #FFFFFF / #2980b9 | 4.3011 | FAIL / 弹层 |
| C10 | Desktop ConfirmDialog secondary #FFFFFF / #95a5a6 | 2.5577 | FAIL / 弹层 |
| C11 | Desktop ConfirmDialog secondary:hover #FFFFFF / #7f8c8d | 3.4778 | FAIL / 弹层 |
| C12 | Desktop ConfirmDialog danger #FFFFFF / #e74c3c | 3.8204 | FAIL / 弹层 |
| C13 | Desktop ConfirmDialog danger:hover #FFFFFF / #c0392b | 5.4384 | PASS_STATIC_PAIR |
| C14 | Desktop ConfirmDialog success #FFFFFF / #2ecc71 | 2.1017 | FAIL / 弹层 |
| C15 | Desktop ConfirmDialog success:hover #FFFFFF / #27ae60 | 2.8729 | FAIL / 弹层 |

审批浅色原色对 #6366F1 / #EAEBFE = 3.79:1。审批页改用现有 onPrimaryContainer 语义色，不另建 Token。

## 问题清单（未关闭即不得验收）
| ID | 条款 | 问题 / 证据 | 责任 / 状态 |
|---|---|---|---|
| A01 | 1.4.3、1.4.11 | 上表 12 个静态色对失败；非文字边界、焦点环、交互状态、渐变尚未渲染测量 | Token/弹层 / OPEN |
| A02 | 2.1.1、2.1.2、2.4.3、2.4.7、2.4.11 | Market `src/components/AppConfirmDialog.vue` 无显式初始焦点、Escape、焦点循环/恢复逻辑；Desktop 已有 useDialogFocus，实际 Tab 顺序及可见性未测试 | 弹层 / OPEN |
| A03 | 4.1.2、4.1.3 | Flutter `features/approval/approval_screens.dart` 的加载无名称、错误/结果无 live region、输入框只有 hint | 无障碍 / CODE_FIXED_UNVERIFIED |
| A04 | 1.4.4、1.4.10 | Flutter WeCell 存在 maxLines/ellipsis，200% 下关键文字和操作可达性需逐项测量 | 组件 / OPEN |
| A05 | 2.5.8、1.3.4 | Flutter 审批页原 SafeArea bottom:false，已改；实际触控目标、安全区及横竖屏仍需 iOS/Android 验证；WCAG AA 最小目标一般 24 CSS px，平台采用 44/48 目标 | 无障碍/移动 / CODE_FIXED_PARTIAL |
| A06 | 1.4.10、1.4.11、2.3.1 | 深浅主题、窄屏、平板、DPR2 模拟、减少动画新增截图用例；渲染差异、实际主题切换和动作时序未实测 | 无障碍/动效 / TEST_ADDED_UNRUN |
| A07 | 视觉回归 | 已有 CI 用相同测试捕获 base/candidate；本轮新增审批、确认、任务、异常和输入焦点场景；新增滑杆/授权状态截图尚未覆盖，基线不存在的新组件不得静默跳过 | 视觉/弹层 / PARTIAL |
| A08 | 证据门禁 | 保留原 compare_visual_regression.py、审批文件空配置、artifact 上传与比较逻辑；无基线/候选/差异截图实物 | 视觉 / BLOCKED |

## 已提交实际变更
- `9879c6a2249e9445c9667ce70d4d09cc6c733a86` 审批页面语义色、进度名称、错误和结果 live region、持久标签、底部安全区；确认后增加 mounted/_working 检查。
- `a6a952fa0e096b9039824b144dd6866e6cf93999` Flutter 审批无障碍 widget 测试（深浅色、200% 字体、加载、错误及安全区）。
- `9be9bb1489375ecb3e47e1a2c42f82c0504bb70f` Flutter 视觉用例：三种尺寸 × 两主题的审批列表和错误；审批详情和确认；任务正常和失败。使用合成业务数据，不实际发起业务审批。
- `4342a981b3801258d328a2044451c0df0af0e87a` Desktop 独立视觉用例：两视口、两媒体颜色方案、DPR2、减少动画、输入焦点与 Tab。
- `0d5fc0ed595c2b58c625fe0c07118a1e5128e3f2` Market 独立视觉用例：手机/平板视口、同上。
- `aabff9f2b4fe179dcd673cac0793300fa3838854` 可重复执行且失败时非零退出的静态对比度审计工具。未新增第二套 Token 或截图比较器。该工具尚未接入单独 CI 检查，原门禁未更改。

新增视觉候选计划：Flutter 20 张（12 审批列表/异常 + 4 详情/确认 + 4 任务正常/异常），Desktop 8 张，Market 8 张，共 36 张计划；不是实际产出的图片。浏览器共用 capture.ts 仍按 CSS 像素输出；DPR2 只模拟设备布局，不等同物理高 DPI 截图验证；媒体方案也不等同应用实际完成主题切换。

## 后续必须执行的验收
- `cd FHD/mobile-flutter-poc && flutter test test/approval_accessibility_test.dart`；flutter analyze、格式检查、三端视觉 CI 全部执行，核对当前 SHA 与 CI 候选的对应关系。
- 真实浏览器键盘逐控件遍历，NVDA/VoiceOver/TalkBack 实测名称、状态与播报；所有覆盖的 modal、slider、审批、任务及业务失败进行逐场景操作。非文本状态 3:1；正常文字 4.5:1；检查透明和实际背景。
- Windows/macOS 及 Android/iOS：实际设备、横竖屏、安全区、字体 200%、平台触控目标、减少动画、窄屏与平板。不能由静态计算替代。
- 原 UI visual regression CI 上传 baseline/candidate/diff 和报告；复核所有未批准差异，不得自动批准。保存运行 ID、基线 SHA、候选 SHA、图片路径和独立审核。
- 原始检查时 CI 为 queued/pending。当前工作环境没有 Flutter SDK 或可启动的完整仓库/产品，未运行 Flutter 或 Chromium 产品 UI，未生成图片。全部三端测试与截图均待验收。保持 PR Draft，不作合规声明、不以旧结果替代当前候选。
