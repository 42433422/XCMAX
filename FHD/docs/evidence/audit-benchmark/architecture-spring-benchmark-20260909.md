# R22 外部标杆实测：依赖注入与分层域开源锚点（Spring Framework）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Spring Framework 5.3.39（Maven Central 官方构件，Apache-2.0），JDK 17 Temurin，本地直连运行。**版本边界**：SSOT 锁定 main@572850bd（6.2.x 开发线），本次实测为受支持稳定发行版 5.3.39，差异已在审计记录登记（政策允许，不声称等同该 SHA） |
| dataset_hash | 任务脚本随本文档存档（同目录 architecture-spring-tasks） |
| task_protocol | B1 组合根+生命周期+适配器替换；B2 契约可自动验证（缺依赖 fail-fast）；B3 初始化/并发失败可定位 |
| predeclared_metrics_and_tolerances | 适配器输出精确匹配；端口无实现时 refresh 必抛；BeanCreationException 定位 bean 名+根因；40 并发无丢失 |
| environment | 本机 macOS JDK17，spring-core/beans/context/aop/expression/jcl 直连 |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 商业锚点（SAP BTP / Mendix / OutSystems）未实测；Web 层/事务/AOP 全栈能力不在本任务范围（architecture 域只取 DI 与分层必选语义） |
| domain_status | architecture 域开源 60 分锚点：B1/B2/B3 实测通过（E2/E3：真实库、完整任务） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 组合根+生命周期+替换 | architecture-B1 | PASS | 业务核心 `Business` 仅依赖 `GreeterPort`；换 CfgA→CfgB 适配器输出 A:r22→B:r22 零改动；`close()` 后取 bean 抛 IllegalStateException |
| B2 契约自动验证 | architecture-B2 | PASS | 端口无实现时 `refresh()` 抛异常（fail-fast），依赖契约在启动期即校验 |
| B3 初始化/并发可定位 | architecture-B3 | PASS | BrokenInit 构造抛错 → `BeanCreationException` 精确定位 bean 名 `broken`+根因 `boom-init`；单例并发 40 任务无丢失（count=40） |

## 与 XCMAX 侧对照

XCMAX 同域验收见 R19（DI 生命周期/组件替换/初始化故障：33+2 项全绿）。本记录证明 Spring 开源基线在同等必选语义
（组合根、契约 fail-fast、初始化失败可定位）上行为一致，XCMAX DI 容器契约不低于该开源锚点；不据此宣称达到商业产品水平。
