# XCAGI 企业 AI 桌面平台

XCAGI 位于 [XCMAX](https://github.com/42433422/XCMAX) 的 `FHD/` 子树。Windows 与 macOS 共用由 `main` 构建的宿主；客户定制通过版本化 Mod、账号权益和数据归属隔离交付。

本页只保留入口。功能、版本、架构和发布事实在既有 SSOT 中维护，避免重复说明漂移。

## 快速入口

| 内容 | 文档 |
|---|---|
| 日常工作与维护文档 | [START_HERE](docs/START_HERE.md)、[SSOT_INDEX](docs/SSOT_INDEX.md) |
| 开发环境与运行 | [QUICK_START](docs/QUICK_START.md) |
| 功能边界与目录职责 | [FEATURE_MAP](docs/FEATURE_MAP.md) |
| Mod 开发与权限 | [MOD_AUTHORING_GUIDE](docs/guides/MOD_AUTHORING_GUIDE.md) |
| AI 员工配置 | [AI_EMPLOYEE](docs/AI_EMPLOYEE.md) |
| 迁移与历史入口 | [MIGRATION_REGISTRY](docs/MIGRATION_REGISTRY.md) |
| 更新内容 | [CHANGELOG](CHANGELOG.md) |

## 开源组件选型

小 C 桌面浮窗复用已锁定的 [Electron 45.3.2](https://github.com/electron/electron/tree/v45.3.2)（MIT）`BrowserWindow` 和 `Tray`，沿用现有小 C 对话组件和同一登录会话。

开发自动化继续使用 [LangGraph 1.2.10](https://github.com/langchain-ai/langgraph)（MIT；checkpoint 4.3.0、SQLite 3.1.2 与已吸收的 PostgreSQL 适配版本见 `packages/retort_engine/pyproject.toml`）保存审批、中断和交付等待，不增加另一套任务引擎。GitHub 执行迁移到官方 Actions 独立 job：执行候选、受信发布、恢复原验证、独立验收；[checkout 4.4.0](https://github.com/actions/checkout/tree/11d5960a326750d5838078e36cf38b85af677262)、[upload-artifact 4.6.2](https://github.com/actions/upload-artifact/tree/ea165f8d65b6e75b540449e92b4886f43607fa02)、[setup-node 4.4.0](https://github.com/actions/setup-node/tree/49933ea5288caeca8642d1e84afbd3f7d6820020)、[setup-python 7.1.0](https://github.com/actions/setup-python/tree/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0) 均为 MIT，并在相关源 workflow 固定完整提交。候选用 Git 原生 bundle 传递，发布任务只导入对象，不执行候选代码；原共享身份发布入口保持禁用。

GitHub 业务适配复用 [HTTPX 0.28.1](https://github.com/encode/httpx/tree/0.28.1)（BSD-3-Clause）及 GitHub REST `2022-11-28` 的 merge SHA 并发守卫、dispatch run ID、Issues/Actions 持久回执；配置使用 PyYAML 6.0.3（MIT）。只保留任务归属、风险门禁、可信回执和最终版本校验等产品胶水。已知 Para 控制任务优先恢复；未知外部写入结果保留待核对，不能保证跨 GitHub/Para 的恰好一次。正式完成需受保护主干合入、同提交 CI/安全扫描、已有发布审批、部署证据及线上 SHA/制品摘要一致；分支验收不会提前归档为上线成功。共享宿主交付不替代桌面安装包及客户 Mod 的原有验收。操作入口见根仓 [CI SSOT](../docs/CI_SSOT.md#自治闭环autonomy)。

Retort 复用 Git 原生归档与 [GitHub Compare REST 2022-11-28](https://docs.github.com/en/rest/commits/commits?apiVersion=2022-11-28#compare-two-commits) 核对修复提交与实际发布的祖先关系。MODstore 通过 [GitHub artifact attestations](https://github.com/actions/attest-build-provenance/tree/e8998f949152b193b063cb0ec769d69d929409be)（MIT，锁定提交 `e8998f949152b193b063cb0ec769d69d929409be`）签署原生 Git tar（Git GPL-2.0），由 GitHub CLI 验证签名和签名工作流身份。部署回执绑定签名制品摘要、版本、实际发布 SHA 与公共运行读回。策展员沿用已审查执行包、Python 标准库 `zipfile` 和 Retort 已有加密证据存储，核对批准和原包后生成私有候选 `.xcemp`，读回包与执行凭证后登记完成。

客户反馈改进接入已有 Retort 的 LangGraph 和正式发布核验。管理端复用已锁定的 [Element Plus 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（MIT）表格、步骤和抽屉；审批仍显示准确脱敏复现并绑定摘要，公开计划不含客户原文。客户复现是不可信输入，管理员审批不授权其访问执行器凭据；当前 Codex/OpenCode 尚无不可导出的任务凭据，新的反馈修复执行、新分支推送和新 PR 均暂停为 `waiting_credential_isolation`。旧任务恢复只能读取已有执行及准确匹配的分支、PR，不重新派工或发布；普通非修复任务沿用原路径。群体效果按 [GrowthBook 5.2.0](https://github.com/growthbook/growthbook/tree/0bd125f5a1df8dcde5b1dd1996bc0bc7e1b1e73d)（开源核心 MIT，企业目录另行许可）的 REST v1 读取原统计，真实付费复用客户价值账本的支付源与退款排除规则。

已有 `MODSTORE_RETORT_PROTOCOLS` 的冻结验收方案可选配 `customer_feedback`。其中 `domain` 为 `platform` 或 `software`，`surface` 固定为 `shared_web`，`goal` 为适合公开派工的目标。若同时配置 `MODSTORE_RETORT_FEEDBACK_ACTOR_ID` 和 `MODSTORE_RETORT_FEEDBACK_TEMPLATE`，现有调度器每天自动选题一次；审批不能解除上述执行与发布暂停。可选的 `growthbook` 指定 `project`、`metric`、`minimum_users`，由 `MODSTORE_RETORT_GROWTHBOOK_URL` 和服务端只读 API 密钥连接实验。实验 `trackingKey` 使用 `xcagi-retort-<运行 ID>`，标签使用 `xcagi-release-<正式提交>`。`track_paid_outcome` 启用同一账号、订单、目标与制品的商业对账。实验或付费证据缺失时保持待核对。

演化信号的时间与数值护栏复用 Python 标准库 `datetime` / `math`：`generated_at` 按既有信号回看窗口判断新鲜度，`window` 仅表示统计范围，缺测和证据不足沿用原 `needs_human` 账本回执。

智能对话执行流复用现有 AI SDK / Vue 栈，选型和许可证如下：

| 层 | 固定来源 | 复用边界 |
|---|---|---|
| 桌面更新 | [electron-updater 6.8.11](https://github.com/electron-userland/electron-builder/tree/electron-updater%406.8.11/packages/electron-updater)，MIT | 沿用上游频道、灰度、制品哈希校验与安装。产品 provider 在同一次清单请求上验 Ed25519。Windows 未签名候选沿用 NSIS 安装包和临时手动下载流程。 |
| 执行卡片 | [shadcn-vue v2.9.0](https://github.com/unovue/shadcn-vue/tree/39cb0b277f009e47de2dc62c4217755fb9a27eec/apps/v4/registry/bases/reka/ui/trace)，MIT | `frontend/src/components/ui/trace/` 保留上游 Trace / Collapsible 结构及许可；仅替换样式、图标和 Vue getter，使用已有 Reka UI 2.11.0，无额外 CSS 框架。 |
| 消息状态 | [Vercel AI SDK 7.0.173](https://github.com/vercel/ai)，Apache-2.0，版本由前端 lockfile 固定 | `readUIMessageStream` 组装文本和工具事件，`ChatStatus` 提供会话状态。参考 [Open WebUI 的会话任务事件](https://docs.openwebui.com/features/extensibility/plugin/development/events/) 按会话分发，产品层只绑定账号、Mod、会话和审批回执。 |
| SSE 解析 | [eventsource-parser 3.1.1](https://github.com/rexxars/eventsource-parser)，MIT | 从现有传递依赖提升为直接锁定依赖，代替手写 SSE 分隔解析，支持碎片、CRLF、多行 data。 |
| 子进程观测 | Python 标准库 `multiprocessing.Pipe` | 只增加隔离工具与现有 StreamLifetime 的 JSON 进度适配，保留业务回执、绝对截止、进程回收、租户和审批控制。 |
| ELT 预演续租 | [CPython 3.12.13 threading](https://github.com/python/cpython/blob/v3.12.13/Lib/threading.py)，PSF-2.0 | 阻塞解析和字段映射期间使用线程及 Event，在独立短事务校验原租户和租约令牌。 |
| ELT 台账证据 | [openpyxl 3.1.5](https://openpyxl.readthedocs.io/en/3.1.5/)，MIT | 复用只读行列坐标。现有结构化模型只判断客户归属，入库校验逐行核对原件。 |

对话执行卡复用同一套 Trace 组件展示规划、附件读取、工具节点、确认和回执。规划占用状态栏，步骤数来自真实工具事件或运行回执。ELT 进度直接读取已持久化的阶段数据；流结束且缺少工具回执时显示“待核对”。正文和执行进度独立更新。

AIOPEN「系统地图」的能力目录直接读取 FastAPI 自动生成的 OpenAPI（框架自身能力，不另建索引表）；目录检索复用已锁定依赖 [scikit-learn](https://github.com/scikit-learn/scikit-learn)（BSD-3-Clause）的 TF-IDF 向量化与余弦相似度，按字符 n-gram 切分以兼容中文，不额外引入分词器或向量库；语义 overlay 使用已声明的 PyYAML（MIT）读取。MCP 协议层沿用官方 Python SDK（`mcp==2.3.0`，MIT）同一生态的 JSON-RPC 约定，未替换现有传输实现。

桌面语音沿用 [HTTPX 0.28.1](https://github.com/encode/httpx/tree/0.28.1)（BSD-3-Clause）和 websockets 16.1（BSD-3-Clause），由 XCAGI 绑定配置的出站地址。通话断句使用 [Pipecat Smart Turn v3.2 CPU](https://huggingface.co/pipecat-ai/smart-turn-v3/commit/f766f81d3cfdf7737ac64aad813d91bbfd56bf93)（BSD-2-Clause），桌面后端构建校验并打包固定权重。

扫描件与图片兜底复用 [RapidOCR](https://github.com/RapidAI/RapidOCR) `rapidocr-onnxruntime` `1.4.4`（Apache-2.0，ONNX，无 torch）：仅在 pdfplumber 提取不到文本的页面渲染后识别，`XCAGI_PDF_OCR=off` 可关闭，默认最多处理 30 个空页；同时支持直接导入 png/jpg/webp/bmp 图片。文本版 PDF 仍走 pdfplumber 的文本与表格。

知识库网页导入复用 [trafilatura](https://github.com/adbar/trafilatura) `2.3.1`（Apache-2.0，纯 Python）提取正文与标题，URL 导入与本地 `.html/.htm` 文件共用同一实现；联网复用锁定的 [urllib3](https://github.com/urllib3/urllib3/tree/2.8.0) `2.8.0`（MIT）连接池，把经全部 DNS 结果校验的数字 IP 作为连接目标，保留原域名的 Host、TLS SNI 与证书校验，不继承环境代理。产品侧只保留 SSRF 防护（拒绝内网/回环/保留地址、逐跳校验重定向、5MB/15s 限制）与租户隔离胶水；真实传输层回归确认路径中的地址不能更改连接目标。`XCAGI_KB_ALLOW_PRIVATE_URLS=1` 仅用于受控内网调试。

知识库对象存储导入复用 [boto3](https://github.com/boto/boto3) `1.44.4`（Apache-2.0）读取 `s3://bucket/key`：产品侧只做 URI 校验、可选桶白名单 `XCAGI_S3_ALLOWED_BUCKETS`、大小上限 `XCAGI_KB_MAX_OBJECT_BYTES`（默认 25MB）与错误归一化；S3 兼容存储用 `XCAGI_S3_ENDPOINT_URL` / `XCAGI_S3_REGION` 指向，凭证沿用标准 AWS 环境。

知识库 Confluence 导入直接调用站点 REST API（`GET /rest/api/content/{id}?expand=body.storage`），产品侧只保留配置校验、5MB/15s 限制与正文抽取；站点用 `XCAGI_CONFLUENCE_BASE_URL` 指定，凭据用 `XCAGI_CONFLUENCE_API_TOKEN`（可选 `XCAGI_CONFLUENCE_EMAIL` 启用 Basic Auth，否则 Bearer Token）。

知识库飞书文档导入调用开放平台 `tenant_access_token` 鉴权与 docx `raw_content` 接口，产品侧只做凭据校验、token 缓存、5MB/15s 限制与纯文本落库；应用凭据用 `XCAGI_FEISHU_APP_ID` / `XCAGI_FEISHU_APP_SECRET`，私有化域名用 `XCAGI_FEISHU_BASE_URL`。

知识库 Notion 导入调用官方 REST API 读取页面标题与块树（递归子块、分页、最多 500 块 / 3 层），扁平化为纯文本；集成 token 用 `XCAGI_NOTION_TOKEN`，自建代理域名用 `XCAGI_NOTION_BASE_URL`。

知识库语雀导入直接调用官方 REST `GET /api/v2/repos/{namespace}/docs/{slug}`（`X-Auth-Token`），正文取 Markdown（缺失时从 `body_html` 抽纯文本）；token 用 `XCAGI_YUQUE_TOKEN`，私有化域名用 `XCAGI_YUQUE_BASE_URL`，文档引用写成 `namespace/repo/doc`。

外部来源入库时记录 `source_kind` / `source_ref`（url、Confluence、飞书、Notion、语雀），`POST /datasets/{dataset_id}/documents/{document_id}/refresh` 可按坐标重新抓取：内容未变不产生新版本，变化则沿用原 source 与分块配置生成下一版本，供 diff / rollback 治理；`POST /datasets/{dataset_id}/documents/refresh` 批量同步当前租户可见来源并返回 changed/unchanged/failed/skipped 汇总；每次刷新记录 `last_source_sync_at`，批量同步传 `max_age_hours` 可只处理超时未同步的来源（返回 `fresh` 计数），适合定时任务反复调用。设置 `XCAGI_KB_AUTO_REFRESH_HOURS>0` 后应用会启动进程内定时同步线程（首次延迟 120 秒、最小间隔 5 分钟，随应用关闭退出），默认关闭。

知识库语义检索复用 [fastembed](https://github.com/qdrant/fastembed) `0.9.1`（Apache-2.0，ONNX Runtime，不依赖 torch）：`FHD_EMBEDDING_MODE=fastembed` 时默认中文模型 `BAAI/bge-small-zh-v1.5`，精排复用其 `TextCrossEncoder`（默认 `BAAI/bge-reranker-v2-m3-int8`，多语言 int8，约 0.57GB，需显式开启或 `FHD_RERANK_AUTO=1` 在 hash 降级时自动启用）。未安装或未启用时回退到 192 维「中英二元组带符号哈希」向量与词法重排（BM25 中文按字、剔除高频功能字），状态接口会如实报告 `semantic_embedding_available=false`。检索质量用 `scripts/dev/knowledge_retrieval_eval.py` 的 recall@k/MRR 评测，`--multi` 可把语料拆到 3 个知识库验证跨库检索。入库可带 `tags`（≤20 个、每个 ≤32 字），查询与跨库检索支持 `tags` 任一命中过滤（也可用 `metadata_filter` 做同样收窄）。纯文本/外部抓取入库时，同一租户下不同来源的正文完全一致时，入库直接复用已有文档（返回 `duplicate=true`/`duplicate_of`），需要保留副本可传 `allow_duplicate=true`；文件上传仍走指纹幂等。问答默认带低置信拒答：证据覆盖率低于 `XCAGI_KB_MIN_RELEVANCE`（默认 0.1，单次请求可用 `min_relevance` 覆盖）时明确回复「没有找到相关内容」，`--ood` 可验证域外问题拒答率；送入模型的证据默认限制 6000 字（`XCAGI_KB_MAX_CONTEXT_CHARS` 或请求 `max_context_chars` 调整），返回 `context_chars/context_truncated`。`XCAGI_KB_AUTO_QUESTIONS=1` 可在入库时为片段生成检索问题（写入 `metadata.auto_questions`，参与 BM25 与证据覆盖；每片 3 个、单次 20 片可调），默认关闭。检索支持可选的 MMR 多样性重排：查询与跨库检索传 `mmr_lambda`（0–1，0 关闭，也可用 `XCAGI_KB_MMR_LAMBDA` 设服务端默认），按「相关性 − 与已选结果的相似度」挑选片段，避免同一段内容的多份切片占满 top-k；有向量用余弦、hash 降级用查询词 Jaccard，`--diversity 0.7` 可对照评测。检索模式用 `retrieval_mode` 选择 `hybrid`（默认，向量 + BM25 + RRF）/ `vector`（仅语义）/ `keyword`（仅关键词，适合精确编号与型号），单库查询、跨库检索与问答都支持，`--mode` 可对照评测；混合模式还可用 `vector_weight` / `keyword_weight`（0–10，默认 1:1）调两路 RRF 权重。本语料 hash 下 keyword-only 0.8696/1.0/1.0、MRR 0.9348，BM25S 修复后默认混合 0.8551/0.9710/1.0、MRR 0.9147（69 题 hash 小语料，不代表生产语义验收）。需要整章证据时传 `expand_section=true`：命中块扩展为同一 Markdown 章节的完整正文（默认 4000 字预算、从命中块向两侧扩，不跨文档/版本/章节，结果标 `metadata.context_mode="section"`），即成熟的 small-to-big 检索。知识库问答框下方可直接切换「模式 / 整章扩展 / 多样性」，默认混合、关闭、关闭。PDF 表格入库会保留 `[table N]` 标记的 Markdown 表格，查询命中表格附近时结果附带 `metadata.table_context`（完整表头与各行，4000 字上限）。状态接口返回 `source_sync`（可刷新文档数、从未同步数、最近同步时间），检索质量由 `tests/test_application/test_knowledge_retrieval_baseline.py` 在 CI 中锁定基线。问答另提供 SSE 流式端点 `POST /datasets/{dataset_id}/query/stream`（`meta` / `delta` / `done` 事件，无平台模型时回退确定性答案），前端默认使用流式、失败自动回退普通查询；问答框下的「跨库」开关（存在多个知识空间时显示）改为调用 `POST /datasets/multi-query` 一次检索全部可见库。答案可点「有帮助 / 没帮助」提交反馈（`POST /datasets/{dataset_id}/feedback`，按租户隔离，`GET .../feedback` 汇总满意度），反馈独立存于 `dataset_feedback.json`，不触碰查询快照。术语表（同义词）用 `PUT /datasets/{dataset_id}/synonyms` 维护（`{退款: [退货, 退钱]}`），查询命中口语词时自动追加语料写法参与召回，前端问答「术语」按钮可编辑。未命中问题会记入知识缺口（`GET/DELETE /datasets/{dataset_id}/query-gaps`，同问题合并计数、租户隔离），前端空召回时可直接查看与清空。问答引用带 `document_id`/`char_range`，召回面板证据行可点「原文」直接打开该文档分块。知识空间可整体导出为 JSON（`GET /datasets/{id}/export`，含文档/分块/术语，已剔除内部向量字段）并导入恢复（`POST .../import`，需写权限、非空需 `overwrite=true`、强制操作者租户），前端工具栏提供导出/导入按钮。外部只读访问用数据集 API Key：`POST /datasets/{id}/api-keys` 生成（明文只显示一次、仅存哈希、可回收），外部调用 `POST /api/knowledge/v1/public/query` 携带 `X-KB-Key`，密钥绑定单一数据集与创建者租户并按 ACL 过滤。查询结果 `metadata.highlights` 给出命中词区间，前端召回证据行高亮显示。问答对（FAQ）用 `GET/PUT/DELETE /datasets/{dataset_id}/qa-pairs` 维护：`PUT` 接受 `{question, answer}` 列表或「问题,答案」CSV/TSV 文本（默认覆盖当前租户、`replace=false` 追加，按问题+答案去重，单库 2000 对），问答对随数据集持久化并和文档块一起进混合召回与引用（`metadata.type="qa"`），无文档也能直接命中答案；前端问答框的「问答」面板可粘贴导入并预览。

AIOPEN 虚拟光标的蓝色星尘拖尾复用 [cursor-effects](https://github.com/tholman/cursor-effects) `1.0.18`（MIT，已锁定版本）的 `fairyDustCursor`，通过合成 `mousemove/mousedown` 驱动；光标本体、方向倾斜与点击动效仍由产品侧 CSS/薄胶水控制，库仅在首次操作时懒加载。
模板库前端采用 [VueFinder](https://github.com/n1crack/vuefinder) `4.8.0`（MIT，已锁定版本）作为文件管理页面；文档预览沿用 `@vue-office/docx` `^1.6.3` 与 `@vue-office/pptx` `^1.0.1`。业务数据、权限与审批仍由宿主承担，组件仅做只读浏览与交互。

前端测试的原生 Canvas 后端复用 [@napi-rs/canvas](https://github.com/Brooooooklyn/canvas) `1.0.13`（MIT，仅开发依赖），满足已锁定 jsdom `31.0.1` 的可选 peer 要求；像素回归使用真实绘制结果，依赖及平台二进制均由锁文件安装，不依赖宿主共享模块。

## AI 浏览器执行（可选）

浏览器自动化复用 [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) `@playwright/mcp==0.0.86`（Apache-2.0）、已锁定的官方 Python MCP SDK `2.3.0`（MIT）与原有 AgentRun / LangGraph。浏览器依赖单独锁在 [browser_mcp_deps](scripts/autonomy/runtime_tools/browser_mcp_deps/package.json)，保持官方发行包的 Playwright `1.66.0-alpha-2026-11-18` 精确依赖及 integrity；这是官方 MCP 包的依赖选择，不把 alpha 浏览器引擎描述成稳定版，也不更改前端 Playwright 版本。

决策继续调用 `planner_llm_gateway` 和已有模型池，使用原任务的预算、模型调用记录、工具契约、逐步审批、租户权限与检查点。产品适配只补任务身份、原执行器进程生命周期和观察回路；纯动作策略与决策/页面证据契约分别位于 `domain/autonomy/browser_policy.py`、`browser_evidence.py`，本地服务信任与执行图入口合同留在原 MCP registry。已调研 [Browser Use](https://github.com/browser-use/browser-use)（MIT）与 [Stagehand](https://github.com/browserbase/stagehand)（MIT）；它们带有另外的 Agent / 模型控制面，本实现直接使用 Playwright MCP 的浏览器能力，保留仓库已存在的执行控制面。AIOPEN 的宿主 DOM 导航与光标仍负责自身页面；Codex CLI 的编码执行、模型路由与超时能力不等同于这个第三方网页回路。

| 已定位的缺口 | 当前代码处理与证据入口 |
|---|---|
| MCP 每调用一次就关闭连接，执行器每步又销毁进程 | 有状态连接与隔离 worker 都按服务器、租户、账号、原 run 复用；普通工具仍用原路径。见 `persistent_sessions.py`、`browser_tool_process.py`。 |
| SDK 2.3 字段变化丢失错误、Schema、分页及结构化结果 | 同时识别新 snake_case 与旧别名；显式结构化 `success=false`、非法成功标记及未完成外层回执不报成功，空的合法 MCP 结果和普通资源正文仍兼容。 |
| 工具发现后只剩必填字段，模型缺少参数类型和枚举 | 原始 JSON Schema 保留至规划、ToolActionSpec 与执行前校验。 |
| 模型预先猜测页面目标，静态计划执行完就宣称完成 | 只接受一个导航/快照起始节点；每步重新观察后仅追加一个节点，仍由原 LangGraph 执行。 |
| 外部动作绕过原权限或复用旧审批 | 工具继续走真实 actor、Mod、allowlist、审批凭据与幂等回执；每个新写动作重新绑定自己的 step。 |
| 页面文字或模型回复被当作成功凭证 | 必须实际等待指定文字，再获取同代会话的新内联快照；拒绝仅出现在工具代码回显中的文字及操作前已存在的静态文字。最终只证明指定页面文字已读回。 |
| 超时、断连、重启后可能重做未知写操作 | 输出持久化 session generation；旧进程/会话丢失、身份或配置变化时明确阻断，未知写结果须核对，不能自动创建新浏览器继续。 |
| 取消可打断 SDK 的受保护清理 | 会话 owner 与 deadline 使用官方 SDK 同体系的 AnyIO 取消域；真实 stdio 回归同时检查进程退出与 transport 关闭，不忽略资源告警。 |
| 模型凭据随 worker 请求进入临时文件 | 请求通过有大小、deadline 与清理边界的匿名 Pipe 传输；模型 scope 与任务输入不写入请求文件。 |
| 无界循环和等待任务占用资源 | 最多 12 次模型决策、32 个步骤，原始 300 秒调度期限不因续跑重置；每步仍受原执行 deadline 约束，终态主动回收，空闲会话默认 300 秒回收。 |
| 目标审核把观察起始节点误判成遗漏后续任务 | 仅对本地配置认可的合法入口补充浏览器控制合同，独立模型仍须审核完整目标、约束和可验证范围；普通计划不获得该合同。后续决策保留原任务内已持久化的用户澄清答案，用户更正优先于原请求，提问文字本身不构成授权。 |
| 原隔离内存上限无法启动现代 V8 | 浏览器单独设置虚拟地址上限并采样整个子进程树 RSS，超限回收；保留原 CPU、文件描述符和进程树清理。 |
| 只有受控 transport 测试，没有真实浏览器验收入口 | CI `Browser Agent real MCP integration` 安装精确 runtime 与 Chromium，经真实隔离执行器验证跨步页面、任务隔离、审批消费、单次提交、读回失败和会话丢失。测试代码存在不等于该提交的 CI 已通过。 |
| Codex 的 CLI、验证或发布失败被文字结果标记完成 | 原同步、派发回退与流式调用保留阶段失败、部分输出和已启动事实；验证失败不提交，失败工作区保留供核对，持久工作区有改动或状态未知时停止。历史消息读取不再重放明确的失败回执；已接收任务不等于执行成功。 |

启用前按 [QUICK_START](docs/QUICK_START.md) 安装现有服务端依赖，并在 `FHD/` 中安装独立浏览器 runtime（Node 20 以上）：

```bash
npm --prefix scripts/autonomy/runtime_tools/browser_mcp_deps ci --ignore-scripts
cd scripts/autonomy/runtime_tools/browser_mcp_deps
npx --no-install playwright install --with-deps chromium
```

从 [mcp_browser.example.json](resources/config/mcp_browser.example.json) 创建本机私有配置，把 `args[0]` 改为安装后 `@playwright/mcp/cli.js` 的绝对路径，设置 `XCAGI_MCP_SERVERS_FILE` 指向该文件，再启动原后端。配置不存在或 `XCAGI_MCP_ENABLED=0` 时不启用。`--isolated` 不复用个人浏览器 profile；本地 `browser: true` 与 `session_mode: persistent` 才会启用观察回路，远端名称或注解不能自行开启。明确写出原任务目标和可读回的页面完成条件，初始规划只含 `mcp__browser.browser_navigate` 或 `browser_snapshot`。

浏览器动作仅开放导航、快照、点击、填写、选择、按键、等待、标签页、返回和截图；最终执行边界也检查相同策略。导航只接受不含凭据的 HTTP(S) 地址，禁止直接执行 JS、安装代码、上传本地文件和指定本地输出路径。非白名单动作、登录、验证码或模型不可用进入原澄清/等待流程；等待不会替用户完成登录。需要人工操作时必须在可见桌面配置同一浏览器实例，默认 headless 模式没有远程接管 UI。

`session_idle_seconds` 默认 300，`max_sessions` 默认 8（每服务最多 32），另有 worker 总量上限。浏览器虚拟地址配置为 `XCAGI_BROWSER_ADDRESS_MB`（默认 1.5 TiB，仅为 V8 地址预留，非物理内存配额）；`XCAGI_BROWSER_MEMORY_MB` 默认 4096 MiB，由生命周期监测器采样 RSS 并回收超限进程树，不等同于内核 cgroup 的无超调硬限制。`XCAGI_TOOL_CPU_SECONDS` 默认 60，长寿 worker 不为每步重置 CPU 额度。300 秒为调度期限，已开始的单次模型/工具调用仍使用原调用超时，期限后不再发起新动作。

剩余缺口与复用路线如下。候选 PR 和上游能力不表示本提交已接入或验收；并行 PR 的共享 MCP/执行器文件须逐项整合，不能整体覆盖持久会话实现。

| 剩余缺口 | 已有资源、候选组件与当前边界 |
|---|---|
| AIOPEN 内部 Agent 到宿主屏幕的可信桥接 | 外部 REST/MCP 与 `cursor_hub → useAiOpenCursor` 已有；内部 ToolSpec 登记而 workflow router 未绑定。[#3434](https://github.com/42433422/XCMAX/pull/3434) 有按 actor / tenant / screen 绑定的短效单动作桥候选，尚未合入；宿主 WebSocket 池不会自动进入工具子进程，多 worker 屏幕归属也须验证。 |
| 按租户约束网络目标与页面隐私 | #3434 的 origin 约束、字段脱敏和截图遮罩可复用，尚未接入本持久 MCP 回路；浏览器进程隔离和动作白名单不代替网络出口边界。 |
| 登录、SSO、验证码与人工接管 | 可复用 [Playwright authenticated state](https://playwright.dev/docs/auth) 和 [noVNC](https://github.com/novnc/noVNC)（主体 MPL-2.0）的可见会话接管；尚未接入账号凭据保险库或远程接管 UI，当前沿用澄清等待，默认 headless 不提供人工登录窗口。 |
| 跨宿主恢复浏览器 | 可评估 Playwright 远程连接及 [Steel Browser](https://github.com/steel-dev/steel-browser)（Apache-2.0）的会话设施；Steel 当前仍标 public beta，仅作候选。已有检查点只能恢复任务控制状态，原浏览器丢失后明确停止，不宣称网页状态已恢复。 |
| 授权上传、下载与持久制品 | 复用 [Playwright download](https://playwright.dev/docs/downloads)、原文件归属/哈希/下载接口及 #3434 的制品桥候选；当前白名单未开放本地文件操作，完整上传下载场景仍需真实验收。 |
| Canvas 与桌面视觉定位 | [#3430](https://github.com/42433422/XCMAX/pull/3430) 有 PyAutoGUI 桌面候选；尚未接入本回路，像素状态不证明后台业务完成。 |
| 超长页面、混合工具和多个浏览器 | 继续复用原 LangGraph 与 MCP 定位快照能力；当前每次观察最多 24,000 字符，入口仅接受单一浏览器服务的连续任务，不宣称整页覆盖，混合或多浏览器初始计划会被拒绝。 |
| 业务数据库、付款或外发结果核验 | 须复用对应业务服务的独立查询和实际交易回执；本回路终态仅证明指定页面文本已读回。 |
| 生产模型、客户站点和各平台交付 | 复用原模型池、客户测试环境与原发布流水线逐项验收；Linux fixture 不代替真实模型决策质量、客户 SSO、Windows/macOS 安装包或同 SHA 部署证据。 |
| Codex 的完整产品验收与任务凭据隔离 | 继续复用现有 CLI、工作区和 CI；本次验证了失败状态与禁止重放，默认验证仍是已配置命令或 Python 编译，未调用真实 Codex 账户完成产品验收。反馈修复链的 `waiting_credential_isolation` 仍须独立解决，不因普通 CLI 回执修复而解除。 |
| CI 宿主后续升级 | 浏览器专项暂固定为保持 Chromium 沙箱的 `ubuntu-22.04`，避免 24.04 缓存内 Chromium 的 user-namespace/AppArmor 不兼容；该镜像已进入弃用期，须在官方 [2027-04-17 退休](https://github.com/actions/runner-images/issues/14254)前迁移到验证过沙箱兼容的新宿主。 |

<a id="version-policy"></a>

## 版本与发布约定

产品版本与工具链映射以 [VERSION.md](VERSION.md) 为准；仓根 [GitHub workflows](../.github/workflows/) 是执行入口，生成的子树副本不独立调度。发布流程见 [CI_SSOT](../docs/CI_SSOT.md)。

产品修复通过审查和必需检查后合入 `main`。交付包须来自明确的主线 SHA；包内身份、运行后台与业务验收记录必须一致。分支测试、demo 和历史包不证明新候选通过。

| 验收 | 入口 |
|---|---|
| 同版双端发布原则 | [desktop_platform_parity_ssot](docs/desktop_platform_parity_ssot.md) |
| Windows 包、签名与实机门禁 | [WINDOWS_RELEASE_SSOT](docs/WINDOWS_RELEASE_SSOT.md) |
| Mac 双架构、签名公证与实机门禁 | [MACOS_RELEASE_SSOT](docs/MACOS_RELEASE_SSOT.md) |
| 客服工单与客户确认 | [CUSTOMER_TICKET_BUS_SSOT](docs/architecture/CUSTOMER_TICKET_BUS_SSOT.md) |

正式下载指针和 stable 更新通道只在既有发布门禁及真实客户闭环通过后推进。历史变更保留在 CHANGELOG，已外置文档的恢复位置见 [ARCHIVE_POINTER](../ARCHIVE_POINTER.md)。

## 🧠 Neuro-DDD 与代码落点（必读）

分层和运行入口见 [ARCHITECTURE](docs/ARCHITECTURE.md)、[TECH_STACK](docs/TECH_STACK.md) 与 [XCAGI 子树说明](XCAGI/README.md)。应用用例在 `app/application/`，业务规则在 `app/domain/`，数据库及外部能力在 `app/infrastructure/`；HTTP 路由经应用层调用。

桌面壳在 `desktop/`，共享前端在 `frontend/`。Mod 的编辑源、镜像及发布约束见作者指南；不要维护客户分叉宿主或重复编辑镜像。真实业务数据、密钥与大体积私有资源不提交源码。

## 参与开发

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX/FHD
```

依赖安装、启动和最小验证按快速开始与 [贡献指南](.github/CONTRIBUTING.md) 执行。修改前检查工作区及历史主线提交，保留其他人的改动；本地定向测试不能替代发布级实机验收。

## 对话上下文与技能的来源

记忆与检索优先复用以下固定组件。个人记忆表单参考 [Hermes Agent v0.23.2 的写入策略](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/website/docs/user-guide/features/memory.md#controlling-memory-writes)（MIT），用户主动保存时复用 MemoryV2 的候选和确认接口。记忆写入遵循现有权限和来源校验。

| 能力 | 来源与版本 | 产品适配 |
|---|---|---|
| 长期记忆抽取、向量存储 | [Mem0](https://github.com/mem0ai/mem0) `mem0ai==2.2.1`，Apache-2.0 | 复用官方 additive extraction 和 SDK。本人明确陈述的个人记忆从已授权对话自动生效，企业及跨空间候选保留审核。写入体验参考 [Hermes Agent v0.23.2](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/website/docs/user-guide/features/memory.md#controlling-memory-writes)（MIT）。召回按来源 ID 和版本回查 MemoryV2。 |
| 结构化候选、历史预算 | [LangChain Core](https://github.com/langchain-ai/langchain) `1.5.3`，MIT | 复用 PydanticOutputParser 与 trim_messages；移除规则自动确认为事实和不完整摘录摘要，完整消息按预算保留并报告实际丢弃范围。 |
| 关键词召回 | [BM25S](https://github.com/xhluca/bm25s) `0.3.16`，MIT | FHD 与 MODstore 共用成熟 BM25 计算；完整授权语料的关键词候选独立于 dense 候选，随后 RRF 融合。 |
| 多进程历史写入 | [filelock](https://github.com/tox-dev/py-filelock) `4.2.4`，MIT | 共享本地目录中的会话和轮次文件锁，保护跨进程读改写及执行归属；不提供跨节点锁或业务 ExactlyOnce。 |

用户业务记忆按 tenant/user/Mod 隔离，企业记忆按 tenant/Mod 隔离；跨企业复用仅接受显式确认的本人 `global_preference`。旧裸账号、缺少来源版本的索引和原始聊天仍保留供审计，但不自动转为可信事实。员工任务历史独立保留真实运行来源和成功/失败状态，不标记为已核实业务事实。撤销/更正先持久化权威状态，投影故障返回 `retry_required`，过期副本立即失去召回资格；后续召回按退避重放已生效记录和撤销记录。未配置模型时，只处理现有回退能识别的明确陈述；模型明确返回空结果时不使用规则补写。

`EmbeddingService` 为 mode/model/endpoint/revision 生成不含密钥的指纹。数据集指纹变化即重建，即使维度相同；Mem0 使用新指纹集合并从当前已确认记录重放。供应方更新同名模型权重时设置新的 `FHD_EMBEDDING_MODEL_REVISION` 并重启，该值只标识索引版本。自定义 embedder 应暴露 `embedding_fingerprint`，否则只能检查维度。hash 模式仍报告非语义；小语料回归和关系查询测试不代表真实模型、生产 pgvector 或大规模延迟验收。

模型窗口登记于 `config/model_context_windows.json`，来源为 [LiteLLM 固定目录](https://github.com/BerriAI/litellm/blob/736b05716593347fa51b92afa9526a2397af312c/model_prices_and_context_window.json)（MIT）和 [小米 MiMo-V2.6-Flash 文档](https://mimo.mi.com/models/en-US/mimo-v2.6-flash)。按本轮实际路由查找精确模型名，再匹配去掉服务商前缀的名称。未知模型使用保守默认值；历史压缩前预留输出和工具 token。

仓库技能以 [OpenHands Software Agent SDK 的 `SKILL.md` 解析格式](https://github.com/OpenHands/software-agent-sdk/blob/ae4fd87f9b86a9362943d29771192816877646a9/openhands-sdk/openhands/sdk/skills/skill.py)（参考提交 `ae4fd87f9b86a9362943d29771192816877646a9`，[MIT](https://github.com/OpenHands/software-agent-sdk/blob/ae4fd87f9b86a9362943d29771192816877646a9/LICENSE)）为协议参考；使用锁定的 [PyYAML 6.0.3](https://github.com/yaml/pyyaml/tree/6.0.3)（MIT）解析元数据。宿主仅适配 `name`、`description`、`triggers` 和 Markdown 正文，不引入另一套 Agent 运行时；仅命中的技能参与本轮规划，受服务端开关、路径和输入总量限制，不能用客户端 `active_skills` 冒充技能规则。此适配不宣称支持上游完整技能发现、资源调用或插件协议。

## 许可证与安全

多轮澄清复用 [LangChain Core 1.5.3](https://github.com/langchain-ai/langchain/tree/01d8481ae3d457ec3751cbb0331ea3a4b720fa90/libs/core)（MIT）：`trim_messages` 保留有序会话窗口，`PydanticOutputParser` 解析字段与候选对象回答；暂停与续跑沿用已吸收的 LangGraph 1.2.10。完整业务计划也复用其 `convert_to_openai_tool` 与 `PydanticOutputParser`，由 [Pydantic](https://github.com/pydantic/pydantic)（MIT，服务端锁定 2.13.5）生成同一份原生调用/JSON Schema；一次提交含全部 `depends_on` 的图，替代逐个原生动作手写适配。嵌套必填字段复用 [python-jsonschema](https://github.com/python-jsonschema/jsonschema) 4.26.0 与 [referencing](https://github.com/python-jsonschema/referencing) 0.37.0（均为 MIT），规划与澄清续跑共用工具契约和本地 Schema 引用解析；服务端 tarball 复用 `ops/deploy/requirements-langgraph-runtime.txt` 清单，通过已有运行时 bootstrap 固定安装两者，`FHD_SKIP_PIP=1` 时仍执行。已停用的直接导入工具由同一服务端规则在规划、执行与恢复前拒绝，导入沿用 ELT 预演与执行。产品侧仅绑定原话、节点、权限和会话；独立模型调用核对目标覆盖、否定与顺序，失败最多重新规划一次，仍失败则不执行。该语义核对不是正确性证明，真实模型准确率由评测报告另行记录。版本固定在依赖清单，不另建对话或执行引擎。

会话连续性复用 [LangChain 1.3.14 SummarizationMiddleware](https://github.com/langchain-ai/langchain/tree/01d8481ae3d457ec3751cbb0331ea3a4b720fa90/libs/langchain_v1)（MIT）及上述 Core 1.5.3，压缩入口同时覆盖普通/流式规划，预留输出和工具 schema，保存完整原文的已覆盖游标；摘要失败不伪造覆盖。跨进程文件互斥使用 [filelock 4.2.4](https://github.com/tox-dev/filelock/tree/4.2.4)（MIT，统一跨进程锁依赖版本）。SQLAlchemy 事务管理会话 revision、删除标记和整轮回执，JSON 只作为可重建投影；历史通过授权游标分页读取，保存失败仅重试原回执。

任务恢复使用 [LangGraph 原生检查点](https://docs.langchain.com/oss/python/langgraph/checkpointers)（核心 1.2.10、checkpoint 4.3.0、SQLite 3.1.2、Postgres 3.1.1+xcagi.1，MIT，源码与许可见 `packages/xcagi_langgraph_*`）。安全步骤在原 run 内恢复。独立规划澄清复用 AgentRun、WorkflowPlanStore 和执行租约保存原目标、问题与答复，只有尚未执行业务的单一提问图可以重新规划，并再次经过目标、风险与审批校验；参数澄清和已有业务图继续在原图恢复。知识答复沿用 DatasetRag 的答案、证据和查询范围。聊天批量导入按 ELT 文件回执核对已写入项，将剩余原附件绑定到同一任务的下一次审批执行，继续用原有 StateGraph 调度。未知写结果保留待核对。

对话撤回参考 [Temporal Saga v1.40.0](https://github.com/temporalio/sdk-java/blob/v1.40.0/temporal-sdk/src/main/java/io/temporal/workflow/Saga.java)（[Apache-2.0](https://github.com/temporalio/sdk-java/blob/v1.40.0/LICENSE)），复用现有 ELT 行级回滚和回执。服务端先核对写入归属及补偿范围，按倒序撤销，收齐回执后再按会话版本截断历史。

企业专属客服复用 [APScheduler 3.11.3](https://github.com/agronholm/apscheduler/tree/3.11.3)（MIT，版本见 `uv.lock`）触发 IM 待处理消息恢复，沿用现有数据库记录和 MODstore 账号授权。产品知识复用 BM25S 0.3.16（MIT）与现有引用组件，内置公开指南。扩展资料使用专用只读密钥 `XCAGI_ENTERPRISE_CS_KB_KEY` 及公开元数据过滤。

主动提醒的外发适配复用 [Apprise 1.13.1](https://github.com/caronc/apprise/tree/v1.13.1)（BSD-2-Clause，确切版本见 `uv.lock` 的可选 `proactive-push` 依赖），记录与渠道结果复用 SQLite 事务及既有跨进程锁。当前交付仅为服务和 `scripts/ops/publish_proactive_event.py`：必须指定租户；本地事件记录不等于站内通知已送达，业务事件生产、站内 UI 与真实渠道验收尚未完成。已成功渠道不重复投递，失败渠道可重试；进程中断留下的未知投递结果需人工核对，不能宣称外发恰好一次。

[Apache-2.0](LICENSE)；商业约定见 [COMMERCIAL_LICENSE](COMMERCIAL_LICENSE.md) 与 [LICENSING](docs/guides/LICENSING.md)。安全反馈和配置规则见 [SECURITY](SECURITY.md)。
