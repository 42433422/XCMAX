# 智能对话功能排查清单（路由 + 能力全景）

> 生成时间：2026-09-07，基于本地运行实例（127.0.0.1:17500）的 openapi.json 实测 + 代码核查。
> 用途：逐项排查「智能对话」端到端可完成的功能。每节含【入口】（真实路由）与【测试项】（可执行用例）。
> 状态标记：`[ ]` 未测 / `[x]` 通过 / `[!]` 失败（附现象）。

---

## 0. 软件路由全景（实测 1175 条路径 / 138 个 tag）

按业务域分组（条数为该 tag 下端点数）：

| 域 | 主要前缀 | 规模 | 说明 |
|---|---|---|---|
| 移动端 API | `/api/mobile/v1/*` | 99 | 会话、员工、审批、客户、AI 圈 |
| 管理端 | `/api/xcmax/admin/*` | 92 | 仅网页，桌面进程禁 admin 会话 |
| XCAGI 兼容层 | `/api/xcagi-compat/*` 等 | 78 | 旧入口转发 |
| 客服桥 | `/api/service-bridge/*` | 54 | 工单/客户管线 |
| 出货订单 | `/api/shipment*` `/api/orders` | 36 | |
| 考勤 mod | `/api/mods/attendance-industry/*` | 34 | 已按账号隔离（PR #1797） |
| Mod 商店 | `/api/mod-store` | 32 | |
| 认证 | `/api/auth/*` | 32 | 登录/会话 |
| ERP 域 | `/api/products` `/api/customers` `/api/inventory` `/api/purchase` | ~60 | |
| ETL/Excel | `/api/excel/*` `/api/etl/*` | 41 | |
| 知识库 | `/api/knowledge/v1/*` | 24 | 数据集/文档/Persy 记忆 |
| AI 助手 | `/api/ai/*` `/api/intent/*` | 29 | 本清单主角 |
| 打印 | `/api/print/*` | 20 | |
| 审批 | `/api/approval/*` | 28 | |
| IM | `/api/im/*` | 15 | |
| 财务 | `/api/finance*` | 26 | |
| 员工包 | `/api/emp-pack-*`（30+ 个角色） | ~100 | 每包 3 端点 |
| 其余 | lan/market/agent/ops/voice/ocr/tts/gdpr… | | |

---

## 1. 对话主入口（必测）

【入口】`app/fastapi_routes/ai_intent.py`
- `POST /api/ai/chat-unified`（及别名 `/api/ai/chat`、`/api/ai/unified_chat`、`/api/ai/chat/v2`）
- `POST /api/ai/chat/stream`（SSE 流式）
- `POST /api/ai/chat-unified/batch`（批量）
- 请求体：`message` / `user_id` / `source`（`pro`=专业模式）/ `context` / `file_context`

【测试项】
- [ ] 1.1 纯文本问答：`{"message":"你好"}` → 200，`success:true`，有回复文本
- [ ] 1.2 空消息 → `success:false`，提示"消息内容不能为空"
- [ ] 1.3 流式：stream 接口逐 token 返回，结束帧正常
- [ ] 1.4 批量：batch 多条消息各自有回复
- [ ] 1.5 上下文延续：先说"发货单 太阳鸟 5桶 20L"，再说"再来一份" → 命中 `repeat_last`，不重复追问
- [ ] 1.6 会话持久化：对话后 `GET /api/conversations/sessions` 能看到会话，`GET /api/conversations/{id}` 有消息记录
- [ ] 1.7 `POST /api/ai/context/clear` 清空后，"再一份"不再复用旧槽位
- [ ] 1.8 附件对话：带 `file_context`（上传 Excel 后追问）→ 能引用文件内容

## 2. 意图识别（`/api/ai/intent/test`、`/api/intent/predict`）

【实现】`app/services/intent_service.py`（规则+BERT）、`app/services/bert_intent_labels.py`（30 类标签）

BERT 标签全集：greet / goodbye / help / settings / negation / customers / customer_edit / customer_export / customer_supplement / products / materials / shipments / shipment_generate / shipment_records / shipment_template / template_extract / template_preview / excel_decompose / print_label / printer_list / show_images / show_videos / upload_file / wechat / wechat_send / tools_table / other_tools / business_docking / ai_ecosystem / unk

快捷模式（正则直判，`QUICK_INTENT_PATTERNS`）：`发货单XX 5桶`、`开单…桶`、`打印…规格` → `shipment_generate`

【测试项】
- [ ] 2.1 `POST /api/ai/intent/test {"message":"发货单 太阳鸟 5桶 20L"}` → `primary_intent=shipment_generate`
- [ ] 2.2 "你好" → `is_greeting`；"再见" → `is_goodbye`；"帮助" → `is_help`
- [ ] 2.3 "不要打印标签" → `is_negated=true`（否定不触发工具）
- [ ] 2.4 "查一下客户" → customers 类；"把张三的电话改成…" → customer_edit
- [ ] 2.5 "上传文件" / "看图片" / "看视频" → 对应意图
- [ ] 2.6 无意义输入 → `is_likely_unclear=true`，走澄清话术而非乱执行
- [ ] 2.7 `GET /api/intent/health` 正常；BERT 不可用时降级规则路径仍可用

## 3. 对话内 function-calling 工具（workflow 注册表，20 个）

【实现】`app/application/tools/workflow_registry_data_part0{1,2}.py`，OpenAI tools 格式，由 planner/orchestrator 调度

| 工具 | 用途 | 测试项 |
|---|---|---|
| excel_analysis | 读/查询/聚合 Excel | [ ] 3.1 "统计报价单里总金额" |
| excel_schema_understand | 表头/结构理解 | [ ] 3.2 上传异形表→识别 header_row |
| excel_join_compare | 两表关联比对 | [ ] 3.3 "对比这两个 Excel 差异" |
| excel_chart_recommend | 图表推荐 | [ ] 3.4 "这个数据适合什么图" |
| import_excel_to_database | Excel 入库 | [ ] 3.5 "把这个表导入产品库"（需确认流程） |
| template_preview | 模板预览 | [ ] 3.6 "预览送货单模板" |
| generate_office_document | 生成 Word/Excel/PDF | [ ] 3.7 "生成一份对账单"→返回下载 |
| list_orders / update_order / delete_order | 订单 CRUD | [ ] 3.8 查询→修改→删除全链路 |
| list_customers / update_customer / delete_customer | 客户 CRUD | [ ] 3.9 同上 |
| configure_report / list_report_configs | 报表配置 | [ ] 3.10 "给销售表配个日报" |
| create_role / update_role / delete_role / assign_role / list_roles | RBAC | [ ] 3.11 建角色→分配→列表 |

【安全项】
- [ ] 3.12 删除/写操作需确认卡片，未确认不执行
- [ ] 3.13 未登录/越权账号调用写工具 → 拒绝

## 4. 员工专属工具 TOOL_REGISTRY（58 个，运维/研发域）

【实现】`app/mod_sdk/employee_specialized_tools.py` L177-236；授权映射 `employee_specialized_tools_employee_map.py`；调度 `..._part04.py: handle_specialized`

分组速查：
- 质量：run_pytest, run_ruff_check, run_ruff_format, run_mypy, check_coverage, count_type_debt, count_raw_sql, run_arch_fitness, verify_version_anchors, verify_employee_contract, mutation_kill_report
- Git/发布：git_status, git_log, git_diff, git_branch, pack_release, list_deploy_scripts, trigger_gh_workflow
- 运维：nginx_test, api_health, mod_loading_status, disk_usage, tail_logs, performance_status
- 清单：list_mods, list_employee_packs, validate_employee_pack, duty_graph_health, list_docs, read_file, list_scripts, list_employees, employee_status, list_action_items, employee_autonomy_dashboard, list_workbench_sessions, list_enterprise_mods, list_users
- 执行：sandbox_python, patch_file, write_file
- 财务：check_transactions, list_invoices
- 前端/移动：frontend_lint, frontend_typecheck, frontend_test, android_gradle_build
- LLM 治理：read_llm_env_config, list_configured_providers, test_llm_key_health, query_provider_usage, compare_model_prices, list_vlm_models, get_vlm_route, query_local_token_usage, query_cursor_usage, query_codex_usage, query_trae_usage

【测试项】
- [ ] 4.1 对话"看下 API 健康状态" → 员工调 api_health 并回报
- [ ] 4.2 "跑一下后端测试" → run_pytest（耗时长，验证有进度/结果回执）
- [ ] 4.3 越权：无该工具授权的角色请求 → 拒绝
- [ ] 4.4 写类工具（patch_file/write_file）走 gate，需审批
- [ ] 4.5 `POST /api/tools/execute` / `POST /api/skills/execute` 直调 tool_id+params 链路通

## 5. AI 员工体系（对话可分派的角色）

【配置】`config/duty_roster.json`（enterprise_employees：lan_gate 局域网网关、label_print 标签打印、shipment_mgmt 出货管理、receipt_confirm 签收确认、workflow_automator 流程自动化、task_router_officer 任务派发、daily_orchestrator 每日编排、excel/word/ppt/pdf_generate 文档生成…）；员工包 30+ 个 `/api/emp-pack-*`

桌面端员工卡片中文名（已修复）：需求接入员、需求分析员工、流程自动化员工、产物生成员工、质检员工、用户客服员工、企业使用跟踪员

【测试项】
- [ ] 5.1 对话指定"让质检员工检查这份表" → 路由到对应员工并有产出
- [ ] 5.2 `GET` 员工列表/状态端点返回全部角色，无英文 ID 泄漏
- [ ] 5.3 员工间协作：需求接入→分析→产物生成 链式任务有 trace

## 6. 上下文注入（对话"看得见"的数据源）

【实现】`process_chat` 主链（`app/application/ai_chat_app_service_...mixin01.py` L110-111）：
`_inject_excel_vector_context` → `_inject_wechat_contact_context`

- Excel 向量：`/api/knowledge/v1/datasets/*` 文档入库后可被对话引用
- 微信情报：消息文本自动匹配联系人名（≥2 字，最长优先）→ 渲染【微信联系人情报】进 system prompt；显式 `context.wechat_contact_key` 优先
- Persy 记忆图谱：`/api/knowledge/v1/datasets/{id}/memories*`（查询/纠错）

【测试项】
- [ ] 6.1 上传合同文档进数据集 → 对话问"合同账期多久" 能引用
- [ ] 6.2 问"王总最近聊了什么" → 命中微信联系人，回复含情报
- [ ] 6.3 未命中联系人 → 静默降级，不报错不阻断
- [ ] 6.4 记忆查询/纠错接口往返正常
- [ ] 6.5 考勤情报：登录账号下问考勤数据 → 只看到本账号数据（隔离回归）

## 7. Neuro Bus / 事件联动

【入口】对话触发 `neuro_notify_chat_received` / `neuro_notify_chat_completed`；`/api/neurobus/*`；意图域 handler `app/neuro_bus/domains/intent_domain_handlers.py`

【测试项】
- [ ] 7.1 一轮对话后事件/追踪记录生成（chat trace 有 run_id）
- [ ] 7.2 熔断/限流开启时对话不中断（降级）

## 8. 多模态与外设

- 语音：`/api/voice/*`、`/api/tts/*`
- OCR：`/api/ocr/*`
- 打印：`/api/print/*`（打印机列表、标签打印意图 print_label）
- 图片/视频展示意图：show_images / show_videos

【测试项】
- [ ] 8.1 语音输入→识别→对话回复全链路
- [ ] 8.2 图片 OCR 进对话（"识别这张报价单"）
- [ ] 8.3 "打印标签" → printer_list/print_label 正确响应
- [ ] 8.4 "把结果导出 docx" → 报告导出（`/api/ai/kitten/report/export-docx`）

## 9. 对话周边管理

- [ ] 9.1 `POST /api/ai/conversation/new` 新建会话
- [ ] 9.2 `POST /api/conversations/sessions/clear` 清空
- [ ] 9.3 `GET /api/ai/config` / `GET /api/ai/context` 正常
- [ ] 9.4 专业模式 `source=pro` 与默认模式回复差异符合预期

---

## 执行建议

1. 优先跑 §1、§2、§3（核心对话+意图+工具），占用户可感知功能 80%。
2. §4 运维工具在开发者机本地跑才有意义，客户机可抽查 api_health/list_mods。
3. 失败项记录：请求体、HTTP 码、回复片段、期望差异，回填到本清单 `[!]` 标记处。

---

## 冒烟结果（2026-09-07，本地 17500 直测）

| 项 | 结果 | 说明 |
|---|---|---|
| 1.1 纯文本问答 | [!]→已修 | 「你好」原被 planner 判成 generic_workflow 并真的执行 query_products 查库；已加小闲聊短路（greeting/goodbye/help 固定话术，不调工具） |
| 1.2 空消息 | [x] | `success:false` + "消息内容不能为空" |
| 9.1 新建会话 | [x] | 返回 session_id |
| 1.6 会话持久化 | [!] | sessions 列表为空 + 后端日志每轮对话报 `跨会话记忆写入失败: near "EXTENSION" syntax error`——桌面 SQLite 上误用 PG pgvector store；已修：DATABASE_URL 为 sqlite 时自动降级 SQLite 向量 store（用户记忆 + Excel 向量两处） |
| 2.1 发货单意图 | [x] | 主链正确识别并返回确认卡片；`/api/ai/intent/test` 端点显示 shipments 属规则引擎分类口径差异，`QUICK_INTENT_PATTERNS` 为死代码（全仓无引用，待清理） |
| 2.2 问候/再见/帮助 | [x] | 意图层 is_greeting/is_goodbye/is_help 正确 |
| 2.3 否定保护 | [x] | "不要打印标签" → print_label + is_negated=true |
| 2.4 客户查询 | [x] | customers；customer_edit 细分依赖 BERT（桌面规则引擎归入 customers，可接受） |
| 2.5 上传/微信 | [!] | upload_file [x]；「发微信给张三」→wechat_send [x]，但「用微信通知李四」漏判（关键词覆盖不全，低优） |
| 2.6 无意义输入 | [x] | 不触发工具（is_likely_unclear 需短句，长句走 LLM 兜底属预期） |
| 4.5 tools/execute | [x] | products.query / customers.query 成功（注册表键=域+action，非 list_orders 这类动作名） |
| 8.x 多模态 | 待 UI 测 | 语音/OCR/打印需前端配合 |
| 其余 | 待测 | 需登录态 + UI 交互 |

**遗留待办**：
- [ ] 清理 `QUICK_INTENT_PATTERNS` 死代码或接入 pipeline
- [ ] wechat_send 关键词补「用微信通知」类变体
- [ ] 桌面端 LLM provider 未配置确认（专业模式回复疑似降级路径）

## 冒烟结果（2026-09-08 第二轮，本地 17500 直测）

> 注意：17500 实例为 #1799 合并前的旧构建，小闲聊短路/SQLite 向量修复未生效；以下标 `[源码已修]` 的项待新桌面包重建后复测。

| 项 | 结果 | 说明 |
|---|---|---|
| 1.3 流式 | [!] | SSE 帧结构正常（tool_progress→error），但上游 LLM 报 `平台错误(403): CSRF token missing`——桌面 provider 配置问题，与遗留待办同源 |
| 1.4 批量 | [x] | batch 多条各自回复、`count`/`batch` 字段正确；「你好」走 generic_workflow 属旧构建（短路 `[源码已修]` bd9c8281e） |
| 1.5 上下文延续 | [x] | 「再来一份」命中 repeat，不重复追问 |
| 1.7 清空上下文 | [x] | clear 后「再来一份」不再复用旧槽位 |
| 2.2 问候三件套 | [x] | intent 层 is_greeting/is_goodbye/is_help 正确 |
| 2.4 客户查询/编辑 | [x] | 查客户→customers；改电话→customer_edit（BERT 档） |
| 2.5 上传/图片/视频 | [x] | upload_file/show_images/show_videos 意图正确 |
| 2.6 无意义输入 | [x] | 「啊对对对」不触发工具 |
| 2.7 意图健康 | [x] | `/api/intent/health` 200；`model_available:false`（BERT 未打包，规则降级路径可用） |
| 9.1 新建会话 | [x] | 返回 session_id |
| 9.3 config/context | [x] | 均 200 |
| 槽位解析（1.5 衍生） | [!]→已修 | 「发货单 太阳鸟 5桶 20L规格」原解析成 单位=太阳鸟规格/编号=20L；已修 order_parser：倒装「20L规格/28的规格」归一为规格槽位、「20L」独立记法、单位名剥离「开单」；现统一输出「已识别：单位 太阳鸟，规格 20」+追问编号。回归 119 测试全绿（commit 63c8bbed5，随 #1801） |
| 3.6 模板预览 | [!]→已修 | 「预览送货单模板」原被「送货单」关键词截胡 → 走开单预览；已在 normal 路由新增 template_preview 识别让路（commit da3eefe5a，随 #1801） |
| 9.4 专业模式 | [!] | `source=pro` → 400 `ai_service_unavailable`——桌面 LLM provider 未配置（与遗留待办同源）；normal 模式走规则/planner 降级路径正常返回 |
| 5.2 员工列表 | 待 UI 测 | `/api/employees` 返回 catalog 结构（无英文 ID 泄漏问题在卡片层，#1799 已修兜底中文名），完整验证需重启新桌面包 |
| 3.8 订单 CRUD | [!] | `/api/tools/execute` 的 `orders` 是兼容桩：非 `view` 动作一律返回 `{success:true,message:"出货单"}`，不真正增删改。真实订单 CRUD 在 `/api/shipment*` REST 端点；此端点仅产品/客户/物料查询有效 |
| 3.12 删除确认门禁 | 分层澄清 | 确认门禁在「对话审批卡」层（workflow risk gate），不在 `/api/tools/execute` 裸端点——裸端点是本机兼容 shim，无鉴权无确认属设计预期。删除类需在对话链路（§3.5/§5.1）验证审批卡 |
| 4.5 tools/execute 查询 | [x] | `products`/`query`、`customers`/`query`、`orders`/`list` 均 200；注册表键=域+动作 |
