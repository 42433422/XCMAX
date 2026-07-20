# Evolution 闭环验收 v2 — 2026-07-20（T-C09 修复后）

> T-C10 任务交付 evidence：T-C09 修复 dry-run 信号源单一根因后，重跑五连接点 dry-run，
> 更新 PASS/FAIL 与 trace id。原 evidence 见 `evolution-closed-loop-2026-07-20.md`。

---

## 0. 与 v1 的差异（T-C09 修复要点）

| 项 | v1（修复前） | v2（T-C09 修复后） |
|---|---|---|
| 信号源 below_threshold 数 | 1（仅 legacy_usage） | **3**（legacy_usage + intent_benchmark + slo_metrics 全部 below_threshold） |
| `total_score` | 0.07 | **0.24**（0.07 + 0.15 + 0.02） |
| `signals_to_propose` | 1 | **3** |
| trace 内事件数 | 5（每连接点 1 事件） | **7**（3 signal_detected + 1 proposal + 1 issue + 1 implement + 1 pack_listed） |
| `proposal_generated.signal_score` | 0.15（硬编码，与 total_score 不一致） | **0.24**（与 `_synthetic_signals()['total_score']` 一致） |
| 多源聚合上下文 | 无 | proposal 新增 `aggregated_signal_sources` 字段记录 3 个触发源 |
| trace_id | 62758e4d47f2 | **3195d01b0b32** |
| 修复文件 | — | `FHD/scripts/autonomy/evolution_decision_ledger.py` 的 `_synthetic_signals()` + `cmd_propose_pack()` dry-run 分支 |

> Top2 根因定义：原 dry-run `_synthetic_signals()` 写死 `legacy_usage.below_threshold=True`，其余两源为 False，
> 无法验证实模式 `aggregate_signals()` 多源触发场景（evidence v1 第 8.1 节已识别）。

---

## 1. 验收场景

完整 dry-run 5 连接点闭环：gap → proposal → implement → publish → ledger 全链路。
通过新 CLI `FHD/scripts/autonomy/evolution_decision_ledger.py` 触发，所有事件
写入 `evolution_decisions.jsonl` ledger，共享同一 `trace_id`。

T-C09 修复后，dry-run 在 collect-signals 步骤对 3 个 below_threshold 信号源各写
一条 `signal_detected` 事件，验证多源聚合 → 单 proposal → 单 issue → 单 implement
→ 单 publish 的语义。

## 2. 5 连接点接通状态

| # | 连接点 | 状态 | 实现方式 |
|---|--------|------|---------|
| 1 | legacy-usage-weekly → evolution_handler | ✅ PASS | `collect-signals` 子命令，调用 `_synthetic_signals()`（3 源 below_threshold）+ `evolution_signal_collector.aggregate_signals()`，对每个 below_threshold 信号源写 `signal_detected` 事件 |
| 2 | evolution_handler → ai-issue-implement | ✅ PASS | `propose-pack` 子命令（调 `_synthetic_proposal()`，`signal_score` 与 `_synthetic_signals()['total_score']` 一致，附带 `aggregated_signal_sources` 多源上下文）+ `open-issue` 子命令（调 `gap_to_issue.open_issue_for_proposal()`） |
| 3 | ai-issue-implement → MODstore auto-upload | ✅ PASS | `implement-pack` 子命令 subprocess 调 `FHD/scripts/dev/ai_issue_implement.py --apply` |
| 4 | MODstore auto-upload → ledger 记录 | ✅ PASS | `publish-pack` 子命令调 `build_employee_pack.build_pack_from_commit()`（其内部已调 `append_event`）；CLI 层补充 `trace_id` 关联 |
| 5 | ledger 记录 → 反馈循环 | ✅ PASS | `list` / `summary` / `audit` 子命令 + `evolution-aggregator.yml` workflow 每周 cron + `audit_evolution.py` 独立审计 CLI |

## 3. Dry-run 执行结果

命令：
```bash
cd /Users/a4243342/Desktop/XCMAX/FHD
python3 scripts/autonomy/evolution_decision_ledger.py dry-run
```

输出（trace_id=3195d01b0b32）：

```
=== Evolution closed-loop DRY-RUN (trace_id=3195d01b0b32) ===

[trace_id=3195d01b0b32] Step 1: collect-signals (dry_run=True)
  (dry-run) using synthetic signals: total_score=0.24
  → signal_detected: event_id=01c3cba4 trace_id=3195d01b0b32
    source=legacy_usage score=0.070
  → signal_detected: event_id=26250eaf trace_id=3195d01b0b32
    source=intent_benchmark score=0.150
  → signal_detected: event_id=86690211 trace_id=3195d01b0b32
    source=slo_metrics score=0.020

[trace_id=3195d01b0b32] Step 2: propose-pack (dry_run=True)
  (dry-run) using synthetic proposal_id=dry-run-c5504aa7
  → proposal_generated: event_id=87b024b4 trace_id=3195d01b0b32
    pack_name=intent-failure-triage-clerk department=engineering

[trace_id=3195d01b0b32] Step 3: open-issue (dry_run=True)
  using latest proposal event_id=87b024b4
  → issue_opened: event_id=2d203288 trace_id=3195d01b0b32
    issue_url=https://github.com/example/repo/issues/0#dry-run (dry-run, not actually created)
    pack_name=intent-failure-triage-clerk

[trace_id=3195d01b0b32] Step 4: implement-pack (dry_run=True)
  → implement_succeeded: event_id=31cd5b55 trace_id=3195d01b0b32
    pr_url=https://github.com/example/repo/pull/0#dry-run (dry-run, not actually created)

[trace_id=3195d01b0b32] Step 5: publish-pack (dry_run=True)
  → pack_listed: event_id=4b7806c7 trace_id=3195d01b0b32
    pack_id=dry-run-pack@0.0.1 (dry-run, not actually listed)

=== Trace summary ===
  trace_id: 3195d01b0b32
  events: 7
  final_status: closed_loop_completed

Events written:
  [2026-07-20T13:51:33] 01c3cba4 signal_detected status=signal_detected
  [2026-07-20T13:51:33] 26250eaf signal_detected status=signal_detected
  [2026-07-20T13:51:33] 86690211 signal_detected status=signal_detected
  [2026-07-20T13:51:33] 87b024b4 proposal_generated status=proposal_generated
  [2026-07-20T13:51:33] 2d203288 issue_opened status=issue_opened
  [2026-07-20T13:51:33] 31cd5b55 implement_succeeded status=implement_succeeded
  [2026-07-20T13:51:33] 4b7806c7 pack_listed status=closed_loop_completed
```

### 验证查询

```bash
# 按 trace_id 过滤
python3 scripts/autonomy/evolution_decision_ledger.py list --trace-id 3195d01b0b32
```

```
timestamp                  event_id   event_type             trace_id       status
----------------------------------------------------------------------------------------------------
2026-07-20T13:51:33        01c3cba4   signal_detected        3195d01b0b32   signal_detected
2026-07-20T13:51:33        26250eaf   signal_detected        3195d01b0b32   signal_detected
2026-07-20T13:51:33        86690211   signal_detected        3195d01b0b32   signal_detected
2026-07-20T13:51:33        87b024b4   proposal_generated     3195d01b0b32   proposal_generated
2026-07-20T13:51:33        2d203288   issue_opened           3195d01b0b32   issue_opened
2026-07-20T13:51:33        31cd5b55   implement_succeeded    3195d01b0b32   implement_succeeded
2026-07-20T13:51:33        4b7806c7   pack_listed            3195d01b0b32   closed_loop_completed
```

```bash
# 审计 CLI（FHD/scripts/dev/audit_evolution.py）
python3 scripts/dev/audit_evolution.py --since 1d --summary
```

```
Total events (1d): 68
Unaudited: 67

By event_type:
  implement_failed             28
  implement_succeeded          20
  signal_detected              8
  proposal_generated           4
  issue_opened                 4
  pack_listed                  4

By final_status:
  ?                            31
  implement_failed             10
  signal_detected              8
  proposal_generated           4
  issue_opened                 4
  implement_succeeded          4
  closed_loop_completed        4
  needs_human                  3

Distinct trace_ids: 5
  <none>         44 events
  cdfa24e889b8   7 events
  3195d01b0b32   7 events
  62758e4d47f2   5 events
  4e03b615dd37   5 events
```

> **观察**：T-C09 修复后两次 dry-run（cdfa24e889b8 与 3195d01b0b32）均为 7 事件 trace，
> T-C09 修复前两次 dry-run（62758e4d47f2 与 4e03b615dd37）均为 5 事件 trace。
> 7 事件 = 3 signal_detected + 1 proposal + 1 issue + 1 implement + 1 pack_listed，
> 验证了多源聚合场景下 trace 一致性。

## 4. Ledger trace 验证

### 4.1 本次 dry-run 写入的 7 条事件（trace_id=3195d01b0b32）

文件路径：`成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl`

**事件 1 — signal_detected (legacy_usage)**

```json
{
  "dry_run": true,
  "event_id": "01c3cba4-...",
  "event_type": "signal_detected",
  "final_status": "signal_detected",
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "signal_report": {"legacy_files": 38, "legacy_ratio": 0.32, "total_files": 120},
  "signal_score": 0.07,
  "signal_source": "legacy_usage",
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32",
  "triggered_by": "dry-run"
}
```

**事件 2 — signal_detected (intent_benchmark)**（T-C09 新增）

```json
{
  "dry_run": true,
  "event_id": "26250eaf-...",
  "event_type": "signal_detected",
  "final_status": "signal_detected",
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "signal_report": {"accuracy": 0.65, "errors": 70, "samples": 200},
  "signal_score": 0.15,
  "signal_source": "intent_benchmark",
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32",
  "triggered_by": "dry-run"
}
```

**事件 3 — signal_detected (slo_metrics)**（T-C09 新增）

```json
{
  "dry_run": true,
  "event_id": "86690211-...",
  "event_type": "signal_detected",
  "final_status": "signal_detected",
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "signal_report": {"availability": 0.97, "error_rate": 0.03},
  "signal_score": 0.02,
  "signal_source": "slo_metrics",
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32",
  "triggered_by": "dry-run"
}
```

**事件 4 — proposal_generated**（含 aggregated_signal_sources，T-C09 新增）

```json
{
  "dry_run": true,
  "event_id": "87b024b4-...",
  "event_type": "proposal_generated",
  "final_status": "proposal_generated",
  "llm_proposal": {
    "aggregated_signal_sources": ["legacy_usage", "intent_benchmark", "slo_metrics"],
    "department": "engineering",
    "employee_pack": {
      "acceptance_criteria": ["recall >= 0.7 on test set", "<= 5 files touched", "no HIGH_RISK_PATTERNS touched"],
      "name": "intent-failure-triage-clerk",
      "prompt_template": "You are an intent failure triage clerk...",
      "responsibility": "scan intent benchmark failures, cluster by pattern, propose prompt fixes",
      "skills": ["intent-benchmark", "failure-clustering"],
      "tools": ["read_file", "write_pr_comment"]
    },
    "estimated_files": 3,
    "estimated_tokens": 45000,
    "proposal_id": "dry-run-c5504aa7",
    "signal_score": 0.24,
    "triggered_by": "dry-run"
  },
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "signal_score": 0.24,
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32",
  "triggered_by": "dry-run"
}
```

**事件 5 — issue_opened**

```json
{
  "dry_run": true,
  "event_id": "2d203288-...",
  "event_type": "issue_opened",
  "final_status": "issue_opened",
  "issue_url": "https://github.com/example/repo/issues/0#dry-run",
  "llm_proposal": { /* same as event 4 */ },
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "signal_score": 0.24,
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32",
  "triggered_by": "dry-run"
}
```

**事件 6 — implement_succeeded**

```json
{
  "cost_tokens": 0,
  "dry_run": true,
  "event_id": "31cd5b55-...",
  "event_type": "implement_succeeded",
  "files_written": ["prompt.txt", "skills.json", "manifest.json"],
  "final_status": "implement_succeeded",
  "issue_url": "https://github.com/example/repo/issues/0#dry-run",
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "pr_url": "https://github.com/example/repo/pull/0#dry-run",
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32"
}
```

**事件 7 — pack_listed (final_status=closed_loop_completed)**

```json
{
  "commit_sha": "dry-run-sha-0000000",
  "dry_run": true,
  "event_id": "4b7806c7-...",
  "event_type": "pack_listed",
  "final_status": "closed_loop_completed",
  "owner_audit": {"audited": false, "audited_at": null, "verdict": null},
  "pack_id": "dry-run-pack@0.0.1",
  "risk_level": "low",
  "risk_reason": "dry-run synthetic approval",
  "timestamp": "2026-07-20T13:51:33...+00:00",
  "trace_id": "3195d01b0b32"
}
```

### 4.2 trace_id 一致性验证

7 条事件的 `trace_id` 字段全部为 `3195d01b0b32`，时间戳全部为 `2026-07-20T13:51:33`（秒级一致），
event_type 序列覆盖：`signal_detected ×3 → proposal_generated → issue_opened → implement_succeeded → pack_listed`，
`final_status` 链路在事件 7 终止于 `closed_loop_completed`。

多源聚合语义验证：
- 3 条 signal_detected 各自记录独立信号源（legacy_usage / intent_benchmark / slo_metrics）
- 1 条 proposal_generated 的 `llm_proposal.aggregated_signal_sources` 字段记录 3 个触发源
- 1 条 proposal_generated 的 `signal_score=0.24` = 3 源 signal_score 之和（0.07+0.15+0.02）
- 后续 4 条事件（issue/implement/pack_listed）共享同一 proposal，体现"多源聚合 → 单 proposal"语义

## 5. 验收结论

- [x] **5 连接点全部接通**：PASS — 5 个连接点均有对应 CLI 子命令 + workflow 调用入口
- [x] **dry-run 产出完整 trace**：PASS — trace_id=3195d01b0b32 包含 7 条事件，event_type 序列完整
- [x] **多源信号场景验证**：PASS（T-C09 新增）— collect-signals 步骤写 3 条 signal_detected 事件（legacy_usage + intent_benchmark + slo_metrics），验证实模式多源触发场景
- [x] **signal_score 与 total_score 一致**：PASS（T-C09 新增）— proposal_generated 的 signal_score=0.24 = `_synthetic_signals()['total_score']` = 0.24，消除原 v1 中 0.15 与 0.07 不一致的问题
- [x] **aggregated_signal_sources 上下文记录**：PASS（T-C09 新增）— proposal_generated 的 llm_proposal 中包含 `aggregated_signal_sources` 字段，记录 3 个触发源
- [x] **ledger 文件有 7 条新事件**：PASS — 已追加到 `data/evolution_decisions.jsonl`
- [x] **CLI --help 文档**：PASS — `evolution_decision_ledger.py --help` 输出 8 个子命令
- [x] **trace_id 贯穿全链路**：PASS — 同一 dry-run 内 7 事件共享 trace_id
- [x] **workflow 同步到根仓**：PASS — `fhd-evolution-aggregator.yml` 已生成于 `.github/workflows/`
- [x] **audit 子命令可用**：PASS — `audit_evolution.py --since 1d --summary` 输出 68 events / 5 trace_ids，包含本次 trace 3195d01b0b32（7 events）
- [x] **append_evolution_event CLI 可用**：PASS — 通用写 ledger 工具验证通过
- [x] **audit_evolution.py CLI 可用**：PASS — 独立审计 CLI 验证通过（含 `--summary` 统计）
- [x] **ruff check 通过**：PASS — `ruff check scripts/autonomy/evolution_decision_ledger.py` All checks passed!

## 6. 修改文件清单

### 修改

1. `FHD/scripts/autonomy/evolution_decision_ledger.py`
   - `_synthetic_signals()`：3 源全部 below_threshold=True，total_score 从 0.07 → 0.24，signals_to_propose 从 1 → 3
   - `cmd_propose_pack()` dry-run 分支：signal_score 从硬编码 0.15 改为读 `_synthetic_signals()['total_score']`，并在 proposal 中添加 `aggregated_signal_sources` 字段

### 新建

1. `FHD/docs/evidence/e2e/evolution-closed-loop-2026-07-20-v2.md` — 本 evidence 文档（T-C10 交付物）

## 7. 设计要点

### 7.1 trace_id 贯穿机制

每次 `dry-run` 在入口生成 12 位 hex trace_id（`uuid.uuid4().hex[:12]`），通过 `argparse.Namespace(trace_id=trace_id)` 在 5 个子命令间显式传递，每条 `append_event` 调用都包含 `trace_id` 字段。

### 7.2 多源信号聚合语义（T-C09 新增）

```
[3 个 below_threshold 信号源]
legacy_usage (score=0.07) ─┐
intent_benchmark (score=0.15) ─┼─→ [aggregate_signals() / _synthetic_signals()]
slo_metrics (score=0.02) ─┘            ↓
                                  total_score = 0.24
                                  signals_to_propose = 3
                                          ↓
                            [propose_employee_pack() / _synthetic_proposal()]
                                          ↓
                            proposal_generated.event_id=87b024b4
                            proposal.signal_score = 0.24 (与 total_score 一致)
                            proposal.aggregated_signal_sources = [3 源]
                                          ↓
                            [open_issue_for_proposal()] → 1 个 issue
                                          ↓
                            [implement_employee_pack()] → 1 个 PR
                                          ↓
                            [build_pack_from_commit()] → 1 个 pack_listed
```

### 7.3 dry-run 副作用隔离（与 v1 一致）

- 不调 GitHub API（不创建 issue / PR）
- 不调 LLM（用 `_synthetic_proposal()` 合成提议）
- 不调 `build_pack_from_commit()`（不真实上架）
- 所有 dry-run 事件都标记 `"dry_run": true`，便于区分
- 用合成信号源（3 源全部 below_threshold，验证多源场景）

### 7.4 实模式（CI 触发）行为

- `collect-signals`：调 `aggregate_signals()` 读真实报告
- `propose-pack`：调 `employee_autonomy_service.propose_employee_pack()` 真实 LLM
- `open-issue`：调 `gap_to_issue.open_issue_for_proposal()` 真实创建 issue
- `implement-pack`：subprocess 调 `ai_issue_implement.py --apply` 真实创建 PR
- `publish-pack`：调 `build_pack_from_commit()` 真实上架

### 7.5 与现有 `evolution-orchestrator.yml` 的关系

| Workflow | 职责 | 触发 |
|---|---|---|
| `fhd-evolution-orchestrator.yml` | 直通管道：信号 → issue → PR 合并 → 上架 | 每周一 04:00 UTC + PR closed |
| `fhd-evolution-aggregator.yml` | 5 连接点 dry-run + ledger trace 验证 | 每周一 05:00 UTC + workflow_dispatch |

两者共享 `evolution_decisions.jsonl` ledger，aggregator 故意晚 1 小时跑，避免与 orchestrator 同时触发产生竞态。

## 8. 已知限制与下一步（v2 更新）

1. **dry-run 多源信号场景已验证**（T-C09 修复，原 v1 限制 1 已消除）：实模式 `aggregate_signals()` 可能产出多源信号，会写多条 `signal_detected` 事件，trace 内事件数 >5 属正常。本次 v2 dry-run trace 内 7 事件已验证此场景。
2. **`open-issue` 实模式会写 2 条 issue_opened 事件**（未修复，T-C09 范围外）：`gap_to_issue.open_issue_for_proposal()` 内部已 `append_event` 一次（无 trace_id），CLI 层补写一条带 trace_id 的关联事件。后续可重构 `gap_to_issue` 接受 `trace_id` 参数消除冗余。
3. **未覆盖单元测试**（未修复，T-C09 范围外）：T3 任务范围为"落地 + dry-run"，单元测试归 spec Task 12/13 范围。
4. **workflow git push 可能被分支保护拦截**（未修复，T-C09 范围外）：`fhd-evolution-aggregator.yml` 的 `git push` 步骤在 main 保护下会失败，输出 "push skipped"。可后续改为 PR-based ledger 同步。

> Top2 根因（dry-run 信号源单一）已修复。Top1 根因（open-issue 实模式重复事件）与 Top3/Top4 根因不在 T-C09 范围内，留给后续任务。
