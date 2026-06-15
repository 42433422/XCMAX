# i18n  rollout（zh-CN + en-US）

## 架构

- **vue-i18n@9**：`frontend/src/i18n/`，`legacy: false`
- **默认 locale**：`zh-CN`；**MVP 第二语言**：`en-US`
- **保留** `useIndustryUiText` / manifest `ui_labels` — Mod 动态术语不进 JSON

## Key 命名

```
{domain}.{surface}.{id}

chat.input.placeholder
chat.task.failed
shell.nav.settings
errors.UNAUTHORIZED
```

## 迁移顺序

| 阶段 | 范围 |
|------|------|
| P0 | Chat 栈（components/chat/*、useChatView 子模块） |
| P1 | Login、Settings、Sidebar、router 标题、shellMenuLabels |
| P2 | useApi 错误展示 + backend `error.code` 映射 |
| P3 | 其余 views（Mod 宿主仅 shell 字符串） |

## 后端契约

`app/http/error_codes.py`：`{ "error": { "code": "UNAUTHORIZED", "message": "..." } }`

前端：`t('errors.' + code)`，无 code 时 fallback `message`。

## 验收

- 浏览器 `localStorage.locale = 'en-US'` 后 Chat/Login/Settings 英文
- `useIndustryUiText` 行业覆盖仍生效
