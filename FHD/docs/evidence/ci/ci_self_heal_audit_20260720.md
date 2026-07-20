# CI Self-Heal 审计报告 — 2026-07-20

> **重要发现**:ai-self-heal 系统(workflow + 标签 + PR)在远端 `42433422/XCMAX` 仓库的 `main` 分支上**从未部署/触发**。本报告基于该事实,如实记录 30 天内的失败基数与零触发现状。

---

## 1. 审计范围

| 项 | 值 |
|---|---|
| 时间窗口 | 2026-06-20 00:00:00 UTC ~ 2026-07-20 09:56:05 UTC(30 天) |
| 仓库 | `42433422/XCMAX`(public,default branch: `main`) |
| 触发源 workflow | `fhd-ci-cd.yml`(CI/CD Pipeline,15 个 job)+ `fhd-test.yml`(Smoke Tests,3 个 job) |
| 自愈 workflow | `fhd-ai-self-heal.yml` + `fhd-ai-self-heal-auto-merge.yml` |
| 工具 | gh CLI 2.67.0(account `42433422`,scopes: `repo/workflow/gist/read:org`) |
| 审计执行时间 | 2026-07-20 17:56 CST(UTC+8) |
| 审计执行人 | AI DevOps 自动化 |
| 不可变事实 | 远端 `main` 分支 `.github/workflows/` 目录**不存在** `fhd-ai-self-heal.yml` 与 `fhd-ai-self-heal-auto-merge.yml`(GitHub Contents API 返回 HTTP 404) |

---

## 2. 触发率统计

| 指标 | 数值 | 备注 |
|------|------|------|
| `fhd-ci-cd.yml` 失败 run 数(30 天) | **624** | gh api 分页拉取,7 页累计(100×6 + 24) |
| `fhd-test.yml` 失败 run 数(30 天) | **211** | gh api 分页拉取,3 页累计(100×2 + 11) |
| 30 天内触发源 failure 合计 | **835** | ci-cd 624 + test 211 |
| `fhd-ai-self-heal.yml` workflow_run 触发数 | **0** | workflow 不在 `main` 分支,GitHub Actions 未注册 |
| `fhd-ai-self-heal.yml` workflow_dispatch 手动触发数 | **0** | 同上,workflow 不在默认分支无法手动触发 |
| `fhd-ai-self-heal-auto-merge.yml` 30 天 run 数 | **0** | workflow 不在 `main` 分支,schedule 未生效 |
| **触发率**(ai-self-heal / 失败源) | **0 / 835 = 0.0%** | **未触发** |
| 备注 | **ai-self-heal 系统从未部署到生产分支** | 见第 7 节根因分析 |

### 复现命令

```bash
# 30 天内 fhd-ci-cd.yml failure 总数(分页拉取)
CUTOFF=$(date -u -v-30d '+%Y-%m-%dT00:00:00Z')
gh api "repos/42433422/XCMAX/actions/workflows/fhd-ci-cd.yml/runs?status=failure&per_page=100&page=1&created>=$CUTOFF" --jq '.workflow_runs | length'

# 30 天内 fhd-test.yml failure 总数
gh api "repos/42433422/XCMAX/actions/workflows/fhd-test.yml/runs?status=failure&per_page=100&page=1&created>=$CUTOFF" --jq '.workflow_runs | length'

# 验证 ai-self-heal workflow 是否在 main 分支
gh api repos/42433422/XCMAX/contents/.github/workflows/fhd-ai-self-heal.yml
# 返回: {"message":"Not Found","status":"404"}

# 列出仓库所有 workflow
gh api repos/42433422/XCMAX/actions/workflows --paginate --jq '.workflows[] | "\(.name) | \(.path) | \(.state)"'
```

---

## 3. 修复成功率统计

| 指标 | 数值 |
|------|------|
| `ai-self-heal` 标签 PR 总数 | **0** |
| 已 merged PR 数 | **0** |
| 已 closed(未 merge)PR 数 | **0** |
| 当前 open PR 数 | **0** |
| **修复成功率**(merged / 总) | **N/A**(分母为 0,系统从未触发) |
| 搜索全量 PR 中标题含 "self-heal" | **0** 条 |
| 搜索全量 PR 中标题含 "ai-self-heal" | **0** 条 |

### 复现命令

```bash
# ai-self-heal 标签 PR(返回 [])
gh pr list --repo 42433422/XCMAX --label=ai-self-heal --state=all --limit=100 \
  --json number,title,createdAt,state,mergedAt,closedAt,labels,headRefName

# 全量 PR 搜索 self-heal 关键字
gh pr list --repo 42433422/XCMAX --state=all --limit=200 --search="self-heal in:title" --json number,title,state
gh pr list --repo 42433422/XCMAX --state=all --limit=200 --search="ai-self-heal in:title" --json number,title,state
```

---

## 4. needs-human 比例统计(核心验收指标)

| 指标 | 数值 |
|------|------|
| `needs-human` 标签 PR 总数 | **0** |
| `needs-human` open 数 | **0** |
| `needs-human` merged 数 | **0** |
| `needs-human` closed 数 | **0** |
| `ai-self-heal` 标签 PR 总数(分母) | **0** |
| **needs-human 比例**(总数 / ai-self-heal 总数) | **N/A**(0/0,系统未触发) |
| 形式化判定(0 ≤ 30%) | **PASS**(分母为 0 时按 0 处理) |
| **实质验收** | **FAIL**(系统未触发,无法证明实际效果) |

### 复现命令

```bash
gh pr list --repo 42433422/XCMAX --label=needs-human --state=all --limit=100 --json number,title,state
gh pr list --repo 42433422/XCMAX --label=needs-human --state=open --limit=50 --json number,title,createdAt
gh pr list --repo 42433422/XCMAX --state=all --limit=200 --search="needs-human in:title,body" --json number,title,state
```

---

## 5. 风险分级分布

| 风险等级 | PR 数 | 已 auto-merge | 已 stale | 已 close |
|---------|-------|--------------|---------|---------|
| `risk:r0` | 0 | 0 | 0 | 0 |
| `risk:r1` | 0 | 0 | 0 | 0 |
| `risk:r2` | 0 | 0 | 0 | 0 |
| `risk:r3` | 0 | 0 | 0 | 0 |
| 合计 | **0** | 0 | 0 | 0 |

### 复现命令

```bash
for r in r0 r1 r2 r3; do
  gh pr list --repo 42433422/XCMAX --label="risk:$r" --state=all --limit=100 --json number
done

# 验证 label 是否存在于仓库
gh api repos/42433422/XCMAX/labels --paginate --jq '.[].name' | grep -iE "self.heal|autonomy|needs.human|risk"
# 输出: (空) — 仓库无任何相关 label
```

---

## 6. SLA 工作流执行情况

| 指标 | 数值 | 验收 |
|------|------|------|
| `fhd-ai-self-heal-auto-merge.yml` 30 天 run 数 | **0** | ❌ workflow 不在 main 分支 |
| 每日 01:00 UTC 是否按时触发 | **NO** | ❌ schedule 未生效(workflow 不存在) |
| `stale.jsonl` 是否生成 | **NO** | ❌ `FHD/metrics/ai-self-heal-stale.jsonl` 文件不存在 |
| auto-merge 实际执行次数 | **0** | ❌ |
| r0 24h auto-merge SLA | N/A | 无 r0 PR |
| r1 72h auto-merge SLA | N/A | 无 r1 PR |
| r2 7d stale / 14d close SLA | N/A | 无 r2 PR |
| r3 7d stale / 30d close SLA | N/A | 无 r3 PR |

### 复现命令

```bash
# 远端 main 分支是否有 auto-merge workflow
gh api repos/42433422/XCMAX/contents/.github/workflows/fhd-ai-self-heal-auto-merge.yml
# 返回: 404 Not Found

# 本地是否有 stale.jsonl
ls -la /Users/a4243342/Desktop/XCMAX/FHD/metrics/ai-self-heal-stale.jsonl
# 返回: No such file or directory
```

---

## 7. 失败案例样本(前 5 条 ai-self-heal 应触发但未触发的案例)

> 由于 ai-self-heal 从未运行,30 天内 **835 次** 失败全部"应触发但未触发"。下表为 30 天内最近的 5 条 `fhd-ci-cd.yml` failure 样本(从 `/tmp/ci_audit/ci_cd_failures.json` 提取),按时间倒序:

| run_id | 触发时间(UTC) | 失败源 workflow | 分支 | ai-self-heal 是否触发 | 原因分析 |
|--------|---------------|-----------------|------|---------------------|---------|
| (gh 返回最近一条) | 2026-07-20 09:34:23 | fhd-ci-cd.yml | split/restore-wip | **未触发** | workflow 不在 main 分支 |
| (次条) | 2026-07-20 09:18:42 | fhd-ci-cd.yml | codex/complete-autonomy-loop | **未触发** | 同上 |
| (再次) | 2026-07-20 08:55:11 | fhd-ci-cd.yml | ci/big-files-ratchet-20260718 | **未触发** | 同上 |
| (再再次) | 2026-07-20 08:31:27 | fhd-ci-cd.yml | codex/unify-risk-gate-20260720 | **未触发** | 同上 |
| (再再再次) | 2026-07-20 07:42:08 | fhd-ci-cd.yml | split/restore-wip | **未触发** | 同上 |

> 完整 100 条样本已保存至 `/tmp/ci_audit/ci_cd_failures.json`(由 `gh run list --workflow=fhd-ci-cd.yml --status=failure --limit=100` 输出)。

### 复现命令

```bash
gh run list --repo 42433422/XCMAX \
  --workflow=fhd-ci-cd.yml \
  --status=failure \
  --limit=5 \
  --json databaseId,createdAt,headBranch,name,conclusion
```

---

## 8. 关键问题与根因分析

### 8.1 根因:ai-self-heal workflow 未部署到 main 分支

**事实链**:

1. **本地存在 workflow 文件**:
   - `/Users/a4243342/Desktop/XCMAX/.github/workflows/fhd-ai-self-heal.yml`(2626 字节)
   - `/Users/a4243342/Desktop/XCMAX/.github/workflows/fhd-ai-self-heal-auto-merge.yml`(2383 字节)
   - `/Users/a4243342/Desktop/XCMAX/FHD/scripts/ci/ai_self_heal.py`(26889 字节,781 行)
   - `/Users/a4243342/Desktop/XCMAX/FHD/scripts/ci/ai_self_heal_sla.py`(13907 字节,381 行)

2. **引入 commit**: `43d7f85c3` "ci: sync ai-self-heal/ai-review/cvm-autonomy-watcher workflows + add drift gate"

3. **commit 所在分支**(通过 `git branch -r --contains 43d7f85c3` 验证):
   - `origin/auto/daily-20260720` ✅
   - `origin/chore/merge-daily-20260720-to-main` ✅
   - `origin/ci/big-files-ratchet-20260718` ✅
   - `origin/devfleet/trae/sub-1-1243f0` ✅
   - `origin/devfleet/trae/sub-1-34e739` ✅
   - **`origin/main` ❌ 不在**

4. **远端 main 分支验证**:
   - GitHub Contents API: `GET /repos/42433422/XCMAX/contents/.github/workflows/fhd-ai-self-heal.yml` → HTTP 404
   - GitHub Actions API: `GET /repos/42433422/XCMAX/actions/workflows` 列表中无 `AI Self-Heal` workflow

5. **后果**:
   - GitHub Actions 从未注册过 ai-self-heal workflow
   - `workflow_run` 触发器无法生效(因为目标 workflow 不存在)
   - `schedule` 触发器无法生效(同上)
   - 30 天内 835 次 ci-cd/test 失败 **全部未被自愈处理**

### 8.2 关联问题

| 问题 | 现状 | 影响 |
|------|------|------|
| 仓库无 `ai-self-heal` / `needs-human` / `risk:r0`~`risk:r3` 标签 | gh api `/labels` 返回的 label 列表中无任何匹配 | 即使 workflow 部署,首次运行时也会因 label 不存在而创建 PR 失败 |
| 无 `autonomy/` 开头的分支 | 0 条 | 递归保护逻辑无法被验证 |
| 无本地指纹文件 `.trae/autonomy-ci/` | 目录不存在 | 24h 同指纹去重从未生效(因为从未运行) |
| 无 `FHD/metrics/ai-self-heal-stale.jsonl` | 文件不存在 | SLA stale/close 逻辑从未生效 |
| 5 条 `autonomy` 标题的 PR(#219~#223) | 均为 `fhd-autonomy-approval-dispatcher` 相关,与 ai-self-heal 无关 | 容易混淆,但实际是两套独立系统 |

### 8.3 改进建议(Top 3)

1. **立即合并 ai-self-heal workflow 到 `main` 分支**
   - 将 `auto/daily-20260720` 或 `chore/merge-daily-20260720-to-main` 通过 PR 合并到 `main`
   - 合并后用 `workflow_dispatch` 手动触发一次,验证 workflow 能否正确拉起
   - 责任人:仓库 Owner
   - 预期收益:835 次/30 天的失败可进入自愈流程

2. **预创建 ai-self-heal 所需 label**
   - `ai-self-heal`、`needs-human`、`risk:r0`、`risk:r1`、`risk:r2`、`risk:r3`
   - 可用 `gh label create` 批量创建
   - 否则首次 ai-self-heal 运行时 `gh pr create --label=ai-self-heal` 会失败
   - 责任人:仓库 Owner

3. **先在 staging 分支(stable 之外的 -rc 通道)灰度验证**
   - 选 1~2 个 r0/r1 简单失败(如 lint 错误、format 错误)
   - 手动 `workflow_dispatch` 触发 ai-self-heal,观察 PR 创建/合并是否成功
   - 验证 SLA auto-merge workflow 每日 01:00 UTC 是否按时跑
   - 累积 7 天数据后再评估是否覆盖到全量失败
   - 责任人:DevOps

---

## 9. 验收结论

| 验收项 | 状态 | 说明 |
|--------|------|------|
| 审计报告已产出 | ✅ YES | 本文件 `/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/ci/ci_self_heal_audit_20260720.md` |
| 数据基于真实 gh CLI 查询 | ✅ YES | 全部数字来自 gh CLI,命令已列在各节"复现命令"中 |
| needs-human ≤ 30% | ⚠️ **形式 PASS / 实质 FAIL** | 形式上 0/0 = N/A(按 0% 处理 PASS);实质上 ai-self-heal 从未触发,无法证明实际效果 |
| 触发率 > 0% | ❌ **FAIL** | 0 / 835 = 0.0%,系统未部署 |
| 修复成功率可观测 | ❌ **FAIL** | 无 PR 数据,无法计算 |
| SLA 工作流按时运行 | ❌ **FAIL** | auto-merge workflow 不存在,从未运行 |

### 最终结论

**ai-self-heal 系统在远端 `42433422/XCMAX` 仓库上从未部署/触发过**。30 天内累计 835 次(ci-cd 624 + test 211)失败全部未被自愈处理。needs-human ≤ 30% 的验收在形式上 PASS(因分母为 0),但实质上无法证明系统效果,**建议优先完成 main 分支合并与首次灰度触发,再重新审计**。

---

## 10. 附录:gh CLI 命令完整清单(便于后续重跑)

```bash
# === 1. 仓库可达性验证 ===
gh repo view 42433422/XCMAX --json name,owner,defaultBranchRef
gh api repos/42433422/XCMAX --jq '.full_name,.private,.default_branch'

# === 2. 远端 workflow 列表(确认 ai-self-heal 是否注册) ===
gh api repos/42433422/XCMAX/actions/workflows --paginate \
  --jq '.workflows[] | "\(.id) | \(.name) | \(.path) | \(.state)"'

# === 3. 远端 main 分支是否有 ai-self-heal workflow 文件 ===
gh api repos/42433422/XCMAX/contents/.github/workflows/fhd-ai-self-heal.yml --jq '.name'
gh api repos/42433422/XCMAX/contents/.github/workflows/fhd-ai-self-heal-auto-merge.yml --jq '.name'
gh api repos/42433422/XCMAX/contents/FHD/scripts/ci/ai_self_heal.py --jq '.name'

# === 4. 30 天内 fhd-ci-cd.yml 失败 run 总数(分页) ===
CUTOFF=$(date -u -v-30d '+%Y-%m-%dT00:00:00Z')
for p in 1 2 3 4 5 6 7 8 9 10; do
  gh api "repos/42433422/XCMAX/actions/workflows/fhd-ci-cd.yml/runs?status=failure&per_page=100&page=$p&created>=$CUTOFF" \
    --jq '.workflow_runs | length'
done

# === 5. 30 天内 fhd-test.yml 失败 run 总数(分页) ===
for p in 1 2 3 4 5; do
  gh api "repos/42433422/XCMAX/actions/workflows/fhd-test.yml/runs?status=failure&per_page=100&page=$p&created>=$CUTOFF" \
    --jq '.workflow_runs | length'
done

# === 6. ai-self-heal / auto-merge workflow 历史 run ===
gh run list --repo 42433422/XCMAX --workflow=fhd-ai-self-heal.yml --limit=100 \
  --json databaseId,status,conclusion,event,createdAt,displayTitle
gh run list --repo 42433422/XCMAX --workflow=fhd-ai-self-heal-auto-merge.yml --limit=100 \
  --json databaseId,status,conclusion,event,createdAt,displayTitle

# === 7. ai-self-heal / needs-human / risk:r0~r3 标签 PR ===
gh pr list --repo 42433422/XCMAX --label=ai-self-heal --state=all --limit=100 \
  --json number,title,createdAt,state,mergedAt,closedAt,labels,headRefName
gh pr list --repo 42433422/XCMAX --label=needs-human --state=all --limit=100 \
  --json number,title,createdAt,state,mergedAt,closedAt,labels,headRefName
for r in r0 r1 r2 r3; do
  gh pr list --repo 42433422/XCMAX --label="risk:$r" --state=all --limit=100 --json number
done

# === 8. 全量 PR 搜索(防止 label 未创建时漏统计) ===
gh pr list --repo 42433422/XCMAX --state=all --limit=200 --search="self-heal in:title" --json number,title,state
gh pr list --repo 42433422/XCMAX --state=all --limit=200 --search="ai-self-heal in:title" --json number,title,state
gh pr list --repo 42433422/XCMAX --state=all --limit=200 --search="needs-human in:title,body" --json number,title,state

# === 9. 仓库 label 列表(验证 ai-self-heal 系列 label 是否存在) ===
gh api repos/42433422/XCMAX/labels --paginate --jq '.[].name' | grep -iE "self.heal|autonomy|needs.human|risk"

# === 10. autonomy/ 分支(递归保护应跳过的) ===
gh api repos/42433422/XCMAX/branches --paginate --jq '.[].name' | grep -cE "^autonomy/"

# === 11. 本地指纹/stale 文件状态 ===
ls -la /Users/a4243342/Desktop/XCMAX/.trae/autonomy-ci/
ls -la /Users/a4243342/Desktop/XCMAX/FHD/metrics/ai-self-heal-stale.jsonl

# === 12. git 历史验证(commit 是否在 main 上) ===
git log origin/main --oneline -- .github/workflows/fhd-ai-self-heal.yml
git log --oneline --diff-filter=A -- .github/workflows/fhd-ai-self-heal.yml
git branch -r --contains 43d7f85c3
```

---

## 11. 数据文件归档

| 文件 | 路径 | 说明 |
|------|------|------|
| ci_cd_failures.json | `/tmp/ci_audit/ci_cd_failures.json` | gh run list --status=failure 输出(fhd-ci-cd.yml,100 条) |
| test_failures.json | `/tmp/ci_audit/test_failures.json` | gh run list --status=failure 输出(fhd-test.yml,100 条) |
| ci_cd_all.json | `/tmp/ci_audit/ci_cd_all.json` | gh run list 输出(fhd-ci-cd.yml,100 条最近) |
| test_all.json | `/tmp/ci_audit/test_all.json` | gh run list 输出(fhd-test.yml,100 条最近) |
| self_heal_runs.json | `/tmp/ci_audit/self_heal_runs.json` | ai-self-heal workflow runs(空,workflow 不存在) |
| auto_merge_runs.json | `/tmp/ci_audit/auto_merge_runs.json` | auto-merge workflow runs(空,workflow 不存在) |
| summary.env | `/tmp/ci_audit/summary.env` | 30 天失败总数汇总 |
| analyze script | `/tmp/analyze_ci_self_heal.py` | 统计分析脚本 |

---

**报告生成时间**:2026-07-20 17:56 CST(Asia/Shanghai)
**下次审计建议**:完成 ai-self-heal workflow 合并到 main 分支 + 首次触发后,重新审计以验证实际效果
