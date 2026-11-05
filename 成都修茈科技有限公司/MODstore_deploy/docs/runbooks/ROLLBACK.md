# MODstore 生产回滚

生产采用 `/opt/xcmax/releases/<完整 SHA>` 不可变发行目录；旧的 `/var/www/xiuci-market` 静态双目录步骤已停用。

- 发布、备份、迁移与回滚门禁：[release-checklist.md](./release-checklist.md)。
- 单 CVM 运行与恢复：根仓 `ops/README.md`、`ops/dr/README.md`。
- 回滚后必须核验实际 API 与调度器的完整 SHA、发行版及产物哈希；不得用仅切换静态页代替运行时恢复。
- 固定版本控制器提交与产品提交分别记录。部署回执按工作流文件和 ID 校验来源，再绑定控制器 SHA；实际生产身份始终使用产品 SHA。
- 仅补录已有成功部署的回执时，调度 `modstore-prod-deploy-receipt.yml` 并填写原部署 run ID，不重跑生产部署；无员工包变更时发布步骤正常为空操作。
