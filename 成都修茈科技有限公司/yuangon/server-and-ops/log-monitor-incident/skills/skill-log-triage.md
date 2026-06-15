# ESkill：日志分级与事故分诊（skill-log-triage）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-log-triage` |
| 所属员工 | `log-monitor-incident` |
| 业务域 | 日志分析与事故响应 |
| 版本 | 1.1.0 |

## 契约

- **契约**：`.cursor/contracts/error-code-map.yaml`（仓库根；详见 `.cursor/contracts/README.md`）。
- 每条 `entries[]` 含 `code`、`source`、`pattern`（Python `re` 正则）、`severity`、`root_cause_class`、`recommended_owner_employee`、`runbook_anchor`。

## 1. 静态阶段

**执行逻辑**：
```
1. 读取 coverage/、playwright-report/、test-results/、.cursor_*_log.txt（及任务 input.sources）
2. 粗筛：保留 error/fail/exception/FAILED 等行（可与 grep 等价）
3. 加载 error-code-map.yaml → 按 source 过滤相关 entries
4. 匹配规则（同一行可命中多条时保留 specificity 最高的一条）：
   - 先匹配非 “泛化” 规则（code 不为 MS-LOG-GENERIC 或等价泛匹配）
   - MS-LOG-GENERIC 仅当该行未被其它 cursor_log 规则命中时使用
5. 为每条 incident 生成：code、source、severity、root_cause_class、owner（= recommended_owner_employee）、evidence_path、matched_line（摘要）
6. 未命中任何 entry 的条目进入 unmapped_entries
7. mapping_coverage_rate = (triage_entries.length) / (triage_entries.length + unmapped_entries.length)；若无 incident 则记 1.0
8. 按 P0/P1/P2 填入 p0_incidents / p1_incidents（p2 可仅在 triage_entries 中体现）
9. 生成 report_md：必须以机器可读元数据块开头（见下），其后为「摘要 → P0 列表 → 覆盖率趋势 → 建议」
```

### `report_md` 元数据头（必填）

`report_md` **必须**以如下 fenced block 开头（info string 固定为 `modstore-report-meta`），其后接一个空行再写正文：

````markdown
```json modstore-report-meta
{
  "schema": "modstore.daily-health-report/v1",
  "report_id": "<uuid>",
  "generated_at": "<ISO8601>",
  "employee_id": "log-monitor-incident",
  "employee_version": "1.2.0",
  "data_sources": [
    {"path": "coverage/", "sha256": "..."},
    {"path": "playwright-report/", "sha256": "..."},
    {"path": ".cursor_*_log.txt", "files": 3, "sha256_combined": "..."}
  ],
  "data_sources_hash": "<sha256 of sorted per-source hashes>",
  "error_code_map_version": "<copy from error-code-map.yaml version>",
  "summary_counts": {"p0": 0, "p1": 0, "p2": 0, "unmapped": 0}
}
```
````

**解析约定**：下游取 `report_md` 内**首个** info string 为 `modstore-report-meta` 的 fenced JSON 块；缺失或 JSON 无效则视为 **schema 不合规**。

**输出 schema（顶层 JSON，与 system.md 一致）**：
```json
{
  "status": "ok | warning | critical",
  "p0_incidents": [],
  "p1_incidents": [],
  "p2_incidents": [],
  "coverage_delta_pct": 0.0,
  "triage_entries": [
    {
      "code": "MS-TEST-ASSERT",
      "source": "pytest",
      "severity": "P1",
      "root_cause_class": "business",
      "owner": "test-qa-runner",
      "evidence_path": "",
      "matched_line": ""
    }
  ],
  "unmapped_entries": [
    { "evidence_path": "", "snippet": "", "reason": "no_pattern_match" }
  ],
  "mapping_coverage_rate": 1.0,
  "report_md": "```json modstore-report-meta\n{...}\n```\n\n## 摘要\n..."
}
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 日志文件不可读；`error-code-map.yaml` 缺失或 YAML 损坏 |
| 结果不达标 | `p0_incidents` 非空；`coverage_delta_pct < -5`；`mapping_coverage_rate < 0.8` 且 `unmapped_entries.length > 0` |

## 3. 动态阶段

**预算**：2000 tokens，3 步。  
**约束**：只读日志与契约，不修改源码。  
**LLM 任务**：对 P0 事故生成根因假设与推荐处置步骤；对 `unmapped_entries` 建议新增 `error-code-map.yaml` 条目（仅建议，实际改契约需 admin）。

## 4. 固化

**验收标准**：`p0_incidents` 已全部推送给相关员工确认；`mapping_coverage_rate ≥ 0.8` 或已登记待补 `error-code-map` 条目。

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| mapping_coverage_rate | ≥ 80%（当存在 unmapped 时触发复核） |
