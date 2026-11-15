# XCMAX 18 域审计记录（2026-11-15）

> 记录性质：**证据现状审计，不授予正式分数**。依据 `FHD/config/audit_benchmark_ssot.json`
> （standard `1.0.0` / scoring `external-anchors-v1`）逐域核查 B1–B3、C1–C3 共 108 条验收条目。
> 前序记录 `outputs/audit/xcmax-18-domain-evidence-audit-20261113.md`（本地生成目录，未入库）
> 保持原文，不修改、不复用其结论；本轮只记录今日复核结果。

## 一、审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| source_sha | `7b6c0c558b`（分支 `feat/memory-v2`，非 `origin/main`） |
| main_sha | 未以 `origin/main` 构建，未记录 |
| artifact_sha256 / installed_git_sha | 未采集（无本轮构建产物） |
| reference_versions_editions_regions | Dialogflow CX、Lex V2、watsonx Orchestrate、Rasa 3.6：未锁定版本/区域 |
| dataset_hash | 仅意图路由有 `dataset_sha256`；其余域无冻结任务集 |
| task_protocol | 未冻结（无统一任务集/并发/数据量/故障场景） |
| predeclared_metrics_and_tolerances | 未登记 |
| model_and_budget | 未登记统一模型与预算 |
| environment | 本地 macOS + 仓库测试环境，非目标部署 |
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

| # | 域 | 已具备证据 | 必选短板 | 状态 |
|---|---|---|---|---|
| 01 | 依赖注入与分层 | E2：组合根 `FHD/app/di/`、边界校验脚本、单测 | 无替换实现/故障 E3；C1 未测 | UNRATED |
| 02 | ERP 订单与资金闭环 | E2：订单→出库→开票收款→冲销回归；证据文件最多 | 多币种/期间对账无实现证据；C3 审批身份存在反证 | UNRATED |
| 03 | Agent 编排与审批 | E2：跨实例恢复、逐次鉴权、审批链 | 真实模型多步任务与超时强制中断未验 | UNRATED |
| 04 | ETL 与业务文件处理 | E2：预览/回滚/租户隔离；15 份证据 | **登记范围路径不存在**；C1 无全链路 lineage | UNRATED |
| 05 | AI 意图与工具路由 | E2：留出集 142 例、混淆矩阵、65.49% | 每域仅 10–11 例（<30）；任务基准 22×1；B2 已观察失败 | UNRATED（上限 59） |
| 06 | NeuroBus 事件内核 | E2：DLQ、去重、队列满降级 | 无网络分区/恢复 E3；重放已知缺陷 | UNRATED |
| 07 | Mod SDK 与行业模块 | E2：会话级授权隔离、签名安装回执 | 客户安装/升级 E3 与跨租户负向未验 | UNRATED |
| 08 | 桌面壳与更新恢复 | E1/E2：回滚、凭据、IPC 边界；CI 冒烟 | 目标设备批量更新与数据保留未验收 | UNRATED |
| 09 | FHD 前端与用户任务 | E2：16 个 e2e spec、618 个单测文件 | C3 工作台只追踪健康，不追踪业务结果 | UNRATED |
| 10 | 商城前端与工作流 UI | E2：目录/搜索/授权页面 | C1 无后台订单接口；C2 无组织管理实现 | UNRATED |
| 11 | 商城交易与交付后端 | E2：退款/Webhook 幂等测试 | 无压测/故障注入；交付一致性未验 | UNRATED |
| 12 | 自治与维护执行 | E2：子进程进程组回收、超时、截断 | C3 无队列容量控制；跨节点执行未验 | UNRATED |
| 13 | Java 支付服务 | E1：服务代码存在 | **验签被 mock**；退款不调用渠道；单一 SDK 版本 | UNRATED |
| 14 | Flutter 移动端 | E0/E1：工程存在 | **未锁 Flutter 版本且只构建 debug**；无真机与冲突测试 | UNRATED |
| 15 | Retort 共享引擎 | E2：五标志闭环、吸收状态测试 | 执行证据未绑定产物哈希；C 级缺长期运行证据 | UNRATED |
| 16 | Vibe 编码与沙箱 | E1/E2：路径穿越拒绝、网络隔离+cap-drop | 无留出任务评测；无检查点/恢复 | UNRATED |
| 17 | 客来来独立子系统 | E0：子模块未初始化（0 文件） | 无法取证；仅旁证测试 16 例 | UNRATED |
| 18 | CI、发布与治理 | E2：81 个 workflow、漂移门禁阻塞、负向门禁 | 产物身份/安装升级回退未闭环；C3 无自动回滚 | UNRATED |

## 四、本轮复核的增量事实

1. **统一指标层已落地**：`xcagi_memory_recall_*`、`xcagi_plan_generation_*`、`xcagi_tool_call_*`、
   `xcagi_chat_ttft_ms` 已有埋点，`XCAGI_METRICS=0` 可停用；但**尚无采集端数据**，不构成 E3/E4。
2. **L2 记忆事实化已落地**：规则抽取、`ADD/NOOP/SUPERSEDE`、失效过滤、删除治理与 13 例单测；
   仍属 E2，且无跨会话 recall@5 留出集。
3. **意图路由文档已纠偏**：原引用的 86.6% 无落盘依据，现统一为仓库可复现的 65.49%；
   该域 B1 抽样仍低于协议下限，B2 仍有重复澄清与否定未闭环失败。
4. **两个 scope 失真**：ETL 指向不存在的 `FHD/app/application/etl/`；
   意图路由指向 3 行转发文件 `chat_business_safety_core.py`。按协议需先修正范围再评级。

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
