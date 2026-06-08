# 工作台「说」语音定位 vs 豆包 / ChatGPT Voice

## 一句话

**豆包、ChatGPT Voice 是「语音会话产品」（像打电话）；我们是「工作台语音入口」（边聊边挂工作台上下文，可转任务、进制作流）。「平台模式」是临时纯聊护盾，默认开启，避免误触制作。**

## 对比

| 维度 | 豆包 Seeduplex（App 全量） | ChatGPT Voice | 本工作台「说」 |
|------|---------------------------|---------------|----------------|
| 产品形态 | 独立语音会话产品 | 主聊天内 / 独立语音模式 | 嵌在统一工作台第三档 |
| 会话目标 | 完成一轮自然对话 | 语音对话 + 转录、打断、多模态 | 先聊顺 → 可转任务 → Mod/员工/Skill 制作 |
| 上下文 | 应用内对话历史 | 主线程或独立会话 | 工作台档位、附件、规划/编排状态 |
| 制作流 | 无（或另入口） | 无对等概念 | 关「平台模式」后暴露做 Mod/做员工 |
| 平台模式 | 无 | 无 | **默认开**：隐藏制作按钮，语音走纯聊天路由 |

## 平台模式（实现要点）

- **默认**：`sessionStorage` 未设置或 v2 迁移前误写 `'0'` → 进入「说/做」时 `platformChatMode=true`，顶栏仅高亮「平台模式」，隐藏做 Mod/做员工/档位。
- **用户关闭**：点击「平台模式」→ 持久化 `'0'`，恢复制作工具条；语音可走 `routeVoiceUtterance` 制作分支。
- **一档「聊」**：仅本地关闭平台 UI，**不写** sessionStorage，避免覆盖「说/做」默认偏好。

代码入口：

- 偏好读写：[`src/utils/workbenchPlatformChatMode.ts`](../src/utils/workbenchPlatformChatMode.ts)
- UI 与路由：[`src/views/WorkbenchHomeView.vue`](../src/views/WorkbenchHomeView.vue)（`platformChatMode`、`voiceHumanChatMode`、`enablePlatformChatMode`）
- 空态文案：[`src/components/workbench/voice/VoiceFlowPanel.vue`](../src/components/workbench/voice/VoiceFlowPanel.vue)

## 电话式体验（豆包对标，已实现）

默认 `voiceSpeechMode: unified`（单 WebSocket：流式 ASR partial → provisional LLM+TTS → finalize 纠错）。

| 能力 | 说明 |
|------|------|
| 更早开答 | partial 稳定约 **380ms** 发 `utterance_start`（`VOICE_PHONE_ENDPOINT`） |
| 动态判停 | 静音约 **520ms** 提交；FunASR offline 再 finalize |
| 全双工 | unified/s2s 播报时 **不** 关麦；用户说话触发 barge-in |
| 即时 UI | 球体随听/说/播报切换；波形在播报时仍可见；流式字幕 |

后端：`/api/workbench/voice/unified/ws` 支持 `utterance_start` / `utterance_finalize` / `end_utterance`。

个性化设置里若仍为「级联 cascade」，可在设置中切到 **统一语音 unified**。

## 手动验收

1. 清空 `sessionStorage` 的 `wb_platform_chat_mode_v2` 后刷新，进入「说」→ 顶栏仅「平台模式」高亮，无做 Mod/做员工/档位。
2. 关闭平台模式 → 制作按钮出现；刷新 → 仍为关（`'0'`）。
3. 平台模式开时说闲聊 → 不弹员工规划；关闭后说「帮我做一个 XX 员工」→ 可走制作路由。
