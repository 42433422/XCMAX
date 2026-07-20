# Top-20 端点-业务 SLO 映射表（静态推断版 v1）

> **状态**：静态推断 v1，待 7 天 Prometheus 实测后修正（v2）
> **方法**：基于路由文件分布 + 业务域价值，复刻测试覆盖率六铁律的"全量口径、分支独立、可复现"思想
> **铁律映射**：覆盖率"全量 source=[app]"→ SLO"全量 763 端点分桶覆盖"；"分支独立统计"→"P95/P99/错误率分别守护"
> **更新策略**：每周五 09:00 UTC 由 `slo-endpoint-weekly.yml` 从 Prometheus `api_requests_total` 提取真实调用量，重排 Top-20 并 PR

## 一、SLO 三档分级（避免窄口径凑数）

| 档位 | 覆盖范围 | SLO 目标 | 判定频率 |
|------|---------|---------|---------|
| **Tier-P0**（业务核心） | Top-20 高频端点 | 每条独立 SLO | 每小时 |
| **Tier-P1**（业务相关） | Top-21~Top-100 | 聚合 SLO（按业务域） | 每日 |
| **Tier-P2**（长尾） | 其余 663 端点 | 聚合 SLO（仅错误率） | 每周 |

**判定铁律**（复刻 coverage ratchet）：
- 任何端点进入 Top-20 后**只升不降**（被挤出 Top-20 时自动落入 Tier-P1，SLO 历史保留）
- 禁止使用"端点归一化"凑数：必须按 Prometheus `endpoint` label 精确匹配，禁止合并 `/customers/{id}` 与 `/customers/list`
- P0 端点必须**行+分支双守护**：可用性 + P95 延迟 + P99 延迟 + 错误率 四项独立

## 二、Top-20 端点-业务 SLO 映射表

### Tier-P0：业务核心（每条独立 SLO）

| # | 端点 | 业务域 | 调用量权重 | 现有 SLO | 新增 SLO | 目标 | 埋点位置 |
|---|------|--------|----------|---------|---------|------|---------|
| 1 | `POST /api/auth/login` | 认证 | 极高 | ✅ SLO-API-02 (P95<500ms) | SLO-ENDPOINT-01a P99<1s | ≥99.95% 可用 | [auth/login.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/auth/login.py) |
| 2 | `POST /ai/chat/stream` | AI 对话 | 极高 | ✅ SLO-AI-01 首包<1500ms | SLO-ENDPOINT-02a 完整响应 P95<10s | ≥99.5% 可用 | [conversation/routes.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/conversation/routes.py) |
| 3 | `POST /ai/chat/v2` | AI 对话 | 高 | ✅ 共享 SLO-AI-01 | SLO-ENDPOINT-03a P95<8s | ≥99.5% | conversation/routes.py |
| 4 | `GET /api/auth/me` | 认证 | 极高 | ❌ | SLO-ENDPOINT-04a P95<200ms | ≥99.99% | [auth/me.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/auth/me.py) |
| 5 | `POST /api/auth/token/refresh` | 认证 | 高 | ❌ | SLO-ENDPOINT-05a P95<300ms | ≥99.95% | auth/token.py |
| 6 | `GET /customers` | 客户 | 高 | ✅ 共享 SLO-BIZ-01/02 | SLO-ENDPOINT-06a P95<400ms | ≥99.9% | [customer/routes.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/customer/routes.py) |
| 7 | `POST /customers` | 客户 | 高 | ✅ SLO-BIZ-01 (P95<800ms) | SLO-ENDPOINT-07a 写入 P95<1.2s | ≥99.5% | customer/routes.py |
| 8 | `GET /customers/{id}` | 客户 | 高 | ✅ 共享 SLO-BIZ-01 | SLO-ENDPOINT-08a P95<300ms | ≥99.9% | customer/routes.py |
| 9 | `POST /customers/import` | 客户 | 中 | ❌ | SLO-ENDPOINT-09a 大文件 P95<30s | ≥99% | customer/routes.py |
| 10 | `GET /customers/export` | 客户导出 | 中 | ✅ 共享 SLO-BIZ-04 | SLO-ENDPOINT-10a P95<25s | ≥99% | customer/routes.py |
| 11 | `POST /api/ai/parse-single` | 文档识别 | 高 | ✅ 共享 SLO-BIZ-03 | SLO-ENDPOINT-11a P95<4s | ≥99.5% | [excel/routes.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/excel/routes.py) |
| 12 | `POST /api/ai/parse-products` | 文档识别 | 高 | ✅ 共享 SLO-BIZ-03 | SLO-ENDPOINT-12a P95<6s | ≥99% | excel/routes.py |
| 13 | `POST /api/ai/analyze` | AI 分析 | 高 | ✅ 共享 SLO-AI-01 | SLO-ENDPOINT-13a P95<12s | ≥99% | excel/routes.py |
| 14 | `POST /conversations/message` | AI 对话 | 高 | ❌ | SLO-ENDPOINT-14a P95<3s | ≥99.5% | conversation/routes.py |
| 15 | `GET /conversations/sessions` | AI 对话 | 中 | ❌ | SLO-ENDPOINT-15a P95<400ms | ≥99.9% | conversation/routes.py |
| 16 | `GET /products` | 产品 | 高 | ❌ | SLO-ENDPOINT-16a P95<500ms | ≥99.9% | [product/routes.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/domains/product/routes.py) |
| 17 | `GET /products/export.xlsx` | 产品导出 | 中 | ✅ 共享 SLO-BIZ-04 | SLO-ENDPOINT-17a P95<28s | ≥99% | product/routes.py |
| 18 | `POST /tts/synthesize` | TTS | 中 | ❌ | SLO-ENDPOINT-18a P95<2s | ≥99.5% | conversation/routes.py |
| 19 | `POST /mods/install` | MOD | 中 | ✅ 共享 SLO-BIZ-05 | SLO-ENDPOINT-19a P95<60s | ≥99% | [mod_store_routes.py](file:///Users/a4243342/Desktop/XCMAX/FHD/app/fastapi_routes/mod_store_routes.py) |
| 20 | `GET /mods/installed` | MOD | 中 | ❌ | SLO-ENDPOINT-20a P95<300ms | ≥99.9% | mod_store_routes.py |

**注**：编号 `SLO-ENDPOINT-XXa` 表示该端点的首条 SLO；如需追加第二/第三条（如 P99、错误率）用 `XXb/XXc`。

### Tier-P1：业务相关（按业务域聚合）

| 业务域 | 端点数 | 聚合 SLO | 目标 |
|--------|-------|---------|------|
| `/api/auth/*` 其余 | ~22 | SLO-DOMAIN-AUTH P95<800ms + 错误率<0.5% | ≥99.5% |
| `/customers/*` 其余 | ~10 | SLO-DOMAIN-CUSTOMER P95<1.5s + 错误率<1% | ≥99% |
| `/products/*` 其余 | ~30 | SLO-DOMAIN-PRODUCT P95<1s + 错误率<0.5% | ≥99.5% |
| `/ai/*` 其余 | ~15 | SLO-DOMAIN-AI P95<15s + 错误率<1% | ≥99% |
| `/shipment/*` 全部 | ~6 | SLO-DOMAIN-SHIPMENT P95<1s + 错误率<0.5% | ≥99.5% |
| `/excel/*` 其余 | ~5 | SLO-DOMAIN-EXCEL P95<10s + 错误率<1% | ≥99% |
| `/admin_audit/*` 全部 | ~3 | SLO-DOMAIN-ADMIN P95<2s + 错误率<1% | ≥99% |
| `/agent/*` 全部 | ~5 | SLO-DOMAIN-AGENT P95<5s + 错误率<1% | ≥99% |

### Tier-P2：长尾（仅错误率聚合）

| 范围 | SLO | 目标 |
|------|-----|------|
| 全部剩余 ~660 端点 | SLO-DOMAIN-LONGTAIL 错误率 | <1%（周聚合） |

## 三、PromQL 模板

```promql
# P0 端点可用性（示例：SLO-ENDPOINT-01a /api/auth/login）
1 - (
  sum(rate(api_requests_total{endpoint="/api/auth/login", status=~"5.."}[WINDOW]))
  / clamp_min(sum(rate(api_requests_total{endpoint="/api/auth/login"}[WINDOW])), 1)
)

# P0 端点 P95 延迟
histogram_quantile(0.95, sum by (le) (
  rate(api_request_duration_seconds_bucket{endpoint="/api/auth/login"}[WINDOW])
)) * 1000

# P0 端点 P99 延迟
histogram_quantile(0.99, sum by (le) (
  rate(api_request_duration_seconds_bucket{endpoint="/api/auth/login"}[WINDOW])
)) * 1000

# Tier-P1 业务域聚合 P95
histogram_quantile(0.95, sum by (le) (
  rate(api_request_duration_seconds_bucket{endpoint=~"/api/auth/.*"}[WINDOW])
)) * 1000

# Tier-P2 长尾错误率（仅 5xx 聚合）
sum(rate(api_requests_total{
  endpoint!~"/api/auth/login|/ai/chat/stream|...top20...",  # 用正则负向匹配
  status=~"5.."
}[WINDOW])) / clamp_min(sum(rate(api_requests_total[WINDOW])), 1)
```

## 四、复刻覆盖率六铁律的 SLO 守护机制

| 覆盖率铁律 | SLO 守护对应 | 落地脚本 |
|----------|------------|---------|
| 铁律1 全量 source=[app] | 全量 763 端点必须分桶（无 Tier 之外） | `scripts/observability/slo_endpoint_ratchet.py --audit` |
| 铁律2 pragma: no cover 审批 | 端点移出 Top-20 需审批 + 历史 SLO 保留 | 同上 `--move-out` |
| 铁律3 不只测 happy path | 端点必须守护 4 个维度：可用性/P95/P99/错误率 | 同上 `--check` |
| 铁律4 Mock 最小化 | 埋点必须真实路由调用，禁止 mock api_requests_total | 代码 review |
| 铁律5 覆盖率可复现 | SLO 计算只用 Prometheus 真实数据，禁止 seed 数据 | CI 校验 |
| 铁律6 分支 ≠ 行覆盖 | P95 ≠ P99，独立守护 | PromQL 自动生成 |

## 五、CI 守护脚本（棘轮）

新增 `FHD/scripts/observability/slo_endpoint_ratchet.py`：

```bash
# 每日凌晨由 slo-metrics-collect.yml 调用
python scripts/observability/slo_endpoint_ratchet.py --check     # 检查 SLO 是否破线
python scripts/observability/slo_endpoint_ratchet.py --bump      # 实测超越目标时上调 floor
python scripts/observability/slo_endpoint_ratchet.py --top20     # 从 Prometheus 重排 Top-20
python scripts/observability/slo_endpoint_ratchet.py --audit     # 校验 763 端点全覆盖（无漏 Tier）
```

**棘轮 floor 文件**：`FHD/metrics/slo_endpoint_baseline.json`

```json
{
  "_note": "Top-20 端点 SLO 棘轮基线（只升不降）。复刻 coverage_ratchet_baseline.json 思路。",
  "updated": "2026-07-18",
  "endpoint_slo_floors": {
    "/api/auth/login": {"availability": 99.95, "p95_ms": 500, "p99_ms": 1000},
    "/ai/chat/stream": {"availability": 99.5, "p95_ms": 10000, "ttfb_ms": 1500}
  },
  "last_measured": {
    "/api/auth/login": {"availability": 99.98, "p95_ms": 380, "p99_ms": 720}
  }
}
```

## 六、v1 → v2 修正路线

- **v1（今日）**：基于路由分布静态推断 Top-20，落地 5 个最高价值端点（login/chat/stream/customers/parse-single）的完整 SLO
- **v2（7 天后）**：Prometheus `api_requests_total` 7 天数据重排 Top-20，PR 修正本表
- **v3（30 天后）**：基于真实业务价值（每条 SLO 与商业 KPI 挂钩）调整目标值，淘汰"达标但无意义"的 SLO
