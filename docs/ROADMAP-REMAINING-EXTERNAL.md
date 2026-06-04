# 路线图剩余项 — 工程闭环 vs 外部依赖（2026-06-05）

> **SSOT**：M0 三项缺口 [`M0-remaining-gaps.md`](M0-remaining-gaps.md) · 阻塞 [`specs/BLOCKERS.md`](../../specs/BLOCKERS.md) · M1 [`M1-kickoff-checklist.md`](M1-kickoff-checklist.md)

## 已在工程侧闭环（勿重复开工）

| 领域 | 验收 | 证据 / commit |
|------|------|----------------|
| 交付树 ≤8 GB | 不含 `.git` ~0.3G | [`workspace-size-delivery-tree.md`](workspace-size-delivery-tree.md) |
| e2e P0 全栈 | 14/14 mock + :5001 | `e2db1aaa` · `5936304a` · [`frontend/ARCHIVE_POINTER.md`](../frontend/ARCHIVE_POINTER.md) |
| API 契约 | vitest 367/367 | `618e4ade` |
| AI Agent V0 | mock + live JSON | `087cf0a9` · `demo-run-20260605-live.json` |
| K8s 可观测脚手架 | 看板 / rules / runbook | `1b69f614` · `3b3d9627` · `9b040292` |
| Staging 本机预检文档 | 无 Docker 路径 | [`staging-m0-preflight.md`](staging-m0-preflight.md) |
| SYNTHETIC AI 月报数据 | T56 SEED | [`AI_BUSINESS_EVIDENCE.md`](AI_BUSINESS_EVIDENCE.md) · `seed_synthetic_evidence.py` |
| Mod deploy check-only | 归档 + `MODSTORE_DEPLOY_ROOT` | `eb594987` · [`mod-pilot-blockers.md`](mod-pilot-blockers.md) |

## 无法在无外部资源时标「完成」（禁止伪造）

| ID | 任务 | 负责人 | 解除条件 | 最早 |
|----|------|--------|----------|------|
| **M0-1** | staging 7 天 SLO + 四图 | SRE / 平台 | 按 [`staging-m0-preflight.md`](staging-m0-preflight.md) §4；`export_m0_panels.sh --prefix staging` | BLOCKERS **T36–T37** ~2026-09 |
| **M0-2** | 真实 Mod 商家四图 | 商务 + MODstore | `evidence/mod/01–04.png` + `--verify` | 友好商家 / 0.01 元支付 |
| **M0-3** | SLO PNG（与 M0-1 同链） | 同上 | `grafana-staging-m0-*.png` | 同 T36–T37 |
| **M1-月报** | 生产 AI 月报 PDF | 业务 + 后端 | staging/生产只读库复核 | **T56** |
| **M1-等保** | 测评合同 + 时间表 | 合规 | 机构签字 | M3-W4 |
| **T59** | split push | DevOps | `git-filter-repo` + 发布窗口 | 2026-10 |

## 本机可选（非 M0 必交）

| 项 | 说明 |
|----|------|
| `du` ≤8G 含 `.git` | 需本机终端 `git gc` / `filter-repo`；交付树已达标 |
| 本地 Docker Grafana | 仅 `grafana-local-m0-*.png`；**≠** staging 验收 |
| LLM `planner_mode=llm` | `.env` 配置 `DEEPSEEK_API_KEY` 等，勿提交密钥 |

## M1 可并行起草（demo 未交付）

| 路径图项 | 状态 | 下一步 |
|----------|------|--------|
| M3-W2 智能搜索 V0 | 未开工 | 定 API + 1 个只读 demo |
| M3-W3 智能纪要 | 未开工 | 选通义听悟 / 腾讯会议 SDK |

---

**结论**：对标路径图 **M0 工程卫生 + M1 脚手架** 已可对外说明；**证据链致命项** 仅剩 staging SLO 与真实 Mod，须运维/商务解阻塞后更新 CLAIMED，不得提前勾 checklist T36–T37。
