# 演化自识缺口自实现自发布闭环设计

**日期**：2026-07-20
**作者**：AI 辅助设计 + 用户决策
**状态**：待审阅
**影响范围**：
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/`（扩展 4 个文件 + 新增 3 个文件）
- `.github/workflows/`（新增 `ai-issue-implement.yml`）
- `FHD/scripts/dev/`（新增 `audit_evolution.py`）

---

## 1. 背景与目标

### 1.1 现状评估

XCMAX 的"演化自识缺口自实现自发布"闭环度仅 5%，是七大目标态（founder / system / client / code / failure / evolution / alignment）中最薄弱的环节。

| 已实现 | 真实状态 |
|---|---|
| `fhd-legacy-usage-weekly.yml` 每周扫描遗留代码 | 只写 `legacy_usage_report.json`，**不转 issue** |
| `fhd-intent-benchmark.yml` 每周扫描意图准确率 | 只写 `intent_benchmark_report.json`，**不转 issue** |
| `fhd-slo-metrics-collect.yml` 每日采集 SLO | 只写 `slo_metrics.json`，**不转 issue** |
| `MODstore` 有 `mod_sdk` 上架 SDK | 上架流程存在，**未接通到自动上架** |
| `auto_approve_policy.py` 自动审批策略 | 已存在且默认开启，**未应用至 employee_pack 上架** |
| `evolution_signal_collector.py` 演化信号采集 | 已存在但仅"采集"，**未聚合 + 未触发后续动作** |
| `self_maintenance_loop_runner.py` 自维护外循环 | 已存在但只做"代码审查→缺口识别→变更请求→PR"，**未接通开 issue 与上架** |
| `ai-issue-implement.yml` 自动实现新功能 | **完全不存在**（仓库+文档全搜 0 命中，承诺与代码漂移） |

### 1.2 核心缺口

5 个断点 + 1 个缺失 workflow：

1. 扫描类 workflow 输出不转 issue（缺桥接脚本）
2. `ai-issue-implement.yml` workflow 完全不存在
3. PR 合并后无员工包构建脚本
4. 员工包上架未走 `auto_approve_policy` 审核
5. 演化决策无独立审计 ledger
6. 三重硬门禁未在自动实现链路中校验

### 1.3 闭环目标

构建"缺口识别 → 自动开 issue → 自动实现 → 自动上架 → owner 事后审计"完整闭环，达到：

- **完全自动**：owner 只做事后审计，全链路无人干预
- **范围中等**：≤5 文件的全自动实现允许做"代码质量收尾 + 新 AI 员工自动上架"
- **决策稳健**：规则预筛 + LLM 提议 + 三重硬门禁
- **失败自愈**：失败重试 3 次（调整 prompt）后才转人工
- **可审计**：`evolution_decisions.jsonl` 作为 owner 唯一审计源

### 1.4 非目标（YAGNI）

- 不包含客户付费/订阅/合同逻辑（归计费域）
- 不包含多环境灰度上架（先做单一 stable 通道）
- 不包含自动回滚上架（依赖现有 `fhd-apply-release.sh` 回滚机制）
- 不包含变异测试（演化决策不需要，单独项目）
- 不包含"新 API 路由 / 新视图 / 新服务"自动实现（>5 文件风险高，归人工）

---

## 2. 现状盘点

### 2.1 已存在零件

| 文件 | 现有职责 | 复用方式 |
|---|---|---|
| `evolution_signal_collector.py` | 演化信号采集 | 扩展为聚合器，聚合 3 个扫描 workflow 的 JSON 报告 |
| `auto_approve_policy.py` | 变更请求风险分级 + 自动审批 | 扩展应用到 employee_pack 审核 |
| `production_line_orchestrator.py` | 制作线 P1-P10 + 运营线 O1-O10 编排 | 仅作为参考流程模型，不直接修改 |
| `self_maintenance_loop_runner.py` | 自维护外循环（代码审查→缺口→PR） | 仅作为信号源之一，不修改其内部逻辑 |
| `employee_autonomy_service.py` | 员工自治建议单 | 扩展为 LLM 提议器，输出 JSON Schema |
| `human_uncertainty_queue.py` | 人类不确定性队列 | 复用为"3 次重试失败后转人工"通道 |
| `arch_fitness.py` | 架构适配度校验 | 复用为三重硬门禁之一 |
| `duty_employee_registry.py` | 内部员工注册表 | 复用为员工包注册入口 |
| `catalog_data/packages.json` | 商店员工包注册表 | 上架目标位置 |
| `fhd-ai-self-heal-auto-merge.yml` | 自动合并 PR | 复用为 PR 合并通道 |
| `fhd-ai-review.yml` | AI 审 PR | 复用为 PR 审查通道 |

### 2.2 待新增零件

| 文件 | 职责 |
|---|---|
| `gap_to_issue.py` | 把聚合信号转 GitHub issue（打 `ai-implement` 标签） |
| `build_employee_pack.py` | PR 合并后构建员工包 + 注册 + 触发审核 |
| `audit_evolution.py` | owner 审计 ledger 查询脚本 |
| `ai-issue-implement.yml` | 自动实现新 workflow（监听 `ai-implement` 标签） |
| `evolution_decisions.jsonl` | 演化决策 ledger（append-only） |

---

## 3. 整体架构与数据流

### 3.1 端到端数据流

```
[扫描源]                          [信号聚合]                [规则预筛]
legacy-usage-weekly.yml       →                      →
intent-benchmark.yml          →   evolution_signal    阈值规则
slo-metrics-collect.yml       →   _collector.py       (代码里，可审计)
                                  (扩展为聚合器)
                                                          ↓ 通过阈值
                                  [LLM 提议器]           [三重硬门禁]
                                  employee_autonomy     1. arch_fitness
                                  _service.py           2. 足迹边界
                                  调用 LLM               3. 预算限制
                                  输出 JSON Schema
                                                          ↓ 全过
                                  [自动开 issue]
                                  gap_to_issue.py
                                  + ai-implement 标签
                                                          ↓
                                  [ai-issue-implement.yml] ← 新 workflow
                                  trigger: issue 打 ai-implement 标签
                                  steps:
                                    1. 读 issue body (含 LLM 提议 JSON)
                                    2. 调 LLM 实现 employee_pack (≤5 文件)
                                    3. 三重门禁校验
                                    4. 失败 → 重试 3 次（调整 prompt）
                                    5. 3 次都败 → issue comment + needs-human
                                    6. 成功 → 提 PR
                                                          ↓
                                  [ai-review] ← 已有
                                                          ↓
                                  [ai-self-heal-auto-merge] ← 已有
                                                          ↓
                                  [build_employee_pack.py] ← 新增
                                  PR 合并的 employee_pack 文件
                                  打包 + 注册到 catalog_data
                                                          ↓
                                  [auto_approve_policy.py] ← 已有，扩展
                                  风险分级 + ≤5 文件 + CI 必过 + 不触敏感路径
                                                          ↓ 通过
                                  catalog_data/packages.json + files/ 上架
                                  (员工可见 / 客户可订阅)
                                                          ↓
                                  evolution_decisions.jsonl ← 新 ledger
                                  每条记录全部决策上下文
```

### 3.2 5 个接通点 + 1 新 workflow + 1 新 ledger

| # | 类型 | 路径 | 动作 |
|---|------|------|------|
| 1 | 扩展已有 | `evolution_signal_collector.py` | 添加 `aggregate_signals()` 聚合 3 个扫描 workflow 的 JSON 报告 |
| 2 | 新增 | `gap_to_issue.py` | 调 `gh issue create --label ai-implement`，body 含 LLM 提议 JSON |
| 3 | 新增 | `.github/workflows/ai-issue-implement.yml` | 监听 ai-implement 标签，自动实现 + 重试 3 次 + 提 PR（**新 workflow**） |
| 4 | 新增 | `build_employee_pack.py` | PR 合并后构建 + 注册 + 上架 |
| 5 | 扩展已有 | `auto_approve_policy.py` | 把 HIGH_RISK_PATTERNS 应用到 employee_pack 审核 |
| 6 | 新增 | `data/evolution_decisions.jsonl` | 演化决策 ledger（**新 ledger，非接通点**） |

> 注：#1-#5 是接通点（把现有零件或新零件接入闭环）；#3 是 1 个新 workflow；#6 是 1 个新 ledger（owner 审计源）。

---

## 4. 核心组件设计

### 4.1 演化决策 ledger（`evolution_decisions.jsonl`）

**位置**：`成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl`

**格式**：append-only JSONL，每行一个事件

**Schema**：

```json
{
  "event_id": "uuid",
  "timestamp": "2026-07-20T10:30:00Z",
  "event_type": "signal_detected | proposal_generated | gate_passed | gate_failed | issue_opened | implement_started | implement_succeeded | implement_failed | pr_opened | pr_merged | pack_built | pack_approved | pack_listed | pack_rejected",
  "triggered_by": "intent_benchmark | slo_metrics | legacy_usage | manual",
  "signal_score": 0.85,
  "llm_proposal": {
    "proposal_id": "uuid",
    "department": "engineering|quality|ops|growth|support|security",
    "employee_pack_name": "intent-failure-triage-clerk",
    "estimated_files": 3,
    "estimated_tokens": 45000
  },
  "gate_results": {
    "arch_fitness": "pass|fail",
    "footprint": "pass|fail",
    "budget": "pass|fail"
  },
  "issue_url": "https://github.com/.../issues/123",
  "pr_url": "https://github.com/.../pull/456",
  "commit_sha": "abc1234",
  "pack_id": "intent-failure-triage-clerk@1.0.0",
  "approved_at": "2026-07-20T11:00:00Z",
  "cost_tokens": 42350,
  "retry_count": 0,
  "final_status": "pack_listed | needs_human | aborted",
  "owner_audit": {
    "audited": false,
    "audited_at": null,
    "verdict": null
  }
}
```

**审计入口**：`python FHD/scripts/dev/audit_evolution.py --since 7d`

### 4.2 LLM 提议 JSON Schema

`employee_autonomy_service.py` 调用 LLM 时，输出格式：

```json
{
  "proposal_id": "uuid",
  "triggered_by": "intent_benchmark | slo_metrics | legacy_usage",
  "signal_score": 0.85,
  "department": "engineering|quality|ops|growth|support|security",
  "employee_pack": {
    "name": "intent-failure-triage-clerk",
    "responsibility": "when intent accuracy < 80%, scan failed cases, cluster by failure pattern, propose prompt fixes",
    "prompt_template": "...",
    "skills": ["intent-benchmark", "failure-clustering"],
    "tools": ["read_file", "write_pr_comment"],
    "acceptance_criteria": ["recall >= 0.7 on test set", "<= 5 files touched"]
  },
  "estimated_files": 3,
  "estimated_tokens": 45000
}
```

**约束**：
- `estimated_files` 必须 ≤ 5（硬限制）
- `estimated_tokens` 必须 ≤ 100000（预算限制）
- `department` 必须是 SIX_LINE_DEPARTMENTS 之一
- `acceptance_criteria` 必须可机器验证

### 4.3 三重硬门禁具体规范

#### 门禁 1：架构适配度

- **复用**：`FHD/scripts/arch_fitness.py`
- **规则**：employee_pack 文件必须遵守 DDD 四层边界（domain / application / infrastructure / interfaces）
- **失败处理**：记录到 ledger `gate_results.arch_fitness = "fail"`，触发重试

#### 门禁 2：足迹边界

- **复用**：`auto_approve_policy.HIGH_RISK_PATTERNS`
- **规则**：employee_pack 不允许触碰：
  - `*.env` / `*.env.*`
  - `secrets/*`
  - `.github/workflows/*`
  - `nginx/*.conf` / `*/nginx.conf`
  - `requirements*.txt`
  - `Dockerfile*`
  - `docker-compose*.yml`
  - `modstore_server/models*.py`
  - `modstore_server/api/app_factory.py`
  - `*.pem` / `*.key` / `*.p12` / `*.pfx` / `*.db` / `*.sqlite` / `*.sqlite3`
- **失败处理**：记录到 ledger `gate_results.footprint = "fail"`，触发重试

#### 门禁 3：预算限制

- **新规则**：每次实现 token 预算上限 100K，PR review 时间预算上限 30 分钟
- **失败处理**：记录到 ledger `gate_results.budget = "fail"`，直接 fail 不重试（预算超限是设计错误，重试无意义）

### 4.4 ai-issue-implement.yml workflow 规范

**触发条件**：
- `issues` 事件 + label = `ai-implement`
- `workflow_dispatch` 手动触发（输入 issue_number）

**关键步骤**：

```yaml
name: AI Issue Implement
on:
  issues:
    types: [labeled]
  workflow_dispatch:
    inputs:
      issue_number:
        required: true

jobs:
  implement:
    if: contains(github.event.label.name, 'ai-implement')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Read issue body (parse LLM proposal JSON)
        run: python FHD/scripts/dev/read_issue_proposal.py ${{ github.event.issue.number }}
      - name: LLM implement employee_pack (≤5 files, 100K token budget)
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
        run: python FHD/scripts/dev/implement_employee_pack.py --proposal proposal.json
      - name: Run three hard gates
        run: |
          python FHD/scripts/arch_fitness.py
          python FHD/scripts/dev/check_footprint.py
          python FHD/scripts/dev/check_budget.py
      - name: Retry up to 3 times on failure (adjust prompt)
        run: python FHD/scripts/dev/retry_with_adjusted_prompt.py --max-retries 3
      - name: If 3 failures → comment on issue + add needs-human label
        if: failure()
        run: python FHD/scripts/dev/escalate_to_human.py
      - name: If success → create branch + commit + open PR
        run: python FHD/scripts/dev/open_pr_for_employee_pack.py
      - name: Wait for ai-review + ai-self-heal-auto-merge
        run: python FHD/scripts/dev/wait_for_pr_merge.py
      - name: After merge → build_employee_pack.py
        run: python 成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py --commit ${{ github.sha }}
      - name: Auto approve via auto_approve_policy.py
        run: python 成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py --pack-id $PACK_ID
      - name: Append to evolution_decisions.jsonl
        run: python FHD/scripts/dev/append_evolution_event.py --event pack_listed
```

### 4.5 build_employee_pack.py 规范

**输入**：合并到 main 的 PR commit

**步骤**：
1. 从 commit diff 提取 employee_pack 文件
2. 校验 employee_pack schema（含 `name` / `prompt_template` / `skills` / `tools` / `acceptance_criteria`）
3. 复制到 `catalog_data/files/<pack_id>/`
4. 注册到 `catalog_data/packages.json`
5. 触发 `auto_approve_policy.evaluate(pack_id)`
6. 通过则上架；不通过则记录到 ledger 并触发人工审核

**输出**：`pack_id` + 上架时间戳 + 写入 ledger

### 4.6 gap_to_issue.py 规范

**输入**：聚合后的 evolution signals

**步骤**：
1. 读取 `evolution_signal_collector.aggregate_signals()` 输出
2. 对每个通过阈值的信号，调用 `employee_autonomy_service.propose_employee_pack(signal)`
3. 对每个 LLM 提议，运行三重硬门禁预校验
4. 全过的提议 → 调 `gh issue create --label ai-implement --body $LLM_PROPOSAL_JSON`
5. 写入 ledger `event_type = "issue_opened"`

### 4.7 audit_evolution.py 规范

**位置**：`FHD/scripts/dev/audit_evolution.py`

**用法**：
- `python audit_evolution.py --since 7d`：查最近 7 天所有事件
- `python audit_evolution.py --event pack_listed`：查所有上架事件
- `python audit_evolution.py --status needs_human`：查所有需人工干预的事件
- `python audit_evolution.py --mark-audited <event_id> --verdict approved`：标记已审计

**输出**：表格形式，包含 timestamp / event_type / pack_id / cost / status

---

## 5. 失败回退与重试策略

### 5.1 重试机制

当 LLM 实现失败时（任一门禁失败）：

| 重试次数 | 调整 prompt | 等待时间 |
|---|---|---|
| 1 | 在 prompt 末尾追加 "上一次失败原因：{failure_reason}，请避免" | 0 |
| 2 | 在 prompt 末尾追加 "已失败 2 次，请简化设计，文件数 ≤ 3" | 0 |
| 3 | 在 prompt 末尾追加 "已失败 3 次，请最小化实现，只做最核心 1 个文件" | 0 |

3 次都失败 → 转 `needs-human`：
1. 在 issue 上 comment 失败原因 + 3 次重试日志
2. 打 `needs-human` 标签
3. 写入 ledger `event_type = "implement_failed"`, `final_status = "needs_human"`

### 5.2 熔断机制

- **连续 5 次上架失败** → 暂停 `ai-issue-implement.yml` 24 小时
- **每天最多新增 3 个 AI 员工** → 防止 LLM 滥发
- **每周最多消耗 500K tokens** → 防止预算失控

### 5.3 owner veto 通道

- 任何时候 owner 都可以打 `.hold` 到 employee_pack manifest，强制冻结（与现有 manifest 冻结机制一致）
- owner 可以 `python audit_evolution.py --mark-audited <event_id> --verdict rejected` 否决已上架的员工包，触发下架流程

---

## 6. 测试策略

### 6.1 单元测试

每个接通点必须有单元测试：

| 模块 | 测试文件 | 关键场景 |
|---|---|---|
| `evolution_signal_collector.aggregate_signals()` | `test_evolution_signal_aggregator.py` | 3 个 JSON 报告聚合 + 阈值过滤 + 空输入 |
| `gap_to_issue.py` | `test_gap_to_issue.py` | 正常开 issue + 重复信号去重 + GitHub API 失败 |
| `implement_employee_pack.py` | `test_implement_employee_pack.py` | LLM 失败 + 5 文件超限 + token 超限 |
| `build_employee_pack.py` | `test_build_employee_pack.py` | schema 校验 + 重复 pack_id + 注册冲突 |
| `auto_approve_policy.evaluate_employee_pack()` | `test_auto_approve_employee_pack.py` | 高风险路径 + CI 失败 + ≤5 文件通过 |
| `append_evolution_event.py` | `test_append_evolution_event.py` | append-only + JSON 合法 + 并发写 |
| `audit_evolution.py` | `test_audit_evolution.py` | 时间过滤 + 状态过滤 + 标记审计 |

### 6.2 集成测试

`test_evolution_e2e.py`：用 mock LLM 跑通端到端流程

- 扫描信号（mock JSON）→ 聚合 → LLM 提议（mock）→ 三重门禁 → 开 issue（mock GitHub API）→ 实现（mock）→ PR（mock）→ 合并 → 构建员工包 → 审核 → 上架 → ledger 写入

### 6.3 验收测试

`test_evolution_acceptance.py`：真实场景验证

- 故意制造 intent_benchmark 低于 80% 的信号 → 触发完整闭环 → 验证员工包真的上架到 catalog_data/packages.json

---

## 7. 验收标准

### 7.1 闭环度验收

- [ ] 扫描 workflow 输出能自动转 issue
- [ ] `ai-issue-implement.yml` 在打 `ai-implement` 标签后自动触发
- [ ] LLM 实现严格遵守 ≤5 文件限制
- [ ] 三重硬门禁每次都校验且结果记入 ledger
- [ ] PR 合并后员工包自动构建并注册到 catalog_data
- [ ] `auto_approve_policy.py` 自动审核 employee_pack
- [ ] 上架成功后 ledger 写入 `pack_listed` 事件
- [ ] owner 能用 `audit_evolution.py` 查询所有演化决策

### 7.2 失败回退验收

- [ ] 单次失败触发重试，最多 3 次
- [ ] 3 次失败后 issue 自动 comment + 打 `needs-human` 标签
- [ ] 连续 5 次失败触发 24 小时熔断
- [ ] 每天上限 3 个员工包防止滥发

### 7.3 安全验收

- [ ] employee_pack 永远不触碰 HIGH_RISK_PATTERNS
- [ ] GitHub token 权限最小（只写 issue + PR，不写 release）
- [ ] LLM_API_KEY 不出现在 ledger 中
- [ ] owner veto 通道可用

### 7.4 覆盖率验收

按 `test-coverage-90-prompt.md` 规范：

- 新增模块单元测试覆盖率 ≥ 90% 行 / 85% 分支
- 集成测试覆盖端到端主路径
- 无 `pragma: no cover` 滥用
- 所有测试可独立运行，无外部依赖（mock GitHub API + mock LLM）

---

## 8. 工作量预估

| 任务 | 预估 |
|---|---|
| 接通点 1：扩展 `evolution_signal_collector.aggregate_signals()` | 2 天 |
| 接通点 2：`gap_to_issue.py` + GitHub Action token 配置 | 1 天 |
| 接通点 3：`ai-issue-implement.yml`（含重试 3 次、三重门禁、子脚本） | 4 天 |
| 接通点 4：`build_employee_pack.py` + catalog_data 注册 | 3 天 |
| 接通点 5：扩展 `auto_approve_policy` 到 employee_pack | 2 天 |
| `evolution_decisions.jsonl` + `audit_evolution.py` | 2 天 |
| 单元测试（覆盖每个接通点） | 4 天 |
| 集成测试 + E2E 验证 | 2 天 |
| **合计** | **约 3 周** |

修正原因：用户原估 6-8 周按"从零造"算，但实际 5 个零件已存在（`evolution_signal_collector` / `auto_approve_policy` / `production_line_orchestrator` / `self_maintenance_loop_runner` / `human_uncertainty_queue`），真正缺的只是 5 个接通点 + 1 个新 workflow。

---

## 9. 风险与缓解

| 风险 | 严重度 | 缓解策略 |
|---|---|---|
| LLM 滥发员工包 | 高 | 每天上限 3 个 + 每周 token 上限 500K |
| LLM 提议设计错误 | 中 | 三重硬门禁 + 3 次重试 + needs-human 兜底 |
| GitHub API 限流 | 中 | gap_to_issue.py 加随机延迟 + 重试退避 |
| employee_pack schema 漂移 | 中 | 强制 JSON Schema 校验 + 单元测试覆盖 |
| owner 长期不审计 | 低 | `audit_evolution.py --since 30d --status pack_listed` 默认每周自动跑（可加到 cron workflow） |
| LLM_API_KEY 泄露 | 高 | 用 GitHub Secrets + 不写入 ledger |
| 员工包上架后客户订阅异常 | 中 | 复用现有 `fhd-apply-release.sh` 自动回滚 + manifest `.hold` 冻结 |

---

## 10. 后续演进

闭环跑通后，可演进方向：

1. **宽范围自动实现**：放开到"新 API 路由 / 新视图 / 新服务"（>5 文件）
2. **多环境灰度上架**：员工包先上架 staging，再灰度到 production
3. **客户反馈闭环**：客户工单自动转缺口信号，进入演化闭环
4. **演化决策可视化**：基于 `evolution_decisions.jsonl` 生成演化图谱 dashboard
5. **变异测试**：对 LLM 实现的代码做变异测试，验证测试质量

这些都不在本次设计范围内，作为后续 Roadmap。

---

## 附录 A：相关文件清单

### A.1 已存在（扩展）

- `成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_signal_collector.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_autonomy_service.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/human_uncertainty_queue.py`
- `FHD/scripts/arch_fitness.py`

### A.2 新增

- `成都修茈科技有限公司/MODstore_deploy/modstore_server/gap_to_issue.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl`
- `FHD/scripts/dev/audit_evolution.py`
- `FHD/scripts/dev/read_issue_proposal.py`
- `FHD/scripts/dev/implement_employee_pack.py`
- `FHD/scripts/dev/check_footprint.py`
- `FHD/scripts/dev/check_budget.py`
- `FHD/scripts/dev/retry_with_adjusted_prompt.py`
- `FHD/scripts/dev/escalate_to_human.py`
- `FHD/scripts/dev/open_pr_for_employee_pack.py`
- `FHD/scripts/dev/wait_for_pr_merge.py`
- `FHD/scripts/dev/append_evolution_event.py`
- `.github/workflows/ai-issue-implement.yml`

### A.3 测试文件

- `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_signal_aggregator.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_gap_to_issue.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_implement_employee_pack.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_build_employee_pack.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_employee_pack.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_append_evolution_event.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_audit_evolution.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_e2e.py`
- `成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_acceptance.py`

---

## 附录 B：Metric-Search Bridge（WeCo/AIDE 思想吸收）

**日期**：2026-07-29  
**状态**：P0/P1 已落地（引擎 + ledger 桥）；实战 heldout 仍为 partial

### B.1 目标

把「提案 → 跑可解析 eval → 留优 → 树扩展」挂进演化轨，而不改运维自治（CVM watcher / self_maintenance_loop_runner）。

### B.2 Retort 引擎

- 模块：`packages/retort_engine/retort_engine/metric_search.py`
- CLI：`retort metric-search --project ... --eval-command ... --metric ... --max-nodes 8 --json`
- 策略：best-first，`beam=2`，硬预算 `max_nodes`
- 铁律：metric 必须从 eval stdout/stderr 用 regex 解析数字；解析失败 = trial failed

### B.3 Ledger 编排

- `propose-pack`：`validate_eval_spec`；缺 eval 写 `gate_failed`，不开 issue
- `implement-pack`：`EVOLUTION_IMPLEMENT_MODE=retort-metric-search` 调 Retort；事件 `metric_search_started` / `metric_search_finished`
- `collect-signals`：最近 metric-search `best_score` 低于 `RETORT_METRIC_THRESHOLD`（默认 0.8）时写 `signal_source=retort_metric`

### B.4 Eval 契约形状

```json
{
  "metric_name": "recall",
  "eval_command": "python3 -c \"print('recall: 0.75')\"",
  "higher_is_better": true
}
```

可放在 `proposal.eval_spec`、`employee_pack.eval`，或 `acceptance_criteria` 中的 dict 项。

### B.5 非目标

- 不触发 restart/freeze 等运维 Action
- V1 无 mid-run steerable UI
- 单 trial 仍遵守 ≤5 文件 / ≤100K tokens 足迹
