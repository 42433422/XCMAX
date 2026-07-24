# 闭环缺口（复测 · 源码后端）

从智能对话起，16/16 页能力读写闭环通过（stamp=95006，用户 wuxinghua1）。

## 本轮额外修复

- **AI 群聊消息 500**：桌面缺 `SECRET_KEY` 时加密存储抛错；已按 `XCAGI_DATA_DIR` 派生稳定密钥回退（`group_chat/storage.py`）。

## 说明（非失败）

- 桌面端 `GET/POST /api/admin/ai-groups` → 403（`ADMIN_DESKTOP_FORBIDDEN`）属设计；闭环走 `/api/mobile/v1/ai-groups`。
- `/api/orders/today` 会被 `{id}` 路由吃掉，前端未用；勿当「今日订单」接口。
- 知识库 RAG/embedding 可为 off；入库与 query 接口仍 200。
- 打印机：本机检测到 `Canon_TS3700_series` 就绪。
