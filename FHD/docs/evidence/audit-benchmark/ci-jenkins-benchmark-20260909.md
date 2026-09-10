# R22 外部标杆实测：CI、发布与治理域开源锚点（Jenkins）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Jenkins 2.462.3 LTS（war 包官方发行版，MIT），零插件 core-only，本机 JDK17 直连运行。**版本边界**：基准目录固定参考为 jenkinsci/jenkins@2701fc6c（master 线 2.582-SNAPSHOT），本次实测为受支持 LTS 稳定发行版 2.462.3，差异已在本记录登记（政策允许，不声称等同该 SHA） |
| dataset_hash | 任务脚本随本文档存档（同目录 ci-jenkins-tasks） |
| task_protocol | B1 流水线从固定源码重建产物；B2 失败检查真实拦截（下游不跑）；B3 凭据/权限最小化与构建审计 |
| predeclared_metrics_and_tolerances | BUILT_SHA 与固定提交 SHA 精确一致、产物内容精确匹配；上游 FAILURE 时下游 lastBuild=404；匿名读/未认证写均 403、明文密码 0 泄漏、bcrypt 散列≥1、构建结果/时长/时间戳可查 |
| environment | 本机 macOS，java -jar jenkins.war --httpPort=18090，runSetupWizard=false，安全域为本地用户数据库（admin 监控） |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 商业锚点（GitHub Enterprise / GitLab Ultimate / Harness）未实测；Kubernetes/Agent 分布式构建、凭据插件库（Credentials Plugin）、多分支流水线与锁文件语义不在 core-only 任务范围（XCMAX 锁文件重建由 R05/R09 验收覆盖） |
| domain_status | ci-release 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实软件环境完整任务） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 固定源码重建产物 | ci-release-B1 | PASS | 本地 git 仓库以固定 author/committer 日期产生确定性 SHA `ed67ce2e…`；job 内 clone+checkout 该 SHA 后构建，`BUILT_SHA` 精确等于源 SHA，`dist.txt=artifact-v1` 内容精确匹配，res=SUCCESS |
| B2 失败检查真实拦截 | ci-release-B2 | PASS | `r22-fail`（exit 1）构建结果 FAILURE；SUCCESS 阈值触发的下游 `r22-down` lastBuild=404（未运行），失败被真实拦截而非仅记录 |
| B3 最小权限与审计 | ci-release-B3 | PASS | 匿名 `/api/json`=403、未认证 POST build=403；`users/` 目录 grep 明文密码=0 泄漏、jbcrypt 散列配置=2；构建 API 可查每次构建的 number/result/duration/timestamp |

## 环境修复记录（如实留痕）

- 任务脚本需幂等：重复运行时旧 job 配置（含过期 SHA）导致 B1 误判 FAILURE，`mkjob` 增加先 `doDelete` 再 `createItem`。
- Jenkins tree 参数含 `[ ]` 需 curl `-g`（关闭 globbing），否则 `builds[...]` 查询返回空导致 B3 误判。
- 作业配置 XML 中 `&&`/`>` 需转义为 `&amp;&amp;`/`&gt;`，否则 SAXParseException。
- CSRF crumb 与会话绑定，创建/触发请求须共享 cookie jar（curl `-c/-b`）。

## 与 XCMAX 侧对照

XCMAX 同域验收见 PR#1826 门禁链（R04 变异测试漏跑修复、R05 Flutter 锁文件、R09 构建/支付沙箱、
R14 桌面发布双扫描门禁）。本记录证明 Jenkins 开源基线在同等必选语义（固定源码重建、失败真实拦截、
最小权限与构建审计）上行为一致，XCMAX CI/发布契约不低于该开源锚点；
不据此宣称达到商业产品水平（90 分锚点未实测）。
