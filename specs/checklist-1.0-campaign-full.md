# XCMAX 1.0 战役全量完成清单

> **首样板**：通用（`ACCEPTANCE_GENERIC_1.0-A.md`）  
> **更新**：2026-07-29  
> **状态图例**：`[x]` 已完成 · `[ ]` 未完成 · `[-]` 本战役明确不做（冻结）

战役成功定义：装完能干活（通用）· 授权装得上（商店）· 出问题找得到（工单）· 叙事不膨胀。

---

## Phase 0 · 口径锁定

| ID | 任务 | 状态 | 证据 / 路径 |
|----|------|------|-------------|
| P0-1 | 首样板定为「通用」 | [x] | `specs/weekly/2026-W31-generic-first-sample.md` |
| P0-2 | 客户验收清单落仓 | [x] | `FHD/docs/customer/ACCEPTANCE_GENERIC_1.0-A.md` |
| P0-3 | DELIVERABLE / USER_FLOW / START_HERE 锚点 | [x] | 三份 docs + `industry_baseline.json` note |
| P0-4 | 证据目录 stub | [x] | `FHD/docs/evidence/e2e/closure-generic-1.0-A-20260729/` |
| P0-5 | 对外承诺页（销售一页纸：承诺/不承诺） | [ ] | 从 ACCEPTANCE §0 导出 PDF/一页纸 |
| P0-6 | `PROJECT_STATE.md` 写入「首样板=通用」一行 | [ ] | `FHD/docs/PROJECT_STATE.md` |

---

## Phase A · 通用首样板交付（1.0-A · P0）

### A1 自动化 / API

| ID | 任务 | 状态 | 通过标准 |
|----|------|------|----------|
| A1-1 | deliverable + edition + generic baseline pytest | [x] | 19 passed（2026-07-29） |
| A1-2 | 本地 `make setup && make dev` 或桌面 SQLite 冷启 | [ ] | `/api/health` = 200 |
| A1-3 | `GET /api/platform-shell/deliverable-status` | [ ] | `deliverable=true`，`missing_mod_ids=[]`，JSON 落证据目录 |
| A1-4 | `POST bootstrap-edition-pack?edition=generic`（若缺 Mod） | [ ] | `success=true` 后再验 A1-3 |
| A1-5 | `GET /api/platform-shell/capabilities` | [ ] | `success=true`，JSON 落盘 |
| A1-6 | `verify_version_anchors.py` | [ ] | exit 0 |
| A1-7 | `deliverable_smoke.ps1`（或等价桌面 SQLite smoke） | [ ] | 全绿 |

### A2 引导与三动作（人工勾 ACCEPTANCE）

| ID | 任务 | 状态 | 对应 ACCEPTANCE |
|----|------|------|-----------------|
| A2-1 | 安装包/构建标识核对 `1.0.0.0` enterprise | [ ] | §1.1–1.2 |
| A2-2 | 记录 userData 路径 | [ ] | §1.3 |
| A2-3 | 引导：welcome → industry=**通用** → host-pack | [ ] | §2.1–2.2 |
| A2-4 | 引导选「通用」截图 | [ ] | 证据 README 待补 |
| A2-5 | 动作 3.1 智能对话一轮（截图） | [ ] | §3.1 |
| A2-6 | 动作 3.2 capabilities / 壳菜单（截图） | [ ] | §3.2 |
| A2-7 | 动作 3.3 neuro-bus 已装 + health（截图） | [ ] | §3.3 |
| A2-8 | （加分）可选装 excel-tools / 开 ERP 一页 | [ ] | ACCEPTANCE 加分，不挡签字 |
| A2-9 | 日志路径可指认 | [ ] | §4.1 |
| A2-10 | userData / backups 备份演练 | [ ] | §4.2 |
| A2-11 | 重装或还原后再验 deliverable | [ ] | §4.3 |
| A2-12 | 客户 + 供应商双签字 PASS | [ ] | §6 |

### A3 安装包

| ID | 任务 | 状态 | 通过标准 |
|----|------|------|----------|
| A3-1 | 打 enterprise 安装包（Win 优先） | [ ] | `XCAGI-Enterprise-Setup-1.0.0.0-*.exe` |
| A3-2 | post 验收：后端 exe + product-sku + bundled mods + industry-seeds | [ ] | `pre-release-security.ps1 -Phase post` |
| A3-3 | Win 冷启 → deliverable=true | [ ] | 证据 JSON + 截图 |
| A3-4 | macOS dmg 冷启（至少一条） | [ ] | deliverable=true；公证可标「可选」 |
| A3-5 | `adcdfg_acceptance.ps1` | [ ] | 全绿 |
| A3-6 | A 轨退出评审（Go/No-Go） | [ ] | 15 分钟可演示通用样板 |

**A 轨退出门槛**：A1-3 + A2-5/6/7 + A3-3 + A2-12 全 `[x]`。

---

## Phase B · 商店→桌面闭环（1.0-B · P1，不挡 A）

| ID | 任务 | 状态 | 通过标准 |
|----|------|------|----------|
| B1-1 | 读懂 entitlement / user_mods SSOT | [ ] | `payment_fulfillment.py` + 测试旁证 |
| B1-2 | 跑 `provision_enterprise_delivery.py`（测试企业账号） | [ ] | 目标 mod_ids 已授 |
| B1-3 | `GET /api/payment/entitlements` 有条目 | [ ] | 截图或 JSON |
| B1-4 | 相关 pytest：`test_payment_contract` / `test_internal_enterprise_entitlements` | [ ] | 绿 |
| B2-1 | 桌面连市场源（local 或 online-market env） | [ ] | Catalog 可见已授权项 |
| B2-2 | Catalog → 安装 → 侧栏出现 | [ ] | 录屏 5–10 min |
| B2-3 | 安装后再验 deliverable / Mod 路由 | [ ] | 无 5xx |
| B3-1 | 支付主路径（沙箱或真实一单） | [ ] | 订单→entitlement；失败则降级为「仅预置授权」并书面说明 |
| B3-2 | B 轨退出：证据归档 + 销售口径「已在 X 环境验证」 | [ ] | 禁止称「全自动商业化完成」 |

**B 失败降级**：A 仍可凭离线 seed 签约演示；商店缺口单独开单。

---

## Phase C · 消膨胀 / 聚焦

| ID | 任务 | 状态 | 通过标准 |
|----|------|------|----------|
| C1-1 | 客来来体积盘点报告（desktop/dist/venv） | [ ] | `du` 分项表 |
| C1-2 | 选定方案 a 出仓 / b 去制品 / c 冻结+ARCHIVED | [ ] | 三行 ADR |
| C1-3 | 执行 C1-2，主路径不再含 GB 级制品 | [ ] | `du -sh …/客来来` 合理 |
| C2-1 | 宣传资料：补最小 5 件 **或** README 标空勿尽调 | [ ] | 二选一落地 |
| C3-1 | PR 规则：禁新增 `app/services/*` | [ ] | rule / review 清单 |
| C3-2 | 新任务必须标 desktop/modstore/mobile/ops | [ ] | 周会执行 |
| C3-3 | yuangon 角色不得写入客户销售材料 | [ ] | 销售包审查 |
| C3-4 | 修对外入口文档漂移（README/VERSION/START_HERE/DELIVERABLE/CLAIMED） | [ ] | 五入口无矛盾 |

---

## Phase D · 客服工单实跑（内部）

| ID | 任务 | 状态 | 通过标准 |
|----|------|------|----------|
| D1-1 | 确认总线 SSOT = MODstore `incident_bus`（非 NeuroBus） | [ ] | `CUSTOMER_TICKET_BUS_SSOT.md` |
| D1-2 | staging/本地创建 `CS*` 工单 | [ ] | `ops.intake.customer_ticket` |
| D1-3 | enrich → routing_plan → 派发 | [ ] | `dispatched_count > 0` |
| D1-4 | lifecycle 回写非空 | [ ] | `_cs_progress.lifecycle_*` |
| D1-5 | 非全员 `handler_failed`；失败可按 kind 观测 | [ ] | 日志/指标 |
| D2-1 | 数字写入 `PROJECT_STATE`（样本数、积压率、环境） | [ ] | 可引用 |
| D3-1 | （可选）Para 真改→验证→回写一条 | [ ] | 有则记；无则保持「未稳定」 |

**未完成 D2-1 前**：对外禁止「无人客服已闭环」。

---

## Phase E · 战役收口与对外

| ID | 任务 | 状态 | 通过标准 |
|----|------|------|----------|
| E1 | 更新 `CLAIMED_VS_ACTUAL` / 覆盖率无新红灯 | [ ] | 黄灯可接受并解释 |
| E2 | 销售话术只讲「通用首样板 + 可选商店」 | [ ] | 一页纸与 ACCEPTANCE §0 一致 |
| E3 | `PROJECT_STATE` 综合叙述与证据路径对齐 | [ ] | 无「架构已闭环」夸大 |
| E4 | 周报归档本战役 PASS/FAIL | [ ] | `specs/weekly/` |
| E5 | （可选）下一战役立项：涂料或考勤第二样板清单 | [-] | 不在本战役范围 |

---

## 本战役明确不做（冻结）

| ID | 项 |
|----|-----|
| Z1 | bump 产品版本离开 `1.0.0.0` |
| Z2 | 恢复个人版功能 |
| Z3 | Android/iOS 签约级承诺 |
| Z4 | 完整 RBAC / IdP / SIEM |
| Z5 | 客来来全渠道商用化 |
| Z6 | 以 yuangon 55 角色作客户交付物 |
| Z7 | 冲覆盖率 / 新增 coverage_ramp |
| Z8 | 扩 k8s 生产化为主路径 |
| Z9 | 新开第四条产品线 |

---

## 进度汇总（勾选后重算）

| 阶段 | 已完成 | 未完成 | 退出门槛 |
|------|--------|--------|----------|
| P0 口径 | 4 | 2 | P0-5 或 P0-6 至少 1 项（建议都做） |
| A 通用样板 | 1（pytest） | 其余 | A 退出门槛见上 |
| B 商店 | 0 | 全部 | 可不挡 A；要「商业化闭环」则 B3-2 |
| C 消膨胀 | 0 | 全部 | C1-3 + C2-1 必做 |
| D 工单 | 0 | 全部 | D2-1 才可对内宣称 |
| E 收口 | 0 | 全部 | A 退出 + E2 |

**建议执行顺序**：P0 收尾 → A1/A2 → A3 →（并行）C1 → B → D → E。

---

## 快速命令备忘

```bash
# A1 自动化
cd FHD && uv run python -m pytest \
  tests/test_deliverable_status.py \
  tests/test_edition_policy.py \
  tests/test_industry_baseline.py::test_industry_baseline_generic_minimal -q
python3 scripts/dev/verify_version_anchors.py

# 交付 API（服务已起）
curl -s http://127.0.0.1:5000/api/platform-shell/deliverable-status | tee \
  docs/evidence/e2e/closure-generic-1.0-A-20260729/deliverable-status.json

# B 预置（在 MODstore_deploy）
python scripts/provision_enterprise_delivery.py --help
```

客户勾选细表仍以 [`FHD/docs/customer/ACCEPTANCE_GENERIC_1.0-A.md`](../FHD/docs/customer/ACCEPTANCE_GENERIC_1.0-A.md) 为准；本文件是战役全量任务看板。
