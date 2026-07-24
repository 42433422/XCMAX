# 逐项验证清单（初始化 5 卡 + 系统设置）

对照引导顺序：`welcome` → `industry` → `host-pack` → `seed-demo` → `first-ai-task`（见 `PRODUCT_USER_FLOW.md`），再全面走系统设置。

## A. 初始化 5 功能卡片

| # | 卡片 / 步骤 | 路由 / 入口 | 验证要点 | 录屏 | 结果 |
|---|-------------|-------------|----------|------|------|
| 1 | 欢迎 welcome | `/onboarding?step=welcome` | 文案可见、可下一步 | `rec/01-welcome.*` | ☐ |
| 2 | 行业 industry | `/onboarding?step=industry` | 可选行业、确认后进入下一步 | `rec/02-industry.*` | ☐ |
| 3 | 宿主能力包 host-pack | `/onboarding?step=host-pack` | 检测 / 一键装齐、deliverable 相关状态 | `rec/03-host-pack.*` | ☐ |
| 4 | 演示种子 seed-demo | `/onboarding?step=seed-demo` | 种子写入成功、可跳过/继续 | `rec/04-seed-demo.*` | ☐ |
| 5 | 首个 AI 任务 first-ai-task | `/onboarding?step=first-ai-task` | 能发起/完成示意任务并进入主界面 | `rec/05-first-ai-task.*` | ☐ |

## B. 系统设置（全面）

入口：侧栏 / 主界面 → **系统设置**（`SettingsView`）。

| # | 分区（按实际 UI 勾选） | 验证要点 | 录屏片段 | 结果 |
|---|------------------------|----------|----------|------|
| B1 | 基本 / 账号 | 显示本地 SQLite 路径、版本信息 | `clips/settings-basic.*` | ☐ |
| B2 | 外观 / 语言 | 切换后即时生效或提示重启 | `clips/settings-appearance.*` | ☐ |
| B3 | 数据 / 备份 | 路径可见、备份/导出入口可点 | `clips/settings-data.*` | ☐ |
| B4 | AI / LLM | 模型或平台配置可见、保存不报错 | `clips/settings-ai.*` | ☐ |
| B5 | 更新 / 关于 | 检查更新、关于页版本与 SKU | `clips/settings-update.*` | ☐ |
| B6 | 其它可见分区 | 逐项点开无白屏/死链 | `clips/settings-misc.*` | ☐ |

完整设置走查也可合成一条：`rec/06-system-settings.mov`。

## C. 签字

| 项 | 值 |
|----|-----|
| 机器 / OS | |
| 安装包 / buildSha | |
| 操作人 | |
| 日期 | 2026-07-24 |
| 总评 PASS / FAIL | ☐ |
