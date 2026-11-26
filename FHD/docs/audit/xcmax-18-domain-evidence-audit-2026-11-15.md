# XCMAX 18 域审计记录（2026-11-15 · rev.2）

> 记录性质：**证据现状审计，不授予正式分数**。依据 `FHD/config/audit_benchmark_ssot.json`
> （standard `1.0.0` / scoring `external-anchors-v1`）逐域核查 B1–B3、C1–C3 共 108 条验收条目。
> 前序记录 `outputs/audit/xcmax-18-domain-evidence-audit-20261113.md`（本地生成目录，未入库）
> 保持原文，不修改、不复用其结论；本轮只记录今日复核结果。

## 一、审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| source_sha | `3bcc0b12f3`（分支 `feat/memory-v2`，非 `origin/main`） |
| main_sha | 未以 `origin/main` 构建，未记录 |
| artifact_sha256 / installed_git_sha | 未采集（无本轮构建产物） |
| reference_versions_editions_regions | Dialogflow CX、Lex V2、watsonx Orchestrate、Rasa 3.6：未锁定版本/区域 |
| dataset_hash | 仅意图路由有 `dataset_sha256`；其余域无冻结任务集 |
| task_protocol | 未冻结（无统一任务集/并发/数据量/故障场景） |
| predeclared_metrics_and_tolerances | 未登记 |
| model_and_budget | 未登记统一模型与预算 |
| environment | 本地 macOS + Python 3.12.13（`.venv`），非目标部署 |
| evidence_ids | 见第三节逐域 |
| observed_results | 见第三节 |
| unknowns | 见第五节 |
| axis_levels | 不判分（必选证据未知） |
| domain_status | 18 域全部 `UNRATED` |
| score | `null`（不出 18 域总分） |
| auditor | AI 审计（代码与指标复核），非第三方 |
| observed_at | 2026-11-15 |

## 二、总体结论

按协议：60 分需「至少 E2 且核心用户任务达到 E3」；90 分还需商业参考同协议实测与 E4 观察窗口。
本轮证据等级为 **E2（部分域仅 E1/E0）**，E3 / E4 均未采集，**18 域全部 `UNRATED`，正式总分 `null`**。
任一域 UNRATED 时不出 18 域总分；因此本记录只给域级状态与阻塞项。

## 三、逐域判定

状态含义：`E2`=有单测/回归；`E1`=仅源码或静态证据；`E0`=仅目录/资料；`—`=未采集。
「必选短板」指阻断 60 分的首要缺口。

> **rev.3 更新（2026-11-24）**：下表是 rev.2 的静态基线。rev.3 已在隔离真实栈上完成 01/02/06/07/15 五域
> E3 实测，并把其余域逐一记录为带具体阻塞原因的 UNRATED。**最新域名状态以第九节为准。**

| # | 域 | 已具备证据 | 必选短板 | 状态 |
|---|---|---|---|---|
| 01 | 依赖注入与分层 | E2：组合根 `FHD/app/di/`、边界校验脚本、单测 | 无替换实现/故障 E3；C1 未测 | UNRATED |
| 02 | ERP 订单与资金闭环 | E2：订单→出库→开票收款→冲销回归；证据文件最多 | 多币种/期间对账无实现证据；C3 审批身份存在反证 | UNRATED |
| 03 | Agent 编排与审批 | E2：跨实例恢复、逐次鉴权、审批链；编排器回归 34 例今日通过 | 真实模型多步任务与超时强制中断未验 | UNRATED |
| 04 | ETL 与业务文件处理 | E2：预览/回滚/租户隔离；15 份证据 | **登记范围路径不存在**；C1 无全链路 lineage | UNRATED |
| 05 | AI 意图与工具路由 | E2：留出集 142 例、混淆矩阵、65.49%；L2 事实化 13 例与指标 5 例通过 | 每域仅 10–11 例（<30）；任务基准 22×1；B2 已观察失败 | UNRATED（上限 59） |
| 06 | NeuroBus 事件内核 | E2：DLQ、去重、队列满降级 | 无网络分区/恢复 E3；重放已知缺陷 | UNRATED |
| 07 | Mod SDK 与行业模块 | E2：会话级授权隔离、签名安装回执 | 客户安装/升级 E3 与跨租户负向未验 | UNRATED |
| 08 | 桌面壳与更新恢复 | E1/E2：回滚、凭据、IPC 边界；CI 冒烟 | 目标设备批量更新与数据保留未验收 | UNRATED |
| 09 | FHD 前端与用户任务 | E2：16 个 e2e spec、618 个单测文件 | C3 工作台只追踪健康，不追踪业务结果 | UNRATED |
| 10 | 商城前端与工作流 UI | E2：目录/搜索/授权页面 | C1 无后台订单接口；C2 无组织管理实现 | UNRATED |
| 11 | 商城交易与交付后端 | E2：退款/Webhook 幂等测试 | 无压测/故障注入；交付一致性未验 | UNRATED |
| 12 | 自治与维护执行 | E2：子进程进程组回收、超时、截断 | C3 无队列容量控制；跨节点执行未验 | UNRATED |
| 13 | Java 支付服务 | E1：服务代码存在；`verifyNotify` 有真实实现 | **集成测试仍把 `verifyNotify` mock 为 true（第 100 行）**；退款不调用渠道；单一 SDK 版本 | UNRATED |
| 14 | Flutter 移动端 | E1/E2：工程存在；`mobile-flutter-poc/.flutter-version` 已锁 `3.44.7`，Flutter CI 使用该文件 | **Android 发布链仍 `channel: stable`**；无真机、跨设备与冲突测试；仅 debug 构建 | UNRATED |
| 15 | Retort 共享引擎 | E2：五标志闭环、吸收状态测试 | 执行证据未绑定产物哈希；C 级缺长期运行证据 | UNRATED |
| 16 | Vibe 编码与沙箱 | E1/E2：路径穿越拒绝、网络隔离+cap-drop | 无留出任务评测；无检查点/恢复 | UNRATED |
| 17 | 客来来独立子系统 | E0：子模块未初始化（0 文件） | 无法取证；仅旁证测试 16 例 | UNRATED |
| 18 | CI、发布与治理 | E2：根仓 86 + FHD 51 个 workflow、漂移门禁阻塞、负向门禁 | 产物身份/安装升级回退未闭环；C3 无自动回滚 | UNRATED |

## 四、本轮复核的增量事实

1. **统一指标层已落地**：`xcagi_memory_recall_*`、`xcagi_plan_generation_*`、`xcagi_tool_call_*`、
   `xcagi_chat_ttft_ms` 已有埋点，`XCAGI_METRICS=0` 可停用；但**尚无采集端数据**，不构成 E3/E4。
2. **L2 记忆事实化已落地**：规则抽取、`ADD/NOOP/SUPERSEDE`、失效过滤、删除治理与 13 例单测；
   仍属 E2，且无跨会话 recall@5 留出集。
3. **意图路由文档已纠偏**：原引用的 86.6% 无落盘依据，现统一为仓库可复现的 65.49%；
   该域 B1 抽样仍低于协议下限，B2 仍有重复澄清与否定未闭环失败。
4. **两个 scope 失真**：ETL 指向不存在的 `FHD/app/application/etl/`；
   意图路由指向 3 行转发文件 `chat_business_safety_core.py`。按协议需先修正范围再评级。
5. **本地 E2 已可复现**：审计机改用仓库 `.venv`（Python 3.12.13），本轮 L2/指标/编排/流式回归
   共 145 例通过；上一版报告的 Python 3.9 阻塞已解除。
6. **Flutter 版本部分锁定**：`mobile-flutter-poc/.flutter-version` 为 `3.44.7`，
   `ci-mobile-flutter.yml` 已改用该文件；但 Android 发布链仍用 `channel: stable`，
   14-B1 只能算部分修复，仍不满足「固定版本可复现构建」。
7. **E4 仍断档**：SLO 采集最新仍为 `slo-measured-20260903.json`；
   部署事件已更新到 2026-11-14，但缺少 30 天连续窗口与客户验收。

## 五、未知项（不得填 0 或通过）

- 三个商业参考与 Rasa 3.6 的同协议实测值：全部未运行。
- E3：目标部署/真机上的完整任务与故障恢复。
- E4：≥30 自然日运行窗口与客户验收。
- 所有域的统一任务集、并发量、数据量、模型与预算：未冻结。
- 第 17 域源码：子模块未初始化，无法取证。

## 六、下一轮可启动的最小审计

| 顺序 | 域 | 启动条件 |
|---|---|---|
| 1 | 05 意图路由 | 每域 ≥30 例 × 3 次并落盘；修复 B2 重复澄清/否定未闭环 |
| 2 | 02 ERP | 冻结「订单→收款」任务链，跑 E3 + 故障恢复 |
| 3 | 03 Agent 编排 | 真实模型多步任务 + 超时/取消恢复 |
| 4 | 18 CI/发布 | 产物身份、安装升级回退与 SHA 绑定 |
| 5 | 13 支付 / 14 移动端 | 先补 B1–B3 的 E2 基线，脱离 UNRATED |

## 七、口径声明

本记录是内部证据视图，不构成 `external-anchors-v1` 正式审计分。历史值 73.3 / 77.1
（internal-review-v1）与 54.0（语义兜底前）均不换算、不沿用、不混算。
任何「已确认越权、跨租户泄露、重复扣款或不可恢复数据破坏」直接不合格，不能被其他域高分抵消。

## 八、rev.2 变更记录（同日）

- 更新 `source_sha` 为 `3bcc0b12f3`，记录 Python 3.12 审计环境与 145 例 E2 回归结果。
- 14 域 B1 由「未锁版本」改为「CI 已锁 3.44.7、发布链未锁」的部分修复。
- 18 域 workflow 数改为根仓 86 + FHD 51，并记录部署事件更新到 2026-11-14。
- 13 域补充 mock 行号（`AlipayNotifyIntegrationTest.java:100`）。
- 其余域结论不变，正式状态仍为 18 域 `UNRATED`、总分 `null`。

---

## 九、rev.3（2026-11-24）真实运行 E3 实测

本轮把审计从「读代码/跑单测」推进到**在真实运行的产品上执行完整任务 + 注入故障 + 恢复**。
采集器：`/Users/Shared/XCMAX/.e3run/harness.py`；逐域结构化证据：
`FHD/docs/evidence/audit-benchmark/e3-20261124/{01..18}.json`，全量请求轨迹 `harness-steps.json`。

### 9.1 运行环境（可复核）

| 项 | 值 |
|---|---|
| 形态 | FHD 服务真实进程，`XCAGI_DESKTOP_MODE=1`，端口 5199 |
| 数据 | 隔离目录 `/Users/Shared/XCMAX/.e3run/data`，SQLite 主库 `data/data/xcagi.db` |
| 账号 | 本机 `e3runner`（user id=2，tenant_id=1）；桌面模式禁止 admin 会话 |
| 就绪判据 | 仅 `/health/liveness` 不足：必须 `GET /api/inventory/warehouses` 返回 200（延迟路由已挂载） |
| 证据原则 | 不信写入信封，一律独立读回校验；金钱/数量按精确值比对 |
| 代理 | localhost 请求显式绕过 `http_proxy` |

### 9.2 18 域当前状态

| # | 域 | 等级 | 断言 | 证据 |
|---|---|---|---|---|
| 01 | 依赖注入与分层 | **E3** | 7/7 | `01.json` |
| 02 | ERP 订单与资金闭环 | **E3** | 17/17 | `02.json` |
| 03 | Agent 编排与审批 | UNRATED | — | `03.json`（无模型凭证） |
| 04 | ETL 与业务文件处理 | UNRATED | 8/12 | `04.json`（预览需真实模型会话） |
| 05 | AI 意图与工具路由 | UNRATED | — | `05.json`（无模型 + 样本量 0/100） |
| 06 | NeuroBus 事件内核 | **E3** | 5/5 | `06.json` |
| 07 | Mod SDK 与行业模块 | **E3** | 9/9 | `07.json` |
| 08 | 桌面壳与更新恢复 | UNRATED | — | `08.json`（无 GUI/签名安装包） |
| 09 | FHD 前端与用户任务 | UNRATED | — | `09.json`（前端无 dist 构建） |
| 10 | 商城前端与工作流 UI | UNRATED | — | `10.json`（无市场凭证/未构建） |
| 11 | 商城交易与交付后端 | UNRATED | — | `11.json`（服务未部署） |
| 12 | 自治与维护执行 | UNRATED | 6/6 | `12.json`（无 GitHub/CVM 执行器，动作未真实执行） |
| 13 | Java 支付服务 | UNRATED | — | `13.json`（无支付宝沙箱凭证） |
| 14 | Flutter 移动端 | UNRATED | — | `14.json`（无 flutter/adb/真机） |
| 15 | Retort 共享引擎 | **E3** | 7/7 | `15.json` |
| 16 | Vibe 编码与沙箱 | UNRATED | — | `16.json`（仅 MockLLM，不构成 E3） |
| 17 | 客来来独立子系统 | UNRATED | — | `17.json`（0 文件） |
| 18 | CI、发布与治理 | UNRATED | — | `18.json`（未跑构建/回退） |

**结论：5 域 E3（01/02/06/07/15），13 域 UNRATED；因存在 UNRATED，不出 18 域正式总分。**

### 9.3 E3 域的任务协议摘要

- **01 组合根/分层**：真实启动 → 就绪探测 → `SIGKILL` 强杀（确认不可用）→ 重启 → 数据与服务恢复；7 条断言全过。
- **02 ERP 订单与资金闭环**：真实建商品 → 建仓 → 入库/出库 → 汇总核对 → 订单创建 → 凭证增删改查 → 看板对账 →
  幂等重放与租户负向；17 条断言全过，金额按精确值核对。
- **06 NeuroBus 事件内核**：真实发布事件 → `published` 计数增长 → 负向缺 `event_type` 被拒 → `SIGKILL` 重启 → 统计仍可读；5/5。
- **07 Mod SDK 与行业模块**：`build_mod.py --sign` 真实打包 → 上传安装 → 路由立即生效（版本号核对）→
  `SIGKILL` 重启后仍安装且路由可用 → 内容篡改包被签名校验拒绝 → 安装者本人真实卸载并确认移除；9/9。
- **15 Retort 共享引擎**：真实 CLI `quality-gates` 跑真实 `ruff` + `pytest` 子进程（4 门禁）→ 注入未使用导入、
  失败断言、语法损坏三类真实缺陷，均被判失败且 CLI 不崩溃 → 修复后恢复全绿；7/7，报告落盘可解析。

### 9.4 本轮在真实运行中发现的产品问题

1. **finance 路由租户上下文缺失（已修）**：`FHD/app/fastapi_routes/finance.py` 手工构造的 `runtime_context`
   缺 `tenant_id`，导致所有财务写入被租户作用域工具拒绝。修复为用
   `authenticated_runtime_context` + `require_agent_principal` 派生上下文，并剥离请求体中的伪造
   `tenant_id/user_id`。修复后 02 域 17/17 通过。
2. **Mod 路由注册器是硬约束**：宿主只认模块级 `register_fastapi_routes(app, mod_id)`；
   仅声明 `router = APIRouter()` 会得到日志「Mod has no HTTP route registrar, skip」，
   `/api/mod/{id}/*` 返回 503 `mod_unavailable`。
3. **本机上传安装的扩展无法被安装者卸载（已修）**：`POST /api/mod-store/upload` 写入的安装收据
   `owner_scope` 为空，而卸载端点要求「admin 或 owner 绑定」，桌面模式又显式拒绝 admin 账号
   （`is_admin_account_kind`），普通账号因此能安装却无法卸载自己安装的签名扩展（403「扩展归属或卸载权限
   未通过校验」）。修复：上传安装时绑定当前工作空间 owner（`resolve_workspace_owner_id`），
   收据与卸载侧的归属判定口径一致。修复后 07 域 9/9 通过，卸载返回
   `MOD <id> 卸载成功` 且安装列表已移除。
4. **幂等重放会吞掉同 id 的 DELETE**：同一 `transaction_id` 的删除请求命中幂等作用域而不真正执行；
   硬删除验证必须使用新建凭证。
5. **`finance.*` 无独立核验器**：写入提交成功但信封返回 `outcome:"unknown"`；
   只能以独立读回判定，不能信 `success` 字段。
6. **同 id 同版本不同字节会被拒装**（`Mod version already exists with different package bytes`），
   升级验证必须递增版本号。

### 9.5 UNRATED 的阻塞类型

| 类型 | 域 | 具体缺口 |
|---|---|---|
| 无真实模型会话 | 03, 05, 16 | `require_model_session` 失败（实测 `model_configuration_error`）；05 还需 ≥100 留出任务 ×3 |
| 缺外部执行器/凭证 | 12, 13, 10, 11 | GitHub/CVM 执行器缺；支付宝沙箱密钥为空；市场账号与回调不可用 |
| 缺目标平台/产物 | 08, 09, 14, 18 | 无 GUI 与签名安装包；前端未构建；无 flutter/adb/真机；未跑构建与回退 |
| 源码缺失 | 17 | `market/src/domain/客来来` 文件数 0 |
| 证据未闭环 | 04 | 分类确认缺区域参数；预览依赖真实模型 |

### 9.6 口径声明

本节只把「真实进程/真实 CLI 跑通完整任务并完成故障恢复」记作 E3；单测、绿 CI、模拟 LLM、静态代码
一律不计入 E3。未达 E3 的域保持 `UNRATED` 且 `score: null`，不以 0 分或「通过」填空。
