# AI 智能体产出溯源规范（2026-08-24）

> 目标：让每一处 AI 智能体产出（commit / PR / 分支 / 文件）都可审计、可归因、可回收，
> 降低「单人 + AI 集群」模式的单点依赖与失控风险。

## 背景

仓库提交者中 AI 占比高（TRAE 1733 次、DevFleet E2E Agent、Cursor Agent、
dependabot、MODstore Bot、xcmax-evolution-bot 等）。若无统一溯源：

1. 出问题无法快速定位是哪个智能体、哪条链路产出；
2. 无法区分「人工确认过的变更」与「机器自动合并的变更」；
3. 垃圾分支/僵尸 PR 难以按来源批量回收。

## 规范

### 1. Commit 溯源（强制）

所有智能体产出的 commit 必须携带 trailer（git trailer，位于 message 末尾）：

```
Generated-By: <agent-id>            # 如 trae / cursor / devfleet / codex / ai-self-heal
Agent-Run: <run-id 或 workflow run url>   # 可回溯到具体一次运行
Risk-Level: r0|r1|r2|r3             # 与自愈 PR 风险分级一致
```

- `Generated-By` 必填；`Agent-Run`、`Risk-Level` 尽量填。
- 人工提交不加（加了反而污染归因）。
- 示例：

```
fix(chat): dedupe approval cards

Generated-By: ai-self-heal
Agent-Run: https://github.com/42433422/XCMAX/actions/runs/12345
Risk-Level: r1
```

### 2. 分支命名（强制）

智能体分支必须带来源前缀，便于 `pr-hygiene` 按前缀批量回收：

| 前缀 | 来源 |
|------|------|
| `codex/` | Codex 智能体 |
| `devfleet/` | DevFleet E2E Agent |
| `autonomy/` | 自治循环 |
| `ai-impl/` | ai-issue-implement |
| `automation/` | 定时任务机器人（slo-metrics 等） |
| `auto/daily-*` | 每日自治维护 |
| `cursor/`、`trae/` | 对应 IDE 智能体 |

### 3. PR 标签（强制）

智能体产出的 PR 必须打来源标签 + 风险标签：

- 来源：`ai-self-heal` / `ai-implement` / `devfleet` / `codex` / `autonomy` 之一；
- 风险：`risk-r0` / `risk-r1` / `risk-r2` / `risk-r3`（对应自动合并策略）；
- 需人工介入：`needs-human`。

### 4. 自动合并与审计

- r0（机械变更）24h 后自动合并；r1（带验证的语义变更）72h 后自动合并；
  r2/r3 必须人工 review（沿用自愈 PR 既有策略）。
- 每次自动合并必须在 PR 留下 `Agent-Run` 链接，保证事后可回溯。
- 所有自动合并的 PR 进入「认领-合并-回收」闭环（见 `pr-hygiene.yml`）。

### 5. 审计查询

```bash
# 按来源统计提交
git log --format='%b' | grep -c 'Generated-By: trae'

# 找出某智能体近 30 天的提交
git log --since='30 days ago' --grep='Generated-By: ai-self-heal' --oneline

# 按前缀列出机器分支
git branch -r | grep -E 'codex/|devfleet/|autonomy/'
```

## 落地责任

- 各智能体的提交脚本（`ai_self_heal.py`、`ai_issue_implement.py` 等）负责写入 trailer；
- `pr-hygiene.yml` 负责按前缀/标签回收；
- 本规范变更需更新 `docs/CI_SSOT.md` 关联章节。
