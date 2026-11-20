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

## Para 云端平台模型

XCMAX 读取现有平台额度快照。启用 `MODSTORE_PARA_PLATFORM_POOL=1` 后，新派工先检查已验收的流式 Responses、工具调用和实际 token 回执，再按供应商及资源的有效余量选模。共享额度无法核验或低于保留线时等待。`MODSTORE_PARA_PLATFORM_RESERVE_PERCENT` 默认 80，可提高到 100 暂停新派工。

在 `MODSTORE_PARA_PLATFORM_ROUTES` 里登记 LiteLLM 别名及对应的上游资源，例如 `{"xcmax-para-coding":{"provider":"minimax","resource":"general","capabilities":["responses_stream","tool_calling","token_usage"]}}`。`MODSTORE_PARA_PLATFORM_CAPABILITY_PROFILES` 可分别为 `repair` 和 `benchmark` 添加入场所需能力，例如 `{"benchmark":["verified_long_context"]}`。角色配置不能移除基础能力。只登记实际验收过的能力。

额度余量相同时，在 `benchmark_ids` 按来源配置精确标识，如 `{"livebench_coding":"mimo-v2.6-pro"}`。使用 [LiveBench 2.0 Coding](https://livebench.ai/) 和 [DeepSWE](https://deepswe.datacurve.ai/) 的公开源，每 6 小时按需刷新。每榜只有覆盖所有同额度候选时才计入排名，DeepSWE 限同一 mini-swe-agent 测试范围及完整跑分。按榜内名次汇总，避免直接混合不同榜单的分数。回执记录采用的榜单和日期。修改别名所指模型后须重新验收并更新确切标识。

MiniMax 和小米 Token Plan 读取供应商公开的真实余量，使用同池 `general` 资源。其他供应商在没有可核验共享余量时等待。管理端回执仅携带通过能力和额度检查的候选。Para 复用已有 Codex 模型回退器，真实任务前若只读探活报额度不足，按回执候选顺序切换。实际任务已开始时保留原回执和变更供核对。

GitHub 配置 `PARA_PLATFORM_POOL=1` 和 `PARA_PLATFORM_GATEWAY_URL=https://…/v1`。Secret `PARA_PLATFORM_GATEWAY_KEYS_JSON` 映射网关别名到独立限额虚拟密钥，如 `{"alias-a":"<key-a>","alias-b":"<key-b>"}`。旧的单密钥 Secret `PARA_PLATFORM_GATEWAY_KEY` 仍可用于共用额度。使用 [LiteLLM Proxy 的 Codex Responses 接入](https://docs.litellm.ai/docs/proxy/client_setup/codex_cli) 和有限额的虚拟密钥。启用前在网关配置 Para 的模型白名单、预算及 RPM/TPM，按需要在供应商侧划分硬配额。派工检查只控制新任务准入，运行中金额和速率由网关限制。缺少可核验额度时任务等待。

网关验收目标固定为 [BerriAI/litellm v1.108.6 LTS](https://github.com/BerriAI/litellm/releases/tag/v1.108.6)，镜像 `ghcr.io/berriai/litellm:v1.108.6`；使用上游该版本发布页指定的固定公钥验证 cosign 签名后再部署。上游非 enterprise 目录使用 [MIT 许可证](https://github.com/BerriAI/litellm/blob/v1.108.6/LICENSE)，enterprise 目录适用其独立许可证。此记录不代表网关已部署或生产验收通过；实际镜像摘要、签名、配置和端到端计费仍需核对。

如 Para 使用专用火山 Agent Plan，可在平台池模式下设置 `MODSTORE_PARA_ARK_PLAN_FIRST=1`，并在 GitHub 将 `PARA_CODEX_MODEL_CANDIDATES` 设为 `ark-code-latest`。Codex 使用专用 `PARA_CODEX_API_KEY` 直连。关闭火山超额后付费可确保套餐用尽时返回额度错误。只读探活收到火山套餐额度耗尽错误后，从已通过平台保留额度检查的候选中切换。 [火山错误码](https://docs.volcengine.com/docs/ark/error-codes?lang=zh) · [超额后付费规则](https://docs.volcengine.com/docs/ark/agent-plan-personal-over-quota-postpaid-rules?lang=zh)

2026-11-20 生产 `/v1/responses` 已实测的别名如下。供应商目录中的模型在实测通过前只作为待验收项。实际 Para 派工仍要求额度通过。

| 网关别名 | 上游模型 | 计价依据 |
| --- | --- | --- |
| `xcmax-para-coding` | MiniMax-M2.7 | Token Plan 共享额度。普通 API 价表仅供参考 |
| `xcmax-xiaomi-fast` | MiMo V2.6 Flash | 小米 Token Plan 共享积分。普通 API 价表仅供参考 |
| `xcmax-xiaomi-code` | MiMo V2.6 Pro | 小米 Token Plan 共享积分 |
| `xcmax-doubao-code` | 豆包 Seed 2.1 Pro 260915 | 方舟按量。标准在线推理非音频输入 ¥6、输出 ¥30 / 百万 token。缓存按官方表单列 |
| `xcmax-kimi-code` | kimi-for-coding | Kimi Code 会员共享额度 |
| `xcmax-kimi-k3-256k` | k3-256k | Kimi Code 会员共享额度 |
| `xcmax-kimi-k3-1-pro` | k3.1-pro | Kimi Code 会员共享额度 |

[小米价表](https://mimo.mi.com/docs/price) · [MiniMax 价表](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise) · [火山方舟价表](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh) · [Kimi Code 会员额度](https://www.kimi.com/resources/coding-plan)
