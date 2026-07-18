# AI self-heal 修复 PR 分级合并 SLA 策略

> **背景**：[ai-self-heal.py](file:///Users/a4243342/Desktop/XCMAX/FHD/scripts/ci/ai_self_heal.py) 当前所有 PR 一律 `needs-human` 不自动合并。结果：低风险修复（lint/format）堆积过期，业务码修复无人 review，自治系统反成噪音。
> **目标**：按风险等级分级 SLA，低风险 auto-merge，高风险强制人工，全风险兜底 stale 关闭。
> **铁律**：风险分级由规则匹配阶段决定，**不由 LLM 决定**（防止 LLM 自评风险失控）。

## 一、风险等级分类（与 match_rules 对齐）

| 等级 | 错误码 | 修复性质 | 当前 needs_human | SLA 策略 |
|------|--------|---------|-----------------|---------|
| **R0 极低风险** | ruff F401/F811（未用 import）、E501（超长行） | 机械删除/截断 | False | **24h 自动合并** |
| **R1 低风险** | ruff F841（未用局部变量） | 可能误删 | True（当前）→ **改 False + 二次校验** | **72h 无 review 自动合并** |
| **R2 中风险** | ruff 其他（I001/W291/W293）、mypy 简单类型错误 | 影响代码语义 | True | **7 天 stale 提醒 / 14 天自动关闭** |
| **R3 高风险** | bandit 全部、pytest 失败、LLM 兜底修复 | 安全/业务逻辑 | True | **永不自动合并 + 7 天 stale 提醒 / 30 天自动关闭** |

## 二、SLA 决策矩阵

```
                          ┌─────────────────┐
                          │ match_rules 分级 │
                          └────────┬────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
        ┌──────────┐         ┌──────────┐         ┌──────────┐
        │ R0/R1    │         │ R2       │         │ R3       │
        │ auto-merge│         │ stale→close│       │ needs-human│
        │ 候选     │         │          │         │ 永不合    │
        └────┬─────┘         └────┬─────┘         └────┬─────┘
             │                    │                    │
             ▼                    ▼                    ▼
       ┌──────────┐         ┌──────────┐         ┌──────────┐
       │二次校验：│         │ 7d 评论  │         │ 永不自动 │
       │ 1.CI 全绿│         │ 提醒     │         │ 合并     │
       │ 2.覆盖率 │         │ 14d 关闭 │         │ 7d 提醒  │
       │ 不回退   │         │ +指纹记录│         │ 30d 关闭 │
       │ 3.PR 体量│         │          │         │ +指纹记录│
       │ ≤ 3 文件 │         │          │         │          │
       └────┬─────┘         └──────────┘         └──────────┘
            │
       ┌────▼─────┐
       │24h 后    │
       │auto-merge│
       │(R0)      │
       │72h 后    │
       │auto-merge│
       │(R1)      │
       └──────────┘
```

## 三、二次校验守卫（R0/R1 auto-merge 前置条件）

`ai-self-heal-auto-merge.yml` 在每个 R0/R1 PR 创建 24h/72h 后触发：

| 守卫 | 判定 | 不通过则 |
|------|------|---------|
| 1. CI 状态 | 该 PR 分支最新 commit 全部 CI 绿 | 升级 R2，禁止自动合并 |
| 2. 覆盖率棘轮 | 后端行/分支、前端 lines/branches 不回退 | 升级 R2 |
| 3. PR 体量 | 变更文件 ≤ 3，diff 行数 ≤ 50 | 升级 R2 |
| 4. 文件类型 | 仅 `.py` 或 `.md`，禁止改 `pyproject.toml`/CI workflow/迁移脚本 | 升级 R3 |
| 5. 文件路径 | 不在 `app/db/migrations/`、`app/fastapi_app/`、`scripts/deploy/` | 升级 R3 |
| 6. 指纹去重 | 同 fingerprint 24h 内仅 1 个 PR | 关闭重复 PR |
| 7. Branch 守卫 | 不能是 `autonomy/` 分支（不递归） | 关闭 PR |

**任何一条不满足 → 自动升级到 R2（stale→close 流程）**

## 四、stale 生命周期（R2/R3）

| 时间 | R2 动作 | R3 动作 |
|------|---------|---------|
| T+0 | 创建 PR + `needs-human` + `ai-self-heal` + `risk:r2` 标签 | 创建 PR + `needs-human` + `ai-self-heal` + `risk:r3` 标签 |
| T+7d | 评论 `@channel 该 PR 已 stale 7 天，将于 7 天后自动关闭` | 同上 |
| T+14d | 自动关闭 + 评论 `自动关闭：14 天未 review，指纹已记录` + 写 `ai-self-heal-stale.jsonl` | （不关闭） |
| T+30d | - | 自动关闭 + 评论 + 写 stale.jsonl |
| 任何时刻 | 人工 review 通过 → 正常合并；review 拒绝 → 关闭 + 指纹标记 `rejected` | 同上 |

**指纹 stale 记录**（`FHD/metrics/ai-self-heal-stale.jsonl`）：

```json
{"ts": 1784370000, "fingerprint": "abc123", "pr_url": "...", "risk": "r2", "closed_reason": "stale_14d", "reviewer_action": "none"}
{"ts": 1784370100, "fingerprint": "def456", "pr_url": "...", "risk": "r3", "closed_reason": "stale_30d", "reviewer_action": "none"}
{"ts": 1784370200, "fingerprint": "ghi789", "pr_url": "...", "risk": "r1", "closed_reason": "auto_merged_72h", "reviewer_action": "auto"}
```

## 五、修改 ai_self_heal.py（增量）

### 5.1 在 `match_rules` 中返回风险等级

```python
@dataclass
class Fix:
    error: ErrorEntry
    patch: str
    needs_human: bool
    description: str
    risk_level: str = "r3"  # 新增：r0/r1/r2/r3


def match_rules(errors: list[ErrorEntry]) -> list[Fix]:
    fixes: list[Fix] = []
    for err in errors:
        if err.tool == "ruff":
            if err.code in {"F401", "F811"}:
                patch = _make_remove_import_patch(err.file_path, err.line, err.raw)
                fixes.append(Fix(err, patch, False, f"删除未使用 import", risk_level="r0"))
                continue
            if err.code == "E501":
                patch = _make_truncate_line_patch(err.file_path, err.line)
                fixes.append(Fix(err, patch, False, f"截断超长行", risk_level="r0"))
                continue
            if err.code == "F841":
                # 从 needs_human=True 降为 r1，配二次校验
                fixes.append(Fix(err, "", True, f"未用局部变量（r1 待二次校验）", risk_level="r1"))
                continue
            # ruff 其他 → r2
            fixes.append(Fix(err, "", True, f"ruff {err.code}", risk_level="r2"))
            continue
        if err.tool == "bandit":
            fixes.append(Fix(err, "", True, f"bandit [{err.code}]", risk_level="r3"))
            continue
        if err.tool == "mypy":
            fixes.append(Fix(err, "", True, f"mypy: {err.message}", risk_level="r2"))
            continue
        if err.tool == "pytest":
            fixes.append(Fix(err, "", True, f"pytest: {err.message}", risk_level="r3"))
            continue
        fixes.append(Fix(err, "", True, "未知工具", risk_level="r3"))
    return fixes
```

### 5.2 PR 标签带风险等级

```python
# 在 create_pr 调用处，根据 fixes 中最高风险等级打标签
max_risk = max((f.risk_level for f in fixes), default="r3")
labels = ["needs-human", "ai-self-heal", f"risk:{max_risk}"]
pr_url = create_pr(branch, patch, labels=labels, ...)
```

### 5.3 LLM 兜底修复强制 r3

```python
# LLM 修复仍标 needs-human + r3，不进入 auto-merge 候选
if llm_fixes:
    for fix in llm_fixes:
        fix.risk_level = "r3"
        fix.needs_human = True
```

## 六、新增工作流 `ai-self-heal-auto-merge.yml`

```yaml
# FHD/.github/workflows/ai-self-heal-auto-merge.yml
# 每日 09:00 UTC 扫描 ai-self-heal 标签 PR，按 SLA 处理
name: AI Self-Heal Auto-Merge SLA

on:
  schedule:
    - cron: "0 1 * * *"  # 每日 09:00 UTC+8 = 01:00 UTC
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  process-prs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Process ai-self-heal PRs by SLA
        working-directory: FHD
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python scripts/ci/ai_self_heal_sla.py \
            --repo "${{ github.repository }}" \
            --auto-merge-r0-hours 24 \
            --auto-merge-r1-hours 72 \
            --stale-r2-days 7 \
            --close-r2-days 14 \
            --stale-r3-days 7 \
            --close-r3-days 30
```

## 七、新增脚本 `FHD/scripts/ci/ai_self_heal_sla.py`

职责：

```python
"""每日扫描 ai-self-heal PR，按 SLA 处理：auto-merge / stale 提醒 / 关闭。

输入：repo, 各 SLA 阈值
流程：
1. 列出所有 open PR + label: ai-self-heal
2. 按 risk:* 标签分流
3. R0/R1：检查二次守卫（CI 绿、覆盖率、体量、文件类型、指纹、分支）→ 达标 auto-merge
4. R2：>7d 评论提醒，>14d 自动关闭
5. R3：>7d 评论提醒，>30d 自动关闭
6. 全部动作写 ai-self-heal-stale.jsonl
"""
```

核心函数：

```python
def check_second_guard(pr) -> tuple[bool, str]:
    """二次校验：返回 (passed, reason)"""
    if not ci_all_green(pr): return False, "ci_not_green"
    if coverage_regressed(pr): return False, "coverage_regressed"
    if pr.changed_files > 3: return False, "too_many_files"
    if not all_safe_file_types(pr): return False, "unsafe_file_type"
    if any_forbidden_path(pr): return False, "forbidden_path"
    if is_autonomy_branch(pr.head.ref): return False, "autonomy_branch"
    return True, "ok"


def auto_merge_pr(pr, method: str = "squash") -> bool:
    """二次守卫通过后自动合并"""
    passed, reason = check_second_guard(pr)
    if not passed:
        upgrade_risk_label(pr, "r2")
        comment(pr, f"二次守卫未通过 ({reason})，升级为 R2，转 stale→close 流程")
        return False
    pr.merge(method)
    append_stale_jsonl(pr, action="auto_merged")
    return True
```

## 八、监控 SLO

| ID | 名称 | 目标 | 验证 |
|----|------|------|------|
| SLO-SELFH-01 | R0/R1 auto-merge 成功率 | ≥ 95% | stale.jsonl 中 auto_merged / (auto_merged + ci_not_green) |
| SLO-SELFH-02 | 二次守卫拦截率（误报防线） | < 30% | 升级 R2 数 / R0+R1 总数 |
| SLO-SELFH-03 | stale PR 平均存活时间 | R2 ≤ 14d, R3 ≤ 30d | stale.jsonl closed_at - created_at |
| SLO-SELFH-04 | 同 fingerprint 重复 PR 数 | 0（24h 内） | 指纹去重命中率 |
| SLO-SELFH-05 | 自治 PR 合并占比 | ≥ 40%（auto-merged / total） | 月度统计 |

## 九、首日落地 checklist

- [ ] 修改 [ai_self_heal.py](file:///Users/a4243342/Desktop/XCMAX/FHD/scripts/ci/ai_self_heal.py)：Fix 增加 `risk_level` 字段，`match_rules` 返回分级，`create_pr` 打 `risk:*` 标签
- [ ] 新增 `FHD/scripts/ci/ai_self_heal_sla.py` 脚本（二次守卫 + SLA 处理）
- [ ] 新增 `FHD/.github/workflows/ai-self-heal-auto-merge.yml`（每日 09:00 UTC 触发）
- [ ] 同步到根仓：`python scripts/dev/publish_ci_workflows_to_root.py`
- [ ] 在 `metrics/ai-self-heal-stale.jsonl` 初始化空文件
- [ ] 把 SLO-SELFH-01..05 加入 `collect_slo_metrics.py`
- [ ] 首个 R0 PR 跑通 auto-merge 流程后，再开启 R1
- [ ] 更新 [cicd-e2e-prompt.md](file:///Users/a4243342/Desktop/XCMAX/.trae/rules/cicd-e2e-prompt.md) 决策矩阵：补"R0 24h / R1 72h auto-merge"行

## 十、与现有约束的一致性

| 现有约束 | 本方案一致性 |
|---------|------------|
| 同指纹 24h 去重 | ✅ 保留，且新加"重复 PR 自动关闭" |
| autonomy/ 分支不递归 | ✅ 二次守卫第 7 条强制校验 |
| LLM fail-open | ✅ 保留，LLM 修复仍 r3 永不自动合并 |
| needs-human 业务码 | ✅ R3 永不自动合并，强制人工 |
| bandit 安全相关 | ✅ 永远 r3 |
| Branch Protection | 需要仓库 Owner 把 `ai-self-heal-auto-merge` 加入 main 分支 required checks（人工配置） |
