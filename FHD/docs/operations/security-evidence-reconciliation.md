# 安全证据校准（不等于发布放行）

## 依赖清单

`fhd-dependency-snapshot.yml` 在主线提交、每日定时或人工触发时，从当前
`main` 的 Git 对象读取两份 Python 锁文件的每个精确版本条目。
提交前再次核对主线 SHA；空文件、重复包名、非精确锁定条目都失败。
固定 detector/correlator，避免为每个提交创建一个长期并存的数据源。
每份清单附原文件 SHA256，工作流制品保留 120 天。

此快照只声明对应锁文件中的条目。服务端锁文件是顶层版本清单，**不是完整的
运行时依赖闭包**；不得用此快照代替 pip-audit、镜像、桌面制品或生产主机扫描。
所有原有扫描器和 `security-release-gate` 保持独立、失败即阻断。

API 返回成功不算校准完成。必须再读取 GitHub dependency graph 和 Dependabot，
确认同一路径旧版本消失，当前全部锁定条目仍在。不通过 dismiss/ignore 消除告警。
快照优先级与固定身份依据：
[GitHub dependency submission API](https://docs.github.com/en/rest/dependency-graph/dependency-submission)。

## 历史误报复核

在仓库根目录使用 Python 3.11+：

```sh
python FHD/scripts/security/export_codeql_review_packet.py \
  --input /secure/evidence/codeql-dismissed.json \
  --sha <40位主线SHA> \
  --output /secure/evidence/codeql-independent-review-queue.json
```

输入须为 GitHub 已认证的完整分页导出。输出逐条保留告警 ID、规则、位置、
最后分析 SHA、待复核主线 SHA、源码文件 SHA256、历史关闭者及评论摘要。
不复制评论正文或源码，不生成批准，不改变 GitHub 告警状态。

独立复核者须查看原告警、准确版本的代码及完整数据流，逐条判断修复或误报。
误报记录按现有门禁要求包含作者、复核人、理由、证据和复查期限；不得缺失作者，
不得以同一账号大小写不同冒充独立复核。平台关闭原因必须为误报：
CodeQL `false positive` 或 Dependabot `inaccurate`。接受风险、暂不处理、
仅测试使用等原因不会自动转为误报。[GitHub 原因枚举](https://docs.github.com/en/rest/dependabot/alerts#update-a-dependabot-alert)。

## 发布边界

依赖清单恢复、历史复核队列生成、工作流成功，均不证明安全清零。
生产补丁、运行中内核、泄露凭据轮换与独立复核、连续两次每日全量零告警扫描，
仍须全部满足，才能冻结发布 SHA。90 天 SLO 和客户六阶段证据另行验收。

## SLO 口径纠正

比例使用同窗口真实累计计数，不将低流量分母抬高到每秒 1 次。
分母为零或缺失时返回无读数，而非 100% 成功；样本数量门槛不变。
独立 `slo-promql` 检查使用 Prometheus 官方 promtool 执行稀疏流量、计数器重置、
零样本、遥测缺失和环境隔离案例。所有数据只在无网络测试容器内使用，
不导入生产、不充作 SLO 样本。

保留旧字段 `coverage`（10 项 SLO 的非空比例），新增 `scrape_coverage` 和
逐目标 `scrape_evidence`。按生产配置固定 FHD/MODstore 两个目标、15 秒间隔，
分别核算最近 24 小时实际成功抓取次数 / 5760；取较低值，不能让一个服务
补偿另一个服务失联。目标/间隔与生产配置有回归校验，修改配置必须同步盘点。
缺失、异常计数或任何目标低于 99% 均阻止 Day 0；缺少此证据的历史记录
不计入正式连续期。原始历史文件和哈希链不改写。

运行测试：

```sh
python FHD/scripts/observability/build_slo_promql_tests.py --output /tmp/slo-promql-tests.json
docker run --rm --network none -v /tmp/slo-promql-tests.json:/tests.json:ro \
  --entrypoint /bin/promtool prom/prometheus:v3.14.0 test rules /tests.json
```
