# REST API 索引

## 在线交互文档（最权威）

- **Swagger UI**: `https://<your-host>/docs`
- **ReDoc**: `https://<your-host>/redoc`
- **OpenAPI JSON**: `https://<your-host>/openapi.json`
- **静态快照**: [`/contracts/openapi/modstore-server.json`](../contracts/openapi/modstore-server.json)（CI 用 diff）

## 主要业务模块（按 tags 分组）

| 前缀 | 模块 | 主要能力 |
| --- | --- | --- |
| `/api/auth` | 认证 | 登录、注册、刷新、忘记密码 |
| `/api/market` | 商品市场 | catalog 浏览、搜索、详情、收藏、购买、评价 |
| `/api/templates` | **模板市场（M3）** | 浏览、安装、从工作流另存为模板 |
| `/api/wallet` | 钱包 | 余额、流水、充值 |
| `/api/payment` | 支付 | 支付宝/微信下单、回调（实际由 Java 服务承载） |
| `/api/employees` | AI 员工 | 列表、状态、执行 |
| `/api/workflow` | 工作流 | CRUD、节点/边、触发器、沙盒、执行、**版本管理（M1）** |
| `/api/notifications` | 站内消息 | 列表、已读 |
| `/api/knowledge`, `/api/knowledge/v2` | 知识库 | 文档/向量检索 |
| `/api/llm` | 大模型 | 模型清单、BYOK 凭据 |
| `/api/openapi-connectors` | OpenAPI 连接器 | 解析、调用第三方 API |
| `/api/realtime/ws` | 实时 | WebSocket 事件流 |
| `/api/developer/*` | **开发者门户（M2）** | PAT 管理、Webhook 订阅、投递日志、测试发送 |
| `/v1/mod-sync/*` | **Mod 同步** | 使用账号 JWT 或带 `mod:sync` 的 PAT，将库与 XCAGI `mods/` 推送/拉回 |
| `/api/webhooks` | Webhook 管理 | 历史投递重放（仅管理员） |
| `/api/refunds` | 退款 | 申请、审批 |
| `/api/analytics` | 数据 | 看板汇总 |

## 工作流：从 0 到 1 的端到端

```
1. POST   /api/workflow/                            创建空工作流
2. POST   /api/workflow/{wid}/nodes                 添加节点（可重复）
3. POST   /api/workflow/{wid}/edges                 连线
4. POST   /api/workflow/{wid}/sandbox-run           沙盒测试（mock 员工）
5. POST   /api/workflow/{wid}/versions/publish      发布版本
6. POST   /api/workflow/{wid}/execute               生产执行（写入 workflow_executions）
7. GET    /api/workflow/{wid}/executions            历史执行
8. POST   /api/workflow/{wid}/versions/{vid}/rollback   回滚到指定版本
```

或者直接用前端 v2 编辑器（`/workflow/v2/{wid}`）拖拽，所有改动会增量调用上面这些 API。

## 模板市场

```
GET   /api/templates                                浏览（q/category/difficulty/sort）
GET   /api/templates/categories                     类别清单 + 计数
GET   /api/templates/{id}                           详情（含 graph_snapshot）
POST  /api/templates/{id}/install                   一键安装到我的工作流
POST  /api/templates/from-workflow/{wid}            把当前工作流另存为模板
```

## 开发者门户

```
GET    /api/developer/tokens                        我的 PAT 列表
POST   /api/developer/tokens                        创建（一次性返回明文）
DELETE /api/developer/tokens/{id}                   吊销

GET    /api/developer/webhooks                      我的订阅列表
POST   /api/developer/webhooks                      创建订阅
PUT    /api/developer/webhooks/{id}                 更新
DELETE /api/developer/webhooks/{id}                 删除
GET    /api/developer/webhooks/event-catalog        可订阅事件清单
GET    /api/developer/webhooks/{id}/deliveries      投递日志
POST   /api/developer/webhooks/{id}/test            发送测试事件
POST   /api/developer/webhooks/deliveries/{id}/retry  手动重试一次失败投递
```

## Mod 同步（账号化）

同步接口是写操作，不再使用全局 `MODSTORE_CATALOG_UPLOAD_TOKEN`。推荐在开发者门户创建带
`mod:sync` scope 的 PAT，用于本地 XCAGI / FHD 或 CI 脚本。

```
POST /v1/mod-sync/push   库 -> XCAGI/mods（仅服务端磁盘）
POST /v1/mod-sync/pull   XCAGI/mods -> 库（仅服务端磁盘）
GET  /v1/mod-sync/mods   列出当前账号可同步的 Mod（与 /api/mods 范围一致）
GET  /v1/mod-sync/export-zip/{mod_id}   下载与「工作台导出」相同布局的 zip（跨机：本机 modman remote-deploy）
```

跨机场景：线上在 `xiu-ci.com` 编辑库，本机 XCAGI 要更新时，在本机执行：

```bash
python -m modman remote-deploy --base-url https://xiu-ci.com --token pat_xxx --xcagi /path/to/local/XCAGI --mods my-mod
# 或一次拉全部「校验通过」且你有权限的 Mod：
python -m modman remote-deploy --base-url https://xiu-ci.com --token "$MODSTORE_PAT" --xcagi /path/to/XCAGI --all
```

请求体：

```json
{ "mod_ids": ["example-mod"] }
```

`mod_ids` 省略、`null` 或空数组表示“同步当前凭证允许的全部 Mod”：普通用户仅限自己拥有的
Mod，管理员可同步库内全部合法 Mod。

```bash
curl -X POST https://xiu-ci.com/v1/mod-sync/push \
  -H "Authorization: Bearer pat_xxx" \
  -H "Content-Type: application/json" \
  -d '{"mod_ids":["example-mod"]}'
```
