# release_train 与固定版本发布

日更编排的意图、版本计划与生产发布回执必须分开核验；编排完成不表示软件已上线。

- 版本计划：`FHD/config/release_train.json`；日更编排实现：`modstore_server/daily_orchestrator*`。
- 正式发布门槛、备份、迁移、冒烟与回退：[release-checklist.md](./release-checklist.md)。
- 固定版本审批：主线中的 `ops/releases/<完整 SHA>.json`。审批绑定准确版本、产品号、预期生产版本、完整 CI 和全量安全扫描。
- 从 `main` 手动调度 `modstore-prod-deploy.yml`；`git_sha` 始终保持批准版本。主线随后推进不把新增变更自动纳入交付。
- 正常 PR 检查、完整测试、扫描和部署健康门禁均不可降为 advisory。缺证据即停止；不能用非 HEAD 开关、手工 SCP 或配置热补替代正式入口。
- 生产版本与审批快照不一致时停止，防止覆盖其他执行方的新发布；固定版本产物只从批准 SHA 构建。
- 生产状态以 `/api/health` 的 SHA、发行版、产物哈希及 API/调度器实际状态为准。部署失败必须核验回退后的同一身份。
- 单 CVM 监控、备份和异地恢复按根仓 `ops/README.md`、`ops/dr/README.md` 执行，不假设 Grafana、Compose 应用服务或旧工作树路径仍在使用。
- 日更、邮件审批、商店签名、COS 与桌面发布不因 MODstore 固定版本获批而自动获得授权；按各自既有流程处理。

当前流程取代旧的按服务器 `.env`、手动静态推送与“测试 advisory”拼接的发布说明。未闭环项目仍须报告真实阻塞。
