# ESkill：文档所有权管理（skill-doc-ownership）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-doc-ownership` |
| 所属员工 | `log-monitor-incident` |
| 业务域 | 日志监控、事故响应与 SRE 运维相关文档的准确性维护与代码-文档同步 |
| 版本 | 1.1.0 |

## 1. 静态阶段

**触发条件**：满足以下全部条件时走静态路径。
- 监控/运维相关代码或配置文件发生变更（git diff 检测）
- 变更涉及 `metrics.py`、`prometheus.yml`、`modstore-alerts.yml`、`chaos_drill.py`、`sre_smoke_check.py`、`backup_modstore.py`、`restore_postgres.py` 等 scope_globs 内文件
- 无历史已知异常 flag

**执行逻辑**：
```
检测 scope_globs 内代码/配置变更 → 识别受影响的文档
→ 对比文档描述与代码实现是否一致
→ 若 git diff 涉及 MODstore_deploy/monitoring/prometheus/rules/*.yml
   或 MODstore_deploy/monitoring/**/*.yaml：
     A) promtool check rules <file>（PATH 中无 promtool 时降级：仅做 YAML 结构启发式校验：
        顶层须含 groups[]；每组须含 name、rules[]；每条 rule 须含 alert、expr、for）
     B) 阈值合理性启发式（写入 threshold_warnings，非硬错误）：
        - 表达式含 5xx 比率且阈值 > 0.05（每秒）：记「高于常见 API 基线，易漏报或噪声—建议与 modstore-backend-api 对齐 SLO」
        - 表达式为 http p95 / histogram_quantile 且 > 1s（API）或 > 2s（payment proxy）：记「延迟阈值偏紧/偏松需业务确认」
        - 堆或连接池占用阈值 > 0.85：记「与当前 modstore-alerts 基线一致，变更时需同步 observability 文档」
        - for: < 1m：记「疑似抖动敏感」；for: > 30m：记「疑似过迟告警」
     C) -syntax_ok / syntax_errors 写入 alert_rule_validation
→ 不一致时生成同步建议（diff 格式）
→ 一致且无语法错误时输出通过报告（threshold_warnings 可非空）
```

**负责文档清单**：

| 文档 | 路径 | 对应代码/配置 |
|------|------|---------------|
| Prometheus + Grafana 监控 | `MODstore_deploy/docs/observability.md` | `metrics.py`、`prometheus.yml`、`modstore-alerts.yml` |
| 监控与 Grafana 统一说明 | `MODstore_deploy/docs/OPS_MONITORING.md` | `metrics.py`、`prometheus.yml` |
| 事故响应 Runbook | `MODstore_deploy/docs/runbooks/incident-response.md` | `sre_smoke_check.py`、告警规则 |
| SRE 运行体系 | `MODstore_deploy/docs/sre-operating-model.md` | `sre_smoke_check.py`、`perf/full_link_smoke.js` |
| 灾备与恢复 Runbook | `MODstore_deploy/docs/runbooks/disaster-recovery.md` | `backup_modstore.py`、`restore_postgres.py` |
| 混沌演练 Runbook | `MODstore_deploy/docs/runbooks/chaos-game-day.md` | `chaos_drill.py` |

**输出 schema**：
```json
{
  "status": "ok | needs_sync | error",
  "checked_docs": ["doc_path_1", "doc_path_2"],
  "sync_suggestions": [
    {
      "doc_path": "",
      "section": "",
      "current_text": "",
      "suggested_text": "",
      "reason": ""
    }
  ],
  "alert_rule_validation": {
    "syntax_ok": true,
    "syntax_errors": ["promtool: ... or yaml: ..."],
    "threshold_warnings": [
      {
        "rule": "ModstoreApiHigh5xxRate",
        "current": "0.05 requests/s",
        "baseline_low": "0",
        "baseline_high": "0.05",
        "suggestion": "与 SLO 文档对齐；变更需 admin + modstore-backend-api 复核"
      }
    ]
  },
  "metrics": {
    "docs_checked": 0,
    "inconsistencies_found": 0
  }
}
```

**边界**：本员工 **不修改** `MODstore_deploy/monitoring/**/*.yml` 告警规则文件；仅输出 `alert_rule_validation` 与文档同步建议。规则变更由 **admin** 协调 **`modstore-backend-api`** 落地。

**工具绑定**：
- `git diff`（检测代码/配置变更）
- `promtool check rules`（可选）
- 文件读取（对比文档与代码实现）

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 执行报错 | 文件读取失败、文档格式异常 | 即触发 |
| 结果不达标 | `metrics.inconsistencies_found > 0` 且自动修复失败 | 可配 |
| 场景特殊 | 新增代码/配置文件但无对应文档说明 | 可配 |
| 告警规则 | `alert_rule_validation.syntax_ok == false` | 触发动态阶段或升级 admin |

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：`4000`（来自 employee.yaml `max_patch_budget_tokens`）
- 最大步数：`5`

**允许改动的模块白名单**：
- `MODstore_deploy/docs/observability.md`
- `MODstore_deploy/docs/OPS_MONITORING.md`
- `MODstore_deploy/docs/runbooks/incident-response.md`
- `MODstore_deploy/docs/sre-operating-model.md`
- `MODstore_deploy/docs/runbooks/disaster-recovery.md`
- `MODstore_deploy/docs/runbooks/chaos-game-day.md`
- `yuangon/server-and-ops/log-monitor-incident/README.md`
- `yuangon/server-and-ops/log-monitor-incident/runbook.md`

**LLM 补丁格式**：
```json
{
  "patch_id": "<uuid>",
  "base_version": "1.1.0",
  "proposals": [
    {
      "target_doc": "MODstore_deploy/docs/observability.md",
      "section": "已落地告警",
      "change_type": "update_description | add_section | remove_stale",
      "description": "同步新增告警规则到文档",
      "text_diff": "..."
    }
  ]
}
```

## 4. 固化

**验收标准**：
- [ ] 所有受影响文档已与代码实现一致
- [ ] `metrics.inconsistencies_found == 0`
- [ ] `alert_rule_validation.syntax_ok == true` 或已提交 admin 跟踪修复
- [ ] 文档变更通过人工审核（admin 确认）
- [ ] Sandbox 环境无副作用外溢

**固化后动作**：
1. 生效 delta 写入 `skills/skill-doc-ownership-v2.md`
2. `employee.yaml` 中版本号递增
3. 旧版本保留（打 tag `deprecated`）供回滚

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| 文档-代码一致性率 | ≥ 95% |
| 静态路径成功率 | ≥ 90% |
| 动态触发率 | ≤ 15% |
| 文档同步延迟 | ≤ 24h（代码变更后） |
