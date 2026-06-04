# SLO 证据目录（M0 四域 · T36–T37）

> **状态（2026-06）**：**阻塞 T36–T37** — 需 staging 连续 7 天真实流量，或 k6 压测 + Grafana PNG 入库后方可填「实际」列。  
> **禁止**：无流量时伪造曲线、填假基线数字、提交占位 PNG 冒充验收。  
> **阻塞 SSOT**：[`specs/BLOCKERS.md`](../../../../specs/BLOCKERS.md) · 部署步骤 [`k8s/monitoring/STAGING_RUNBOOK.md`](../../../k8s/monitoring/STAGING_RUNBOOK.md)

---

## 1. M0 四域面板与文件命名

| 域 | SLO ID | Dashboard UID | Panel ID | 本地 PNG（验证栈） | Staging PNG（正式基线） |
|----|--------|---------------|----------|-------------------|------------------------|
| API 可用性 | SLO-API-01 | `xcagi-slo` | 1 | `grafana-local-m0-api-availability-202606.png` | `grafana-staging-m0-api-availability-YYYYMMDD.png` |
| DB / Mod SQLite | —（M0 路径图） | `xcagi-mod-store` | 5 | `grafana-local-m0-db-mod-sqlite-copies-202606.png` | `grafana-staging-m0-db-mod-sqlite-copies-YYYYMMDD.png` |
| AI 聊天首包 P95 | SLO-AI-01 | `xcagi-slo` | 3 | `grafana-local-m0-ai-chat-p95-202606.png` | `grafana-staging-m0-ai-chat-p95-YYYYMMDD.png` |
| NeuroBus 投递 | SLO-BUS-01 | `xcagi-slo` | 7 | `grafana-local-m0-neurobus-delivery-202606.png` | `grafana-staging-m0-neurobus-delivery-YYYYMMDD.png` |

辅助面板（非 M0 必交，可选入库）：

| 用途 | Dashboard UID | 说明 |
|------|---------------|------|
| API P95 / 错误率 | `xcagi-api-overview` | k6 压测期间观察 |
| 收入漏斗 | `xcagi-revenue` | T35 关联 |

导出脚本（本地 / staging 通用，需 Grafana 可达）：

```bash
cd FHD
GRAFANA_URL=http://127.0.0.1:3000 bash scripts/observability/export_m0_panels.sh --prefix local
GRAFANA_URL=https://grafana.staging.example bash scripts/observability/export_m0_panels.sh --prefix staging
```

---

## 2. 7 天验收字段模板（staging 解除阻塞后填写）

**推荐**：复制仓内模板文件（字段均为 `null` / `pending`，无假数据）：

```bash
cp docs/evidence/slo/acceptance-TEMPLATE.yaml docs/evidence/slo/acceptance-YYYYMMDD.yaml
```

亦可复制下方 YAML 块至 `acceptance-YYYYMMDD.yaml`（同目录），**仅从 Grafana / Prometheus 读数填写**；无法观测的字段保持 `null` 或 `待测`，勿臆造。

```yaml
# acceptance-YYYYMMDD.yaml — staging SLO 7 天验收（T36–T37）
meta:
  status: pending          # pending | pass | fail — 验收完成前保持 pending
  blocker_ref: specs/BLOCKERS.md#T36-T37
  environment: staging       # 固定 staging；本地 compose 不得冒充
  namespace: xcagi-staging   # K8s 命名空间
  grafana_url: null          # 例：https://grafana.staging.internal（只读账号说明另附）
  prometheus_url: null       # 可选；用于交叉核对
  observation_mode: null     # natural_7d | k6_supplement — 二选一或组合说明
  window_start: null         # ISO8601，≥7 天窗口起点
  window_end: null           # ISO8601，窗口终点
  verified_by: null          # 验收人 / 当值 SRE
  verified_at: null          # ISO8601

traffic:
  k6_run_id: null            # 若用 k6：results JSON 路径或 CI run URL
  k6_script: null            # 例：scripts/loadtest/smoke.js
  k6_base_url: null          # staging API 根 URL（勿填 localhost）
  natural_traffic_note: null # 7 天自然流量时：部署版本 / 是否有变更窗口

panels:
  api_availability:
    slo_id: SLO-API-01
    target: "99.9%"
    panel_ref: "xcagi-slo:1"
    screenshot: null         # 相对本目录 PNG 路径
    reading_7d: null         # 面板 Last 7 days 读数（百分数或小数，与 Grafana 一致）
    meets_target: null       # true | false | null

  api_login_p95_ms:
    slo_id: SLO-API-02
    target: "< 500"
    panel_ref: "xcagi-slo:6"
    screenshot: null
    reading_7d: null         # 毫秒
    meets_target: null

  api_error_rate:
    slo_id: SLO-API-03
    target: "< 0.1%"
    panel_ref: "xcagi-slo:2"
    screenshot: null
    reading_7d: null
    meets_target: null

  ai_chat_first_byte_p95_ms:
    slo_id: SLO-AI-01
    target: "< 1500"
    panel_ref: "xcagi-slo:3"
    screenshot: null
    reading_7d: null
    meets_target: null

  neurobus_delivery:
    slo_id: SLO-BUS-01
    target: ">= 99.95%"
    panel_ref: "xcagi-slo:7"
    screenshot: null
    reading_7d: null
    meets_target: null

  db_mod_sqlite:
    slo_id: null             # M0 路径图项，无独立 SLO ID
    panel_ref: "xcagi-mod-store:5"
    screenshot: null
    reading_7d: null         # 描述性读数或「有/无副本」说明
    meets_target: null

overall:
  all_m0_png_present: false  # 四域 staging PNG 均已入库
  claimed_vs_actual_updated: false  # docs/CLAIMED_VS_ACTUAL.md 已同步
  slo_md_updated: false      # docs/SLO.md 文首「数据源 / 当前基线」已同步（T38）
  notes: null                # 例外、变更窗口、数据缺口说明
```

### 验收通过条件（全部满足）

1. `window_end - window_start ≥ 7d`，且 scrape / API 部署在窗口内无长时间中断（>1h 需 `notes` 说明）。
2. 四域 **staging** PNG 已入库（文件名见上表），与 `panels.*.screenshot` 路径一致。
3. `panels` 中各 `reading_7d` 来自 Grafana **Last 7 days**（或等价 PromQL 窗口），与 PNG 可见读数一致。
4. `meta.status` 改为 `pass` 或 `fail`；**不得**在仍为 `pending` 时更新 CLAIMED 为「已验证」。

---

## 3. 本地 vs staging

| 环境 | 目录内文件前缀 | 能否作为 7 天 SLA 证据 |
|------|----------------|------------------------|
| **本地** compose | `grafana-local-m0-*` | **否** — 仅验证 compose / JSON / 导出脚本 |
| **staging** K8s | `grafana-staging-m0-*` | **是** — T36–T37 正式基线 |

本地一键：`bash scripts/observability/local_stack_up.sh`（需 Docker）。  
Staging 部署：[`STAGING_RUNBOOK.md`](../../../k8s/monitoring/STAGING_RUNBOOK.md)。

---

## 4. 关联

- 可复制模板：[`acceptance-TEMPLATE.yaml`](acceptance-TEMPLATE.yaml)（`meta.status: pending`，无假数据）
- 声称对照：[`docs/CLAIMED_VS_ACTUAL.md`](../../CLAIMED_VS_ACTUAL.md)
- M0 剩余缺口：[`docs/M0-remaining-gaps.md`](../../M0-remaining-gaps.md)
- 可观测脚本：[`scripts/observability/README.md`](../../../scripts/observability/README.md)
