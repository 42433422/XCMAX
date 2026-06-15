# Runbook — 日志监控与事故响应员

| 字段 | 值 |
|------|----|
| 员工 ID | `log-monitor-incident` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 日常巡检

```bash
# 查看最新 pytest 结果
cat MODstore_deploy/.pytest_cache/v/cache/lastfailed

# 查看覆盖率摘要
coverage report --rcfile=.coveragerc 2>/dev/null || echo "no coverage data"

# 汇总 cursor agent 日志错误（粗筛；精确分级用 .cursor/contracts/error-code-map.yaml）
grep -i "error\|fail\|exception" .cursor_*_log.txt | tail -50

# Prometheus 告警规则语法检查（需安装 prometheus 工具链）
command -v promtool >/dev/null 2>&1 && \
  promtool check rules MODstore_deploy/monitoring/prometheus/rules/modstore-alerts.yml \
  || echo "promtool not in PATH; use skill-doc-ownership YAML heuristic"

# 检查所负责文档与代码的一致性
git diff HEAD~5 -- MODstore_deploy/modstore_server/metrics.py \
  MODstore_deploy/monitoring/prometheus/prometheus.yml \
  MODstore_deploy/monitoring/prometheus/rules/modstore-alerts.yml \
  MODstore_deploy/chaos/chaos_drill.py \
  MODstore_deploy/scripts/sre_smoke_check.py \
  MODstore_deploy/scripts/backup_modstore.py \
  MODstore_deploy/scripts/restore_postgres.py \
  | head -200

# 阈值核对清单（启发式，详见 skill-doc-ownership）
# - API 5xx rate > 0.05/s、payment proxy > 0.02/s → 与 OPS_MONITORING 对照
# - API p95 > 1s、payment proxy p95 > 2s → 与 SLO 对照
# - heap/pool > 0.85 → 与 observability 对照
# - for: <1m → 抖动风险；for: >30m → 迟报风险
```

### 每日健康报告 `report_md` 元数据头自检

将当日报告保存为 `reports/daily-health-$(date +%F).md` 后：

```bash
# 确认首个 fenced 块为 modstore-report-meta 且 JSON 含必填键
report_md_path="${1:-reports/daily-health-$(date +%F).md}"
python -c "
import json, re, sys
p = sys.argv[1]
text = open(p, encoding='utf-8').read()
m = re.search(r'\`\`\`json\s+modstore-report-meta\s*\n(.*?)\`\`\`', text, re.S)
assert m, 'missing modstore-report-meta block'
meta = json.loads(m.group(1))
for k in ('schema', 'report_id', 'generated_at', 'employee_id', 'employee_version',
          'data_sources', 'data_sources_hash', 'error_code_map_version', 'summary_counts'):
    assert k in meta, 'missing key: ' + k
print('report_md metadata OK')
" "$report_md_path"
```

用法：`bash -c '...' _ path/to/report.md` 或在上级脚本中第一个参数传入报告路径。

（若本机无 `python`，可用 `node`/`jq` 等价解析首个 fenced 块。）

## 工作流执行引擎日志（与 `modstore_server` 契约）

本员工 **不修改** `MODstore_deploy/modstore_server/workflow_engine.py`。当 `modstore-backend-api` 在该引擎增加 **单行结构化日志**（例如 JSON：`workflow_id`、`execution_id`、`node_id`、`node_type`、`duration_ms`、`step_index`）时：

1. 请对方在变更说明或 PR 中附带 **字段列表与示例行**。
2. 将字段说明追加到本 runbook（或 `MODstore_deploy/docs/observability.md` 由文档责任人同步），便于规则匹配与告警。
3. 现有非结构化 `logger.info("执行 ... 节点: %s", node.name)` 仍可按文本关键词做粗粒度告警；迁移结构化后优先解析 JSON 字段。

其余巡检命令不变。

### 异常 1：测试失败数 > 0

1. 解析 pytest 输出，找到失败用例和错误信息。
2. 用 `.cursor/contracts/error-code-map.yaml` 为失败行标注 `code` / `root_cause_class`（与 `test-qa-runner` 输出对齐）。
3. 按 P0（阻断发布）/ P1（次日修复）/ P2（观察）分级。
4. P0 通知 `deploy-release-officer` 阻止发布；通知对应员工修复。

### 异常 2：覆盖率下降 > 5%

1. 识别新增代码是否缺少测试。
2. 通知 `test-qa-runner` 补充用例。

### 异常 3：Playwright E2E 失败

1. 在 `playwright-report/` 中找到截图和 trace。
2. 用 `error-code-map.yaml` 中 `source: playwright` 条目标注失败类型。
3. 判断是前端 bug 还是环境问题。
4. 通知 `market-frontend-dev` 或 `workbench-ux-stylist`（前端）/ `deploy-release-officer`（环境）。

### 异常 4a：文档与代码不一致

1. 通过 `git diff` 检测到监控/运维相关代码或配置变更。
2. 读取变更内容，对比所负责的 6 个文档对应章节。
3. 生成同步建议（diff 格式），包含 `doc_path`、`section`、`current_text`、`suggested_text`、`reason`。
4. 提交 admin 审核确认。
5. admin 确认后修改文档，记录变更到 ESkill 动态阶段触发记录表。
6. 若 admin 驳回，保留不一致记录并标记待人工处理。

### 异常 4b：告警规则语法或阈值异常

1. 对变更的 `MODstore_deploy/monitoring/prometheus/rules/*.yml` 运行 `promtool check rules`（或记录 YAML 结构校验失败原因）。
2. 将 `syntax_errors` / `threshold_warnings` 写入顶层输出的 `alert_rule_validation`。
3. **不得**直接修改规则文件：提交 **admin** 与 **`modstore-backend-api`** 复核阈值与 SLO、由有权限者改 YAML。
4. 同步更新 `MODstore_deploy/docs/observability.md` / `OPS_MONITORING.md`（经 admin 批准的文档补丁）。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
