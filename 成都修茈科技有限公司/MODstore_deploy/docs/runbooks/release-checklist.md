# 发布门禁 Checklist

## 固定版本发布

正式入口为根仓 `modstore-prod-deploy.yml`，只允许从 `main` 调度。`git_sha` 是完整 40 位已合入版本，不跟随最新主线漂移。
发布前通过正常 PR 在 `ops/releases/<git_sha>.json` 记录用户审批引用、范围、产品版本、预期生产 SHA，以及该 SHA 已成功的完整 CI 和全量安全扫描 run。
入口验证审批、成功 CI 的版本和来源，再独立校验 24 小时内全量扫描零 critical/high、零未处置密钥。单次同 SHA 扫描即可；移除旧的重复扫描下载。
控制脚本从已合入的流程版本执行，交付产物仍只从批准 SHA 构建。构建前、迁移前、切换前均核对生产版本；与审批快照不同即停止，禁止覆盖他人新发布。
保留原有备份、数据库迁移、健康、原子切换、失败回退和异地同步检查。生产单 CVM 告警按 `ops/README.md` 的哨兵状态核验，不假设部署了 Grafana。

## 发布前

- [ ] CI 全部通过。
- [ ] 变更范围已明确，包含回滚方式。
- [ ] 数据库迁移已在预发执行并验证。
- [ ] 支付相关变更已通过 `docs/PAYMENT_GRAY_RELEASE.md` 预检。
- [ ] 备份已完成：`python scripts/backup_modstore.py --components postgres,modstore_data`。
- [ ] 预发冒烟通过：`python scripts/sre_smoke_check.py ...`。
- [ ] 轻量压测通过：`K6_STAGE=smoke k6 run perf/full_link_smoke.js`；若本次为正式容量/回归基线重跑，同步更新 [`docs/perf-benchmark-public.md`](../perf-benchmark-public.md)。
- [ ] 生产哨兵无未处理严重告警。

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
