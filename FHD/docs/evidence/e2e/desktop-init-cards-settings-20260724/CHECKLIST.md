# 逐项验证清单（初始化 5 卡 + 系统设置）

> 壳：`/Applications/XCAGI.app` · SKU `enterprise` · `1.0.0.0` · buildSha `16a9cf27322be4b85d902cdf664a6ddb3cb645a8` · 2026-07-24T08:07:09.824Z  
> 账号：用户已登录会话（`wuxinghua1`）· CDP 9222 / API :17500  
> 素材：shots=41 png · rec=8 mp4 · clips=15 mp4

## A. 初始化 5 功能卡片

| # | 卡片 | 录屏 | 结果 | 备注 |
|---|------|------|------|------|
| 1 | welcome | `rec/01-welcome.mp4` | ☑ PASS | 企业版文案与五步进度可见 |
| 2 | industry | `rec/02-industry.mp4` | ☑ PASS | 7 行业可选，已选「通用」 |
| 3 | host-pack | `rec/03-host-pack.mp4` | ☑ PASS | 侧栏预览：业务对象/组织管理/单据等 9 项 |
| 4 | seed-demo | `rec/04-seed-demo.mp4` | ☑ PASS | 若已写入会跳到 AI 验收步；见 shots/04-* |
| 5 | first-ai-task | `rec/05-first-ai-task.mp4` | ☐ FAIL | **运行 AI 演示任务 → Method Not Allowed** |

主壳侧栏抽查：`rec/00-main-shell.mp4`（对话/生态/员工工作台/业务对象/审批中心）。

## B. 系统设置（9 张 accordion 全开）

| # | 分区 | 素材 | 结果 |
|---|------|------|------|
| B1 | 个人主页 | `clips/settings-00-个人主页.mp4` · `shots/06-settings-all-00-*` | ☑ PASS |
| B2 | 模型服务 | `clips/settings-01-模型服务.mp4` | ☑ PASS |
| B3 | AI 意图能力 | `clips/settings-02-AI_意图能力.mp4` | ☑ PASS |
| B4 | 拟人 Persy 系统 | `clips/settings-03-拟人_Persy_系统.mp4` | ☑ PASS |
| B5 | 基本设置（外观/语言/数据） | `clips/settings-04-基本设置.mp4` | ☑ PASS |
| B6 | 移动端连接 | `clips/settings-05-移动端连接.mp4` | ☑ PASS |
| B7 | 扩展与 Mod | `clips/settings-06-扩展与_Mod.mp4` | ☑ PASS |
| B8 | 蒸馏模型版本 | `clips/settings-07-蒸馏模型版本.mp4` | ☑ PASS |
| B9 | 关于 | `clips/settings-08-关于.mp4` | ☑ PASS |

完整设置走查：`rec/06-system-settings.mp4` · 全流程：`rec/00-full-walkthrough.mp4`

## C. 签字

| 项 | 值 |
|----|-----|
| 机器 / OS | macOS arm64 |
| 安装包 / buildSha | 1.0.0.0 / 16a9cf27322be4b85d902cdf664a6ddb3cb645a8 |
| SKU | enterprise |
| 操作人 | 用户登录 + Agent CDP |
| 日期 | 2026-07-24 |
| 总评 | **条件 PASS**：5 卡 UI 可演示；**AI 演示任务 API 405 记缺陷**；设置 9 卡全截图 |

### 已知缺陷
- first-ai-task：「运行 AI 演示任务」返回 Method Not Allowed（见 `shots/05-first-ai-task-action.png`）
