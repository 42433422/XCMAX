# 发布门禁 Checklist

## CI / Branch protection 映射（Phase A）

以下「GitHub Actions 作业显示名」（Settings → Branches → `main` → Required checks）与上表勾选项对齐；需在仓库 **Branch protection** 中勾选，合并到 `main` 才算满足「CI 全部通过」的自动化部分。

| Checklist | 自动化来源 | Required check 名称（作业 `name`，以仓库 UI 为准） |
|-----------|------------|---------------------------------------------------|
| CI 全部通过（组件） | `.github/workflows` | `Marketing site (static pages)`、`Root project (Vue 3 + Vite)`、`Market subproject (MODstore_deploy/market)`、`MODstore (Python — lint + tests + coverage)`（内含 **`pip-audit`**）、`MODstore (Java payment service)`、`vibe-coding (Python package)`（内含 **`pip-audit`**）、`nginx-t-snippets`（仅当改动命中 nginx workflow 的路径时触发）；Root/Market 前端 job 内含 **`npm audit`** |
| CI 全部通过（全仓提交门禁） | `ci-runtime-artifacts-guard.yml` | `Forbid committed runtime artifacts` |
| 密钥泄露扫描（PR/main） | `secret-scan.yml` | `Secret scan (gitleaks)`（**建议 required**） |
| 轻量压测（发布前可选用） | `performance-smoke.yml`（仅 `workflow_dispatch`） | `k6 full-link smoke`，**不设为 required**：按本清单在发布窗口手动跑一次或接入专用 gate URL（见 [.github/workflows/README.md](../../../.github/workflows/README.md) 中「可选部署前网关」） |
| 支付相关变更 | `docs/PAYMENT_GRAY_RELEASE.md` | **人工 / 专有流程**，无单一 GitHub job |
| DB 迁移、备份、预发冒烟、Grafana | 本清单其余条目 | **人工或外部系统**；可由 `DEPLOY_PREFLIGHT_GATE_URL` 聚合为一条机器门禁（同上 README） |

路径过滤：`paths` 未命中的 CI 对工作流会 **skipped**，通常不阻塞合并；**Runtime Artifacts Guard** 对 `main` 上所有 push/PR 生效，应始终 required。  
完整工作流索引：[.github/workflows/README.md](../../../.github/workflows/README.md)。

## Docker / Serverless 构建算力（评估暂缓）

仓库当前 **不以 GitHub Actions 构建大型 Docker 镜像**（无集中 `docker build` 流水线）；`MODstore_deploy/deploy.sh` 以本机 venv + 可选前端构建为主。  
**暂不**接入 Serverless/弹性 GPU 镜像构建；待引入 CI 镜像构建并具备构建时长与成本数据后，再与发布入口脚本/组件化 `*-release.sh` 一并评审。

## 可选 JSON 部署日志（排障）

在服务器执行 `deploy.sh`、`scripts/python-release.sh`、`scripts/node-release.sh` 时，设置 **`MODSTORE_DEPLOY_LOG_JSON=1`** 可额外输出**单行 JSON**阶段事件（时间与 `deploy-release-officer` 的 pipeline  skill 对齐方向），便于日志采集与告警解析。

---

## 发布前

- [ ] CI 全部通过。
- [ ] 变更范围已明确，包含回滚方式。
- [ ] 数据库迁移已在预发执行并验证。
- [ ] 支付相关变更已通过 `docs/PAYMENT_GRAY_RELEASE.md` 预检。
- [ ] 备份已完成：`python scripts/backup_modstore.py --components postgres,modstore_data`。
- [ ] 预发冒烟通过：`python scripts/sre_smoke_check.py ...`。
- [ ] 轻量压测通过：`K6_STAGE=smoke k6 run perf/full_link_smoke.js`；若本次为正式容量/回归基线重跑，同步更新 [`docs/perf-benchmark-public.md`](../perf-benchmark-public.md)。
- [ ] Grafana 无未处理 P0/P1 告警。

## 发布中

- [ ] 记录发布时间、commit、操作者。
- [ ] 按服务顺序发布：基础设施、Java 支付、FastAPI、market。
- [ ] 每一步执行健康检查。
- [ ] 观察 5xx、p95、支付代理、Java heap/Hikari。

## 发布后

- [ ] 生产冒烟通过。
- [ ] 若本次含 ModStore FastAPI 路由变更：在公网入口（如 systemd `modstore.service` 的 `:9999` 或 compose 映射端口）确认 `GET /api/xcmax/admin/modules` 与 `GET /api/xcmax/sync/status` 返回 200，供 FHD/XCmax 后台联调。
- [ ] 核心业务手工验证：登录、市场、支付计划、钱包、订单查询。
- [ ] 观察至少 15 分钟无新增 P0/P1 告警。
- [ ] 记录发布结果和发现的问题。

## 回滚触发条件

- P0 链路持续 5 分钟不可用。
- 支付/钱包出现未知 5xx 或数据一致性风险。
- 数据库迁移导致核心查询失败。
- p95 延迟超过 SLO 2 倍且无法在 15 分钟内定位。
