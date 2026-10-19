# MODstore 发布门禁

## 固定版本与证据

正式入口为根仓 `modstore-prod-deploy.yml`，只允许从 `main` 调度。`git_sha` 是完整 40 位已合入产品版本；控制器 SHA 单独记录，产物不得跟随最新主线漂移。
通过正常 PR 在 `ops/releases/<git_sha>.json` 记录审批引用、范围、产品版本、预期生产 SHA，以及同 SHA 成功的完整 CI 和全量安全扫描 run。扫描须在 24 小时内，零 critical/high、零未处置密钥；无需重复同 SHA 扫描。
构建前、迁移前、切换前均核对生产版本；与审批快照不同即停止。保留备份、迁移、健康、原子切换、失败回退及异地同步门禁。

## 执行核验

- [ ] CI、变更范围、预发数据库迁移和冒烟通过；支付变更完成 `docs/PAYMENT_GRAY_RELEASE.md` 预检。
- [ ] 按 [disaster-recovery.md](./disaster-recovery.md) 完成当前 systemd 部署的备份和恢复能力核验；旧 Compose 备份命令不适用于生产。
- [ ] 轻量压测通过；重跑正式容量基线时更新 [perf-benchmark-public.md](../perf-benchmark-public.md)。
- [ ] 记录时间、产品 SHA、控制器 SHA、操作者和部署 run；逐步检查健康、5xx、p95、支付代理、Java heap/Hikari。
- [ ] 生产冒烟和登录、市场、支付计划、钱包、订单查询通过；路由变更时公网 `/api/xcmax/admin/modules`、`/api/xcmax/sync/status` 返回 200。
- [ ] API、调度器与公网健康返回同一产品 SHA、发行版及产物哈希；观察至少 15 分钟无新增 P0/P1，核验 `ops/README.md` 哨兵。
- [ ] 部署回执绑定原成功 run，控制器与产品分别核验；无员工包变更的发布为空操作，不计为员工包已发布。

P0 链路持续 5 分钟不可用、支付/钱包未知 5xx 或一致性风险、迁移导致核心查询失败，或 p95 超过 SLO 两倍且 15 分钟内无法定位时，按 [ROLLBACK.md](./ROLLBACK.md) 回退并核验实际运行身份。
