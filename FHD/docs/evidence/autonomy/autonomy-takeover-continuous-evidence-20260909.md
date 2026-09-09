# 自治恢复、人工接管与持续运行证据（审计 R16 归档）

归档日期：2026-09-09。取证方式：GitHub Actions / issues / PR 只读 API + 仓库 metrics 目录实测，
不采信历史宣称；所有 run 号、issue 号、SHA 可复核。

## 1. 自治恢复闭环（自愈 loop 真实执行证据）

2026-08-22 一批 CI 红（Source Governance / CI/CD Pipeline / Release gate / desktop-macos-smoke）
由 `fhd-ai-self-heal` 完成「诊断 → 修复 PR → 验证 → 关闭事件」全链，逐条可追：

| 事件 issue | 关闭时间 | 修复载体 | 验证回执（记录于 issue 评论） |
|---|---|---|---|
| #1517 | 2026-08-22T13:29Z | PR #1516（提交 `964d3dfa`→`ddf3959ff`） | Source Governance run 32573611535 成功；PR 全部检查通过 |
| #1515 | 2026-08-22T13:29Z | 拆分 Dependabot PR #1469/#1474 关闭 | main 与 PR #1516 完整 CI 通过，旧失败不再可执行 |
| #1512 | 2026-08-22T11:36Z | 模块化测试/策略修复合并 | 主干 `02a5c63f`：CI/CD run 32568994578 成功，desktop-test/desktop-build 同 SHA 通过 |
| #1509 | 2026-08-22T09:35Z | PR #1504（提交 `772a7aa51`） | Release gate CI run 32565220691 成功；本地 78/78 通过 |

PR #1516 状态实测：MERGED（2026-08-22T13:29:37Z）。执行身份、审批（owner 合并）与结果回执可追溯。

## 2. 人工接管（needs-human / owner 决策路径）

- 审计 P1 缺陷 #1774（跨站令牌进 URL）、#1780（行业基线断言冲突）标 `needs-human`，
  2026-09-09 由复核确认修复已在 main（`81f0faf98` / `4b4a34b56`，compare 均 ahead）后关闭并留证据评论；
- 开放事件 #1812（Smoke Tests run 34235365607，第三方分支 `codex/ai-full-control`）保持 OPEN，
  自愈 loop 已受理（`ai-implement` 标签），等待 owner「确认」门禁后执行——接管边界按设计生效。

## 3. 持续运行证据

| 通道 | 实测（2026-09-09） | 结论 |
|---|---|---|
| `fhd-cvm-autonomy-watcher`（每 10 分钟） | 最近 20 次：19 success / 1 pending | 正常 |
| `ops-uptime` | 最近 20 次：19 success / 1 pending | 正常 |
| SLO 采集（`FHD/metrics/slo-measured-*.json` 旧格式） | 2026-07-26 → 09-03 共 38 份，缺 08-14、08-31 两日 | 39/40 日连续 |
| SLO 采集（`FHD/metrics/slo-production/` 新格式） | 2026-09-04 起 5 份（缺 09-06）；09-08 run 34227397273 采集步骤 exit 2，fail-closed 未产出假 PASS | 门禁行为正确 |
| `deploy_events.jsonl` | 1612 条部署事件留痕 | 正常 |
| 生产后端 | `/api/health` healthy、`version=1.0.0.1`、`git_sha=73861ed7`（main 祖先） | 正常 |

## 4. 已知缺口（如实记录，不判 PASS）

1. **30 日连续窗口未满**：新格式 `slo-production/` 自 09-04 起算仅 5 天；旧格式 38 份含 2 天缺口。
   完成条件「90 分连续窗口至少 30 日」需等到约 2026-10-04 后方可按新口径判定——时间性阻塞，不可压缩。
2. **自愈取消风暴（2026-09-08/09 观测）**：`fhd-ai-self-heal` 近 50 次 run 全部 cancelled（0 完成）。
   根因：CI 队列积压（峰值 758 queued）+ `workflow_run` 高频触发在同并发组内顶替排队 run
   （GitHub 并发组只保留一个 queued run）。属吞吐问题而非功能缺陷；队列消化后自愈。
   若复发可评估：为 self-heal 增加去抖（dedupe window）或独立并发组。
3. **09-08 SLO 采集失败**：采集步骤 exit 2（DORA 源与凭据相关），fail-closed 正确拦截、未发假 PASS；
   需下一次成功采集补上该日快照。

## 5. 判定

R16 = **部分完成**：自治恢复、人工接管、失败可核验三项有闭环证据（第 1/2/3 节）；
「30 日连续窗口」为硬性时间条件，最早 2026-10-04 可判。
