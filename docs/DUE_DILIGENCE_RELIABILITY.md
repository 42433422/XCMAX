# XCMAX 技术尽调：可靠性证据索引

> 尽调交付入口（工作区 `Desktop/XCMAX`）。不含 40GB 历史 `_archive`（见 [ARCHIVE_POINTER.md](../ARCHIVE_POINTER.md)）。

## 产品 SLO

| 产品 | 文档 | 仪表盘 / 规则 |
|------|------|----------------|
| XCAGI / FHD | [FHD/docs/SLO.md](../FHD/docs/SLO.md) | [xcagi-slo.json](../FHD/k8s/monitoring/grafana/dashboards/xcagi-slo.json) |
| MODstore | [sre-operating-model.md](../成都修茈科技有限公司/MODstore_deploy/docs/sre-operating-model.md) | Grafana + [alert_rules](../FHD/k8s/monitoring/) |

## Runbooks

- FHD K8s：[FHD/k8s/monitoring/runbooks/](../FHD/k8s/monitoring/runbooks/)
- MODstore：[MODstore_deploy/docs/runbooks/](../成都修茈科技有限公司/MODstore_deploy/docs/runbooks/)

## 事故复盘（Postmortems）

| 日期 | 标题 |
|------|------|
| 2026-05-04 | [MODstore DR 演练](postmortems/2026-05-04-modstore-drill.md) |
| 2026-06 | [测试污染 / xpassed 收口](postmortems/2026-06-test-pollution-rca.md) |
| 2026-06 | [CI 基线恢复](postmortems/2026-06-ci-baseline-recovery.md) |

## SLA 探针快照

- CI workflow：[FHD/.github/workflows/sla-probe.yml](../FHD/.github/workflows/sla-probe.yml)
- 测试：`FHD/tests/test_sla_health_probe.py`（`release_gate`）
- 落盘样例：[FHD/metrics/sla-snapshot.json](../FHD/metrics/sla-snapshot.json)

## 客户端测试门禁

| 栈 | 命令 | CI |
|----|------|-----|
| FHD 前端 Vitest | `cd FHD/frontend && npm test` | `frontend-unit.yml` |
| FHD Playwright | `cd FHD/frontend && npm run test:e2e` | `e2e.yml` |
| MODstore market | `cd 成都修茈科技有限公司/MODstore_deploy/market && npm run test:coverage && npm run test:e2e` | `ci-market.yml` |
| Android | `cd FHD/mobile-android && ./gradlew testPersonalDebugUnitTest` | `ci-mobile-android.yml` |

API 层移动契约：`FHD/tests/test_mobile_api.py`（非 UI 替代）。

## 代码仓边界（尽调打包）

```bash
# 推荐交付两仓 ZIP，不含 _archive
git -C FHD archive --format=zip -o xcagi-fhd.zip HEAD
git -C 成都修茈科技有限公司/MODstore_deploy archive --format=zip -o modstore.zip HEAD
```
