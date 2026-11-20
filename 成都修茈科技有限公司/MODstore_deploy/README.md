# MODstore_deploy（姊妹栈 · 全仓实体）

日更全链路、Vibe 双清单、`daily_action_items` 行动看板、派发/部署状态回写的 **Python 后端实体**落在此目录。

## 关键模块

知识混合检索复用 [BM25S](https://github.com/xhluca/bm25s) `0.3.16`（MIT，`knowledge` extra 固定版本），替换 rank-bm25 与向量候选内的二次关键词筛选。关键词从当前授权语料独立召回，再与向量结果做 RRF 融合；产品侧仅保留实体权限、分页读取与结果适配。

| 模块                                      | 职责                                        |
| ----------------------------------------- | ------------------------------------------- |
| `modstore_server/digest_vibe_prep.py`     | Vibe 预备 → 更新/补丁双清单 MD              |
| `modstore_server/digest_action_items.py`  | 解析 MD → `daily_action_items` 落库 + 回写  |
| `modstore_server/action_items_api.py`     | `GET /api/admin/action-items` 等 API        |
| `modstore_server/daily_digest.py`         | 08:00 digest 主流程（含 action items 钩子） |
| `modstore_server/digest_line_executor.py` | 派发成功 → `dispatched` 回写                |
| `modstore_server/approval_dispatcher.py`  | 部署合并 → `merged` 回写                    |

## 本地启动

```bash
bash FHD/scripts/dev/run_modstore_daily_local.sh restart
```

默认使用本目录（工作区 `成都修茈科技有限公司/MODstore_deploy`）；若目录缺失则回退 `~/XCMAX-archives/.../MODstore_deploy`。

治理与员工包构建共用仓库包。在仓库根安装开发依赖：

```bash
python -m pip install -e packages/retort_engine -e packages/xcagi_common \
  -e './成都修茈科技有限公司/MODstore_deploy[web,governance]'
```

员工目录内的 `build_xcemp.py` 与资产流水线共用 `xcagi_common.employee_pack`，
保留原来的包内目录和各员工的文件包含规则。仓库内可直接运行入口；导出到仓库外的
员工源码需要在构建环境安装 `xcagi-common`，生成的 `.xcemp` 无此构建依赖。

## 前端看板

`XCAGI-Full-Pipeline.html` → `#s-gaps` / `#s-roadmap` 由 `docs/xcagi-dashboard/emp-wf-action-items.js` 拉取本栈 `:8788` API 动态渲染。

## 管理端小 C

工作动态复用 [Element Plus Timeline 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（MIT）呈现工单回执。交付跟进沿用现有客服工单的员工路由、恢复和显式审批；站内提醒由 [APScheduler 3.11.3](https://github.com/agronholm/apscheduler/tree/3.11.3)（MIT）在 MODstore 调度进程运行。只有显式关注的交付工单进入提醒，截止时间来自工单字段。

私人记忆由 FHD 的 MemoryV2 保持权威记录并用 [Mem0 2.2.1](https://github.com/mem0ai/mem0/tree/v2.2.1)（Apache-2.0）召回。管理端从 Persona-A 读取对话风格。管理员通过「工作动态 → 我的记忆」主动新增、更正或删除记忆。部署时在 FHD API 和 MODstore API 的受保护环境中配置同一个专用 `XIAOC_ADMIN_CONTEXT_TOKEN`，MODstore 通过 `XIAOC_ADMIN_CONTEXT_FHD_URL`（未设置时用 `XCAGI_FHD_INTERNAL_URL`）访问 FHD 内网。管理员需用同一账号在 FHD 保持有效的管理端登录。未联通时，记忆区会提示不可用，普通小 C 对话和交付跟进仍可使用。详见 [FHD 复用说明](../../FHD/README.md#对话上下文与技能的来源)。

# Company ticket read grants

`GET /api/customer-service/tickets?offset=0&limit=50` and
`GET /api/customer-service/tickets/{id}` accept an independent `cst_ro_` service
credential with exactly `customer-tickets:read`. All other paths/methods are
denied before dispatch; ordinary account ownership rules remain in place.
The scope covers existing customer-service ticket intents, including delivery
tickets stored in that table. It does not grant artifact downloads or access to
Para development tasks. Deadlines are not recorded in this table, so overdue
state is returned as unknown, never inferred from age.

Set `MODSTORE_INSTANCE_ID` and `MODSTORE_TICKET_READ_GRANTS_FILE` on the server.
The latter must be a regular owner-only file (0600), owned by root/service user:

```json
{"instance_id":"fixed-instance","company_id":"fixed-company","owner_user_ids":[1,2],"grants":[{"id":"dot-read","principal":"dot","scopes":["customer-tickets:read"],"token_sha256":"SHA256_OF_RANDOM_SERVICE_CREDENTIAL","expires_at":"2026-11-01T00:00:00Z","revoked":false}]}
```

An operator must populate `owner_user_ids` from the company's authoritative
account membership, including its customer accounts; no wildcard is supported.
New accounts require an explicit membership update. Create separate grants for
`dot` and `grok-bot`. Only credential hashes belong on the server. Keep plaintext
credentials in each executor's protected local file or credential manager, never
in source, chat, tool arguments or Para tasks. Removing a grant or setting
`revoked:true` takes effect on the next request. `ticket_read` logs record grant,
route, allow/deny and response status; retain INFO logs in the server audit sink.

### 模型池组件

复用现有模型目录、凭据路由和钱包预授权。跨供应商对话路由及模型限制元数据使用
[LiteLLM 1.109.3](https://github.com/BerriAI/litellm/tree/v1.109.3) 的 MIT 许可 SDK。
对话与看图使用现有 Chat API，图片生成使用图像代理，语音使用现有 MiMo 协议适配。
管理端可调用 `POST /api/llm/admin/runtime-route/probe-operation` 验证指定模型的指定操作。

桌面生图复用现有 OpenAI 图像适配器及 Java 钱包。平台代付只接受官方
[OpenAI 图像生成用量回执](https://developers.openai.com/api/reference/resources/images/methods/generate)，
且需要为实际模型配置有效 token 定价。缺用量或结算回执不确定时保留原请求待核对。

计费继续使用 LiteLLM 1.109.3 的标准用量字段、现有 Java 钱包和客户端请求账本。
流式对话与生图在结算前保存用量、价格、请求号和预授权号。响应丢失后用认证钱包读回
核对已结算的同一请求，原子补齐用量流水及请求回执。事件持久化参考
[Lago](https://github.com/getlago/lago) 的幂等用量事件，资金状态参考
[TigerBeetle](https://docs.tigerbeetle.com/coding/two-phase-transfers/) 的两阶段转账。

兼容网关接受 `Idempotency-Key`，原生对话及视频接口接受 `client_request_id`。
实时语音沿用回合标识与现有请求账本。视频回执在上游任务未完成时标记等待用量，
独立语音返回经校验的用量或未计费状态。没有有效计费合同的媒体入口继续报告零平台扣费。
