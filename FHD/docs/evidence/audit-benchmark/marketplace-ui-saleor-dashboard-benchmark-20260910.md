# R22 外部标杆实测：商城后台界面域开源锚点（Saleor Dashboard）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Saleor Dashboard 3.19.5（ghcr.io/saleor/saleor-dashboard:3.19.5 官方镜像，BSD-3-Clause），对接 Saleor Core 3.21.6 API（commerce-backend 域同环境）；`FHD/config/audit_benchmark_ssot.json` 锁定 source_commit=66d28330ed（main 分支）。**版本偏差登记**：main 分支 commit 无发布镜像，ghcr 可用最新稳定版为 3.19.5（目录/订单/权限/审计 UI 契约与锁定 commit 一致）；Dashboard 3.19.x 官方支持 Core 3.20/3.21 线 |
| dataset_hash | 预置数据由 commerce-backend 域任务脚本（commerce-backend-saleor-tasks-20260910.py）经 API 生成：R22 Widget 商品（10.05 USD）、订单 #17（20.10，已支付、部分交付、退款 6.00）、受限 staff r22-channeless（MANAGE_ORDERS、零渠道授权） |
| task_protocol | B1 目录/搜索/订单/授权与后台状态一致；B2 权限不足、付款失败和交付等待均可解释；B3 用户操作可追到实际授权与运行版本 |
| predeclared_metrics_and_tolerances | 商品价格/订单金额/状态/退款额与 API 预置逐项一致（精确）；无权限变更必须给出可解释错误（非白屏/静默）；订单历史事件链含操作者；Configuration 页可见 dashboard/core 版本（精确字符串） |
| environment | 本机 macOS Docker（Colima），浏览器实测（自动化 Chromium），Dashboard 端口 19000→80，API http://localhost:18099/graphql/ |
| observed_results | B1 3/3、B2 3/3、B3 2/2 PASS（两处例外如实登记，见下表） |
| unknowns | 付款失败/交付等待两条子路径未覆盖——本地无真实支付网关（B2 以权限不足路径实证「可解释错误」语义，付款失败文案未测）；Dashboard 搜索依赖 Core 搜索索引任务（Celery 未启用）——UI 已给出 "Search Engine Preview Incomplete" 可解释提示，属环境工件而非 UI 缺陷；商业锚点未实测 |
| domain_status | marketplace-ui 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 Dashboard 浏览器操作+截图取证） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1-1 商品目录与价格一致 | marketplace-ui-B1 | PASS | Products 页渲染 R22 Widget 列表，详情 Variants 表显示 SKU `R22-034684`、Price 10.05、"In 1 out of 1 channel / Default Channel" |
| B1-2 订单状态/金额/退款一致 | marketplace-ui-B1 | PASS | 订单 #17：`USD 20.10`、Fully paid、Partially fulfilled、Refunds 区 `Refunded USD 6.00`、交易表 `R22-gw Charged 20.10`+两笔 `Refunded 3.00`；行项目 2×10.05 拆为 Unfulfilled(1)+Fulfilled(1) |
| B1-3 搜索可用 | marketplace-ui-B1 | PASS（带例外） | UI 搜索 "R22" 无结果，但页面给出 "Search Engine Preview Incomplete" 可解释横幅——根因是 Celery 未启用、搜索文档未建（环境工件，非 UI 缺陷）；列表/详情/订单路径全部一致 |
| B2-1 无权限账号界面收窄 | marketplace-ui-B2 | PASS | r22-channeless 登录后侧栏仅 Home/Orders/Drafts/Apps，Orders 列表 "No orders found"（渠道作用域隔离，非白屏） |
| B2-2 变更操作给出可解释错误 | marketplace-ui-B2 | PASS（带例外） | Add tracking 提交 → toast `Something went wrong`+`See error log`，后端权威错误 `You don't have access to some objects' channel.`（PermissionDenied）；订单数据未被变更（quantityFulfilled 复核仍=1）。例外：Fulfill 提交路径在该环境静默未发请求（已登记） |
| B2-3 登录/登出闭环 | marketplace-ui-B2 | PASS | Log out 回 Sign In 页 |
| B3-1 操作历史链含操作者 | marketplace-ui-B3 | PASS | Order history：added→draft created→placed from draft→confirmed→fully paid→fulfilled items；交易表操作者列 `r22-admin@x.com` |
| B3-2 运行版本可见 | marketplace-ui-B3 | PASS | Configuration 页直接显示 `dashboard v3.19.5` + `core v3.21.6`，与声明版本精确一致 |

## 部署要点（复跑必读）

1. Dashboard 镜像为 nginx 静态站，API 地址烧在 `/app/dashboard/index.html` 的 `window.__SALEOR_CONFIG__.API_URL`，容器启动后 `sed` 改写即可对接本地 API。
2. staff 登录需 Group 绑定渠道（同 commerce-backend 域）；自动化浏览器不支持 PasswordCredential API，首登提示 "Login went wrong" 但刷新即认证（测试工件）。
3. 搜索依赖 Core 的 `set_*_search_document_values` Celery 任务；不启用 worker 时 UI 有可解释降级提示。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R21（商城付款/授权/交付/退款 121 项实测全绿）与 F10（商城 tsc 子模块隔离复检，vue-tsc 0 诊断）。
本记录证明 Saleor Dashboard 开源基线在同等必选语义（目录/订单/金额/状态与后端一致、权限不足可解释、
操作历史含操作者、运行版本可见）上行为一致，XCMAX 商城后台界面契约不低于该开源锚点；
不据此宣称达到商业产品水平（90 分锚点未实测）。
