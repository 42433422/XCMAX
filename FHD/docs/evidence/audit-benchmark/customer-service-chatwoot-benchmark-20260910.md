# R22 外部标杆实测：客服域开源锚点（Chatwoot Community）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Chatwoot Community v4.17.1（docker.1ms.run/chatwoot/chatwoot:v4.17.1 官方镜像，Rails 7.2 + pgvector，MIT），本地 Docker 端口 13000→3000；`FHD/config/audit_benchmark_ssot.json` 锁定 source_commit=b227f80427（develop，2026-09-08）。**版本偏差登记**：develop 镜像层在可用镜像源缺失无法按 commit 精确构建，改用同期最新稳定 tag v4.17.1（2026-09 发布，与锁定 commit 同一发布窗口）；必选语义（隔离/交接/回执）在两版间无契约变更 |
| dataset_hash | 任务脚本随本文档存档（customer-service-chatwoot-tasks-20260910.py，引导脚本 customer-service-chatwoot-bootstrap-20260910.rb） |
| task_protocol | B1 客户/会话/工单归属按账号隔离；B2 多渠道接入与人工交接保留上下文；B3 发送状态与失败重试以渠道回执为准 |
| predeclared_metrics_and_tolerances | 跨账户读取会话=404（精确）；错账户 token=401（精确）；联系人/会话列表零跨账户泄漏（精确）；分配后 meta.assignee.id=目标 agent（精确）；交接前后消息集合包含全部历史（精确）；webhook 注册 200+可列出（精确）；出站消息 status=sent（精确） |
| environment | 本机 macOS Docker（Colima），HTTP 一律 `--noproxy '*'` / `no_proxy=*`；PG 用 pgvector/pgvector:pg16（v4.x schema 依赖 vector 扩展） |
| observed_results | B1/B2/B3 全部 11 项 PASS（见下表） |
| unknowns | 真实渠道（WhatsApp/Telegram/Email）收发回执与失败重试未覆盖——本地仅 web_widget 渠道，外部渠道需真实凭据；人工交接的「转接给其他客服」多跳链路未覆盖——以分配（assignment）+上下文完整近似；商业锚点（Zendesk/Intercom/Freshdesk）未实测 |
| domain_status | customer-service 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 Chatwoot 双账户环境完整隔离+交接+回执任务） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1-1 会话归属创建账户 | customer-service-B1 | PASS | 会话 `account_id=1` 与创建账户一致 |
| B1-2 列表按账户隔离 | customer-service-B1 | PASS | A 账户会话列表含 A 的 uuid、不含 B 的 uuid |
| B1-3 跨账户读取会话被拒 | customer-service-B1 | PASS | A token GET B 会话（按 uuid）→ HTTP 404 |
| B1-4 错账户 token 被拒 | customer-service-B1 | PASS | A token 走 `/accounts/2/...` 路径 → HTTP 401 |
| B1-5 联系人按账户隔离 | customer-service-B1 | PASS | A 联系人列表=`['Cust A']`，无 Cust B |
| B2-1 会话消息可追加 | customer-service-B2 | PASS | outgoing 消息 POST → 200 |
| B2-2 人工交接（分配）生效 | customer-service-B2 | PASS | assignments → 200，`meta.assignee.id=2`（目标 agent） |
| B2-3 交接后上下文完整 | customer-service-B2 | PASS | 消息列表含 `hello from A`+`second message`+系统分配事件，交接不丢历史 |
| B3-1 渠道回执事件可订阅 | customer-service-B3 | PASS | webhook 注册（message_created/conversation_updated）→ 200 |
| B3-2 消息带投递状态字段 | customer-service-B3 | PASS | 出站消息 `status=sent`（非静默，可查询） |
| B3-3 回执订阅可审计 | customer-service-B3 | PASS | webhooks 列表返回 1 条订阅记录 |

## 部署要点（复跑必读）

1. **代理**：宿主所有 HTTP 一律 `--noproxy '*'` / `no_proxy=*`（同 java-payment 域教训）。
2. **PG 镜像**：v4.x schema 含 `create_extension "vector"`，必须用 pgvector 镜像（普通 postgres 会 500）。
3. **env 变量名**：Chatwoot 用 `POSTGRES_DATABASE`/`POSTGRES_USERNAME`（非 `POSTGRES_DB`/`POSTGRES_USER`），production 默认库名 `chatwoot_production`；`SECRET_KEY_BASE`（非 `SECRET_KEY`）。
4. **schema 引导**：`bundle exec rails db:chatwoot_prepare`（预建 pg_stat_statements/pg_trgm/vector 扩展后一次成功）。
5. **API 形态**：`api_access_token` 头（`AccessToken(owner_type:"User")`）；inbox 创建 `channel.type` 用短名 `web_widget`；webhook body 键为 `url`（非 `webhook_url`）且需 `subscriptions`；assignee 在 `meta.assignee`。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R18（客来来后端 174 项全绿：会话归属隔离、人工交接、渠道回执状态机均有单测+集成覆盖）。
本记录证明 Chatwoot 开源基线在同等必选语义（账号级数据隔离、跨账户访问拒绝、人工交接保留上下文、
出站消息投递状态可查、回执事件可订阅可审计）上行为一致，XCMAX 客服契约不低于该开源锚点；
不据此宣称达到商业产品水平（90 分锚点未实测，且真实外部渠道回执一项锚点侧因无渠道凭据未覆盖、
XCMAX 侧以支付宝/企微回调验签单测覆盖，属范围差异而非能力差异）。
