# 自治系统运维手册（Autonomy Operations Manual）

> **范围**：XCMAX 三端一体化自治系统（桌面 / 服务器 / CI）的设计、运维与故障演练。
> **适用版本**：v10.0.0+。
> **维护原则**：本手册与代码同源，任何 autonomy 模块的变更必须同步更新本手册。
> **关联文档**：[CI_SSOT.md](./CI_SSOT.md) 中的"自治闭环（Autonomy）"章节。

---

## 1. 概述

XCMAX 自治系统覆盖三个执行端，组成完整闭环：

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   桌面端          │    │   服务器端        │    │   CI 端           │
│  AutonomyCtrl    │    │ cvm-autonomy-    │    │ ai-self-heal +   │
│  (Electron)      │    │ watcher          │    │ ai-review        │
│                  │    │ (cron SSH)       │    │ (workflow_run)   │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────┬───────────┴───────────┬───────────┘
                     │                       │
                     ▼                       ▼
             ┌──────────────────────────────────────┐
             │   CrossTierGate（跨端门禁）          │
             │   env XCAGI_CROSS_TIER_GATE=1 启用    │
             │   fail-closed：查询失败阻断          │
             └──────────────────────────────────────┘
```

### 用户三大痛点 → 自治系统映射

| 痛点 | 自治系统解决方案 |
|---|---|
| **触发闭环**：告警→RCA→修复→验证→上线→回滚半自动 | 三端 AutonomyController + cvm-autonomy-watcher + ai-self-heal 形成完整链路，关键节点自动执行 |
| **非代码故障**：配置漂移/基础设施/网络/数据不一致 AI 看得见动不了 | degraded-remediation policy + 服务器 4 个 policy（health_down/manifest_drift/disk_full/compose_unhealthy）+ CI LLM 兜底诊断 |
| **副作用预测**：修了 A 崩了 B | 桌面 impact-predictor.ts + 服务器 impact_predictor.py + 跨端门禁 cross_tier_gate |

---

## 2. 七元契约（七元一体）

所有自治决策围绕七个核心概念，三端共用同一语义。

### 2.1 Signal（信号）

自治系统的输入事件。`source` / `kind` / `severity` / `detail` / `ts` / `payload`。

**信号来源**：
- 外部 ingest：`controller.ingest(signal)`（如 main.ts 在 backend exit 时调用）
- 内部派生：`deriveSignalsFromTruth(truth)` 从 RuntimeTruthSnapshot 派生

**核心 kind 枚举**（与 `rca_rules.py` / `rca-rules.ts` 同源）：
- `backend_exit` / `disk_full` / `disk_low` / `db_corrupt` / `network_down`
- `config_fingerprint_changed` / `port_in_use`
- `LLM_RUNTIME_UNAVAILABLE` / `NEURO_BUS_CIRCUIT_OPEN` / `NEURO_BUS_DLQ_FULL` / `NEURO_BUS_RATE_LIMIT`
- `ota_install_failed`
- 服务器端：`health_down` / `manifest_drift` / `compose_unhealthy`
- CI 端：`ci_failed` / `pr_opened`

### 2.2 Diagnosis（诊断）

根因分析输出。`root_cause` / `confidence` / `detail` / `evidence`。

由 `diagnoseRootCause(signals)` 纯函数生成，取最近信号作为主因。

### 2.3 Action（动作）

Policy 决策的输出，由 Adapter 执行。`type` / `params` / `idempotency_key` / `max_attempts` / `risk`。

**动作类型枚举**：
- 桌面：`restart_backend` / `rollback_version` / `clear_cache` / `repair_config` / `escalate` / `noop`
- 服务器：`restart_service` / `rollback_to_last_tarball` / `freeze_manifest` / `clear_logs` / `escalate`
- CI：`create_pr` / `comment_pr` / `escalate`

**风险分级**：
- `low`：自动执行（如 `clear_cache`）
- `medium`：自动执行 + cooldown 5min（如 `repair_config`）
- `high`：默认 escalate（如 `rollback_version` / `rollback_to_last_tarball`）

### 2.4 Policy（策略）

信号 → 决策的纯函数。`id` / `matches` / `gate` / `plan(signals)`。

**纯函数约束**：禁止调用 `Date.now()`，时间窗口用 signals 自身 `ts`（取最新信号 ts 作为"现在"）。

**现有 policy 清单**：

| 端 | Policy ID | 触发 kind | 决策动作 |
|---|---|---|---|
| 桌面 | `backend-crash` | `backend_exit` | 5min 内 ≥3 次 → `rollback_version` |
| 桌面 | `degraded-remediation` | `disk_full` / `config_fingerprint_changed` / `port_in_use` / `LLM_*` / `NEURO_BUS_*` / `disk_low` / `db_corrupt` / `network_down` | 按 kind 映射：low→自动修复，high→escalate |
| 桌面 | `update-rollback` | `ota_install_failed` | 回滚到上一版本 |
| 服务器 | `health_down` | `health_down` | `restart_service`（max_attempts=2） |
| 服务器 | `manifest_drift` | `manifest_drift` | `freeze_manifest`（防 cron 反复重试） |
| 服务器 | `disk_full` | `disk_full` | `clear_logs` |
| 服务器 | `compose_unhealthy` | `compose_unhealthy` | `restart_service` |

### 2.5 AutonomyAdapter（适配器接口）

层级无关的执行接口。各端实现：

| 端 | 实现 | 文件 |
|---|---|---|
| 桌面 | `DesktopAdapter` | `FHD/desktop/autonomy/desktop-adapter.ts` |
| 服务器 | `CvmAutonomyAdapter` | `FHD/scripts/autonomy/cvm_adapter.py` |
| CI | （无独立 adapter，直接执行） | `FHD/scripts/ci/ai_self_heal.py` |

**接口方法**：
- `collectTruth()` → 采集运行时现实快照
- `subscribeSignals(emit)` → 订阅外部信号
- `executeAction(action)` → 执行动作
- `audit(entry)` → 写审计（同步、不抛错）
- `getRemoteState?()` → **Phase 4 新增**，跨端门禁查询其他端状态（可选，未实现时 fail-closed）

### 2.6 RuntimeTruthSnapshot（现实快照）

决策时的现实快照，ImpactPredictor 的输入。

**核心字段**：
- `backend`：进程信息（pid / running / startedAt）
- `port_in_use` / `disk_usage_percent` / `disk_free_mb`
- `config_fingerprint_changed` / `pending_rollback_marker`
- `last_backup_ts` / `app_version` / `build_sha` / `restart_count`
- `db_integrity` / `last_network_ok_ts`
- `neurobus?`：NeuroBus 状态
- `extra?`：服务器/CI 端扩展字段

### 2.7 AuditEntry（审计条目）

所有动作必须记录，是唯一事后真相。

**字段**：`ts` / `source_signal` / `diagnosis` / `action` / `result` / `truth_snapshot?`

**存储位置**（三端默认路径）：
- 桌面：`%APPDATA%/XCAGI/audit/autonomy-audit.jsonl`（macOS: `~/Library/Application Support/XCAGI/audit/`）
- 服务器：`/var/log/xcagi/autonomy-audit.jsonl`
- CI：GitHub Actions logs（无独立文件，通过 workflow run 查看）

---

## 3. 决策流程

```
┌──────────────────────────────────────────────────────────────────────┐
│  1. 触发                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ 外部 ingest  │  │ tick() 轮询  │  │ workflow_run │               │
│  │ (main.ts)    │  │ (5s/10min)   │  │ (CI 触发)    │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
└─────────┼─────────────────┼─────────────────┼────────────────────────┘
          ▼                 ▼                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2. 采集 truth（RuntimeTruthSnapshot）                                │
│  - 桌面：backend.pid / port / disk / config hash / db integrity       │
│  - 服务器：health endpoint / disk / manifest hash / compose status    │
│  - CI：失败日志 / diff / 仓库状态                                     │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  3. 派生信号（deriveSignalsFromTruth）                                │
│  - disk_usage > 95% → disk_full                                       │
│  - disk_free < 500MB → disk_low                                       │
│  - db_integrity = 'fail' → db_corrupt                                 │
│  - now - last_network_ok_ts > 5min → network_down                     │
│  - config_fingerprint_changed = true → config_fingerprint_changed     │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  4. Policy.plan(signals) → Plan(diagnosis, actions)                  │
│  - 按 policy.matches 过滤信号                                          │
│  - 纯函数决策（禁止 Date.now()）                                       │
│  - 按 kind 去重，每 kind 出一个动作                                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  5. tryExecute(action, diagnosis, sourceSignal)                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ a. max_attempts 守护：耗尽 → escalate                            │  │
│  │ b. cooldown 守护：5min 内跳过（静默）                            │  │
│  │ c. ImpactPredictor 预检：predict(action, truth)                  │  │
│  │    - allow=false → 写 audit + return                             │  │
│  │ d. CrossTierGate 跨端门禁（env 启用）：                          │  │
│  │    - getRemoteState() 查询失败 → fail-closed                     │  │
│  │    - checkBeforeAction() → allow=false → 写 audit + return       │  │
│  │ e. 执行 adapter.executeAction(action)                            │  │
│  │ f. 写 audit（含 result + truth_snapshot）                        │  │
│  │ g. 失败且耗尽 attempts → escalate                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. 三端实现位置

### 4.1 桌面端（Electron）

| 文件 | 职责 |
|---|---|
| `FHD/desktop/autonomy/types.ts` | 七元契约 TypeScript 定义 |
| `FHD/desktop/autonomy/controller.ts` | AutonomyController 调度器 |
| `FHD/desktop/autonomy/runtime-truth.ts` | truth 派生信号 |
| `FHD/desktop/autonomy/impact-predictor.ts` | 6 action 预检规则 |
| `FHD/desktop/autonomy/cross-tier-gate.ts` | 跨端门禁纯函数 |
| `FHD/desktop/autonomy/rca-rules.ts` | RCA 映射 |
| `FHD/desktop/autonomy/policies/backend-crash.policy.ts` | backend 崩溃回滚 |
| `FHD/desktop/autonomy/policies/degraded-remediation.policy.ts` | 降级状态修复 |
| `FHD/desktop/autonomy/policies/update-rollback.policy.ts` | OTA 失败回滚 |
| `FHD/desktop/autonomy/desktop-adapter.ts` | DesktopAdapter 实现 |
| `FHD/desktop/autonomy/__tests__/*.test.ts` | 6 个测试文件，248 pass |

**集成位置**：`FHD/desktop/main.ts` 在启动时 `controller.start()`，在 backend exit 时 `controller.ingest(signal)`。

### 4.2 服务器端（CVM）

| 文件 | 职责 |
|---|---|
| `FHD/scripts/autonomy/types.py` | 七元契约 Python dataclass/TypedDict |
| `FHD/scripts/autonomy/rca_rules.py` | RCA 映射 |
| `FHD/scripts/autonomy/cvm_adapter.py` | CvmAutonomyAdapter（6 action 实现） |
| `FHD/scripts/autonomy/impact_predictor.py` | 6 action 预检规则 |
| `FHD/scripts/autonomy/cross_tier_gate.py` | 跨端门禁纯函数 |
| `FHD/scripts/autonomy/audit_query.py` | 三端 audit 查询 CLI |
| `FHD/scripts/autonomy/cvm_autonomy_watcher.py` | 主程序 + CLI 入口 |
| `FHD/scripts/autonomy/policies/*.py` | 4 个 policy |
| `FHD/tests/test_autonomy/*.py` | 7 个测试文件，132 pass |

**触发方式**：GitHub Actions cron `*/10 * * * *` SSH 到 CVM 触发 `cvm_autonomy_watcher.py`，非常驻进程。

### 4.3 CI 端（GitHub Actions）

| 文件 | 职责 |
|---|---|
| `FHD/scripts/ci/ai_self_heal.py` | CI 失败自愈（745 行）：日志下载 → 错误提取 → 规则匹配 → LLM 兜底 → 创建 PR |
| `FHD/scripts/ci/ai_review.py` | PR review（496 行）：diff 解析 → 高危规则 → LLM 复核 → 行级评论 |
| `FHD/scripts/ci/requirements-*.txt` | 依赖 |
| `FHD/tests/test_ci/*.py` | 2 个测试文件，78 pass |
| `FHD/.github/workflows/ai-self-heal.yml` | workflow_run(failure) 触发 |
| `FHD/.github/workflows/ai-review.yml` | pull_request(opened/synchronize) 触发 |
| `FHD/.github/workflows/cvm-autonomy-watcher.yml` | cron `*/10 * * * *` + SSH 触发 |

---

## 5. 跨端门禁（CrossTierGate）

### 5.1 启用方式

```bash
# 桌面端（main.ts 启动时设置）
process.env.XCAGI_CROSS_TIER_GATE = '1'

# 服务器端（cvm_autonomy_watcher.py 启动时设置）
export XCAGI_CROSS_TIER_GATE=1

# CI（workflow env）
env:
  XCAGI_CROSS_TIER_GATE: '1'
```

**默认启用（opt-out）**：env 未设时门禁开启；`XCAGI_CROSS_TIER_GATE=0/false/no` 关闭。

### 5.2 fail-closed 原则

跨端查询失败时**阻断**动作，避免在未知跨端状态下误执行。

| 场景 | 行为 |
|---|---|
| env=0/false/no | 跳过门禁检查 |
| env 未设/1 + adapter 未实现 `getRemoteState` | `?.()` 返回 undefined → `?? null` → **fail-closed** |
| env 未设/1 + 查询抛错 | catch 写 audit + **fail-closed** |
| env 未设/1 + 查询返回 null | **fail-closed** |
| env 未设/1 + 查询返回 {} | allow=true（无规则命中） |
| env 未设/1 + 查询返回 frozen=true | **allow=false**（写 audit + return） |

### 5.3 三个跨端场景

| 场景 | 检查项 | 防止问题 |
|---|---|---|
| 桌面 `rollback_version` | `server_manifest_frozen` | 桌面回滚到服务器已冻结的版本，导致 cron 反复应用错误制品 |
| 服务器 `rollback_to_last_tarball` | `desktop_pending_rollback_marker` | 服务器与桌面同时回滚，嵌套回滚导致数据丢失 |
| CI `cvm-push-release` | `server_manifest_frozen` | CI 推送覆盖运维手动冻结的 manifest |

### 5.4 实现位置

- 桌面端：`FHD/desktop/autonomy/cross-tier-gate.ts`（与 Python 版本对称）
- 服务器端：`FHD/scripts/autonomy/cross_tier_gate.py`
- CI：CI 端直接调用 Python 版本

---

## 6. Audit 查询 CLI

### 6.1 用法

```bash
cd FHD
python scripts/autonomy/audit_query.py \
  --source {desktop|server|ci} \
  --since 24h \
  --limit 100 \
  [--filter 'action.type=rollback_version'] \
  [--filter 'result.ok=false'] \
  [--path /custom/audit.jsonl]
```

### 6.2 参数

| 参数 | 说明 | 示例 |
|---|---|---|
| `--source` | 审计来源（必填） | `desktop` / `server` / `ci` |
| `--since` | 时间窗口（必填） | `30m` / `24h` / `7d` / `2026-07-01T00:00:00` |
| `--limit` | 最大返回条数，默认 100 | `1000` |
| `--filter` | 过滤表达式（可多次） | `action.type=rollback_version` |
| `--path` | 自定义审计文件路径 | `/var/log/xcagi/audit.jsonl` |

### 6.3 默认路径

```python
default_audit_path('desktop')  # %APPDATA%/XCAGI/audit/autonomy-audit.jsonl
default_audit_path('server')   # /var/log/xcagi/autonomy-audit.jsonl
default_audit_path('ci')       # ./autonomy-audit.jsonl（CI 临时文件）
```

### 6.4 典型查询

```bash
# 查桌面端最近 24h 的所有 rollback 动作
python scripts/autonomy/audit_query.py --source desktop --since 24h \
  --filter 'action.type=rollback_version'

# 查服务器端最近 1h 失败的动作
python scripts/autonomy/audit_query.py --source server --since 1h \
  --filter 'result.ok=false'

# 查 CI 端最近 7 天的所有 escalate
python scripts/autonomy/audit_query.py --source ci --since 7d \
  --filter 'action.type=escalate'
```

---

## 7. 人工介入触发条件

以下场景自动触发 `escalate` 动作，进入人工处理流程：

| 触发条件 | 来源 | 处理方式 |
|---|---|---|
| `max_attempts` 耗尽 | 桌面 controller / 服务器 watcher | 写 audit + 创建 GitHub Issue（CI 端） |
| `high` 风险动作 | 任何 policy | 直接 escalate，不自动执行 |
| CrossTierGate deny | 桌面 controller / 服务器 watcher | 写 audit + return，等待运维介入 |
| ImpactPredictor deny | 桌面 controller | 写 audit + return |
| CI 自愈失败 | ai-self-heal | PR 标 `needs-human` 标签 |
| CI review confirmed-high | ai-review | PR review 阻断合并 |
| CVM 部署异常 | cvm-autonomy-watcher | 创建根因 issue（只诊断不改码；token=`CVM_INCIDENT_PAT` 或缺省 `github.token`） |

### 7.1 人工介入入口

- **GitHub Issues**：CI 自愈失败的 PR 会自动评论 + 标 `needs-human`
- **Audit 文件**：`audit_query.py` CLI 查询历史动作
- **服务器 SSH**：`ssh root@119.27.178.147` 登录后查看 `/var/log/xcagi/autonomy-audit.jsonl`

### 7.2 解除 manifest 冻结

当 CrossTierGate 因 `server_manifest_frozen=true` 拦截动作时，运维需确认后解除冻结：

```bash
ssh root@119.27.178.147
cd /var/www/update/releases/stable/server
mv fhd-manifest.json.hold fhd-manifest.json
# 验证
curl -sf https://xiu-ci.com/fhd-api/api/health
```

---

## 8. 故障演练剧本

### 8.1 桌面端：backend 5min 内 3 次崩溃 → 自动 rollback_version

**目的**：验证 `backend-crash.policy.ts` 在 5 分钟窗口内 3 次 `backend_exit` 信号触发回滚。

**步骤**：
```bash
cd FHD/desktop
XCAGI_DESKTOP_TEST=1 npx vitest run autonomy/__tests__/policies.test.ts -t "backend-crash"
```

**预期**：
- 1-2 次 backend_exit → 无动作
- 3 次 backend_exit（5min 内）→ `rollback_version` 动作产出
- ImpactPredictor 检查 `pending_rollback_marker=false` + `last_backup_ts` 在 7 天内 → allow
- CrossTierGate（若启用）检查 `server_manifest_frozen=false` → allow
- 执行回滚 + 写 audit

### 8.2 服务器端：/api/health 持续 503 → restart_service → 失败 → escalate

**目的**：验证 `health_down_policy.py` 触发 `restart_service`，失败后 escalate。

**步骤**：
```bash
cd FHD
python -m pytest tests/test_autonomy/test_policies.py::TestHealthDownPolicy -v
python -m pytest tests/test_autonomy/test_cvm_watcher.py -v
```

**预期**：
- health_down 信号 → `restart_service` 动作（max_attempts=2）
- 第 1 次失败 → cooldown 5min
- 第 2 次失败 → escalate（写 audit + 创建 issue）

### 8.3 CI 端：fhd-ci-cd 失败 → ai-self-heal 创建修复 PR

**目的**：验证 `ai_self_heal.py` 在 CI 失败时下载日志、匹配规则、创建 PR。

**步骤**：
```bash
cd FHD
python -m pytest tests/test_ci/test_ai_self_heal.py -v
```

**预期**：
- workflow_run(failure) 触发 ai-self-heal workflow
- 下载失败 job 日志
- 规则匹配（80% 覆盖常见失败）
- LLM 兜底（30s 超时 fail-open）
- 同指纹 24h 去重
- autonomy/ 分支不递归（避免自愈自愈）
- 创建修复 PR + 标 `needs-human`（业务码修复待人工合并）

### 8.4 跨端门禁：桌面 rollback 时服务器 manifest 已冻结

**目的**：验证 CrossTierGate 在桌面端 rollback_version 时检查服务器 manifest 状态。

**步骤**：
```bash
cd FHD/desktop
XCAGI_DESKTOP_TEST=1 XCAGI_CROSS_TIER_GATE=1 npx vitest run autonomy/__tests__/controller.test.ts -t "crossTierGate"
```

**预期**：
- env XCAGI_CROSS_TIER_GATE=1 启用
- adapter.getRemoteState() 返回 `{server_manifest_frozen: true}`
- checkBeforeAction('desktop', 'rollback_version', ...) 返回 `allow=false`
- 写 audit + return，不执行 rollback
- 运维收到 escalate 通知，解除 manifest 冻结后重试

---

## 9. 关键约束（铁律）

1. **Policy 纯函数**：禁止 `Date.now()`，时间窗口用 signals 自身 `ts`
2. **ImpactPredictor 拦截不阻断**：误判仅记录，不抛错
3. **CrossTierGate fail-closed**：查询失败（`remote_state=null`）阻断动作并写 audit，避免盲操作
4. **CrossTierGate 默认启用**：env `XCAGI_CROSS_TIER_GATE=0/false/no` 关闭（opt-out）
5. **同指纹 24h 去重**：CI 自愈避免相同错误反复创建 PR
6. **autonomy/ 分支不递归**：ai-self-heal 不处理 autonomy/* 分支失败
7. **LLM fail-open**：30s 超时不阻断主流程
8. **confirmed-high 才阻断**：ai-review 仅 LLM 高置信度高危才阻断合并
9. **manifest 冻结立即生效**：`.hold` 重命名防止 cron 反复重试错误制品
10. **所有动作必审计**：AuditEntry 是唯一事后真相，三端共用语义

---

## 10. 变更维护

### 10.1 新增 Policy

1. 在对应端的 `policies/` 目录创建 `xxx.policy.{ts,py}`
2. 实现 `Policy` 接口（id / matches / gate / plan）
3. 在 controller/watcher 启动时注册
4. 添加单元测试（happy path + 边界 + 异常）
5. 更新本手册第 2.4 节 policy 清单

### 10.2 新增 Action 类型

1. 在 `types.{ts,py}` 的 `ActionType` 枚举添加
2. 在 `AutonomyAdapter.executeAction` 实现该动作
3. 在 `ImpactPredictor.predict` 添加预检规则（如适用）
4. 在 `CrossTierGate.checkBeforeAction` 添加跨端场景（如适用）
5. 添加单元测试
6. 更新本手册第 2.3 节动作类型清单

### 10.3 新增跨端门禁场景

1. 在 `cross_tier_gate.{ts,py}` 的 `checkBeforeAction` 添加新场景
2. 同步三端实现（桌面 TS + 服务器 Python）
3. 添加单元测试
4. 更新本手册第 5.3 节场景表

---

## 11. 相关文档

- [CI_SSOT.md](./CI_SSOT.md) — CI/CD 流水线文档，含"自治闭环"章节
- [cicd-e2e-prompt.md](../.trae/rules/cicd-e2e-prompt.md) — AI 决策矩阵
- 代码：
  - 桌面：`FHD/desktop/autonomy/`
  - 服务器：`FHD/scripts/autonomy/`
  - CI：`FHD/scripts/ci/`
  - 测试：`FHD/desktop/autonomy/__tests__/` / `FHD/tests/test_autonomy/` / `FHD/tests/test_ci/`
