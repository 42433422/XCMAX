# Windows 发布交付 SSOT

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。实机证据不足不得标记交付完成。 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。

## 1. 当前版本信息

**未闭环。** 版本1.0.0.5，stable OTA关闭；已测候选RELEASE_SHA f3421f709f585d829029c8da872d3b96708ac86f，安装器SHA-256 b76e145c1067261dccdf86ea0f780d41d9d8eeae4b68b128b31265ccedb3628e，250137389字节、未签名。构建36822897572、实装36824523628。客户指针仍为先前83939363包（SHA-256 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf），本轮未发布；CodeQL3751修复集成后须重新冻结最终包。
#2103/#2104及#2096的#2107替代实现、main #2111–#2114已通过#2109合入上述主线SHA；初始化清理采用#2114，租户输出夹具及实际标准模板断言修复后完整后端37958通过、69跳过。同包四个独立runner的[编号、时间与原始证据索引](evidence/e2e/windows-closeout-20260930/independent-36824523628.json)已核对；完整A/B/C、设备与承诺权益、正常退出重开、自然调度备份及客户入口发布仍缺。同SHA复扫36826287214为0严重、2高危：CodeQL3751与生产内核；冗余空白重复匹配已在工作分支删除，54项否定/审批边界回归通过，仍待主线集成、重建和复扫。用户确认无可用客户测试机/快照；生产内核安装与重启授权待答。

## 3. Release Gate 定义
G1–G13 必须以同一最终安装包的实际结果核销；缺测、失败和阻塞均不得判交付通过。正式调度须核对备份产物，恢复须由应用读回；覆盖升级不计 OTA。
## 4. Release Gate 状态

| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | 已测主线候选36824523628正常设置显示1.0.0.5，包内build-info与运行SHA均为f3421f709；ERP Mod与种子版本1.0.0.3。[实装JSON](evidence/e2e/windows-closeout-20260930/gui-36824523628.json)；客户入口重下未完成 |
| G2 | 首装 | YELLOW | 已测候选干净runner实装与正常GUI业务通过；客户入口重下及完整A轮未完成 |
| G3 | 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 | 首次启动 | YELLOW | 已测候选独立runner首次启动就绪，17500归安装目录后端，数据目录与预期一致。[首装JSON](evidence/e2e/windows-closeout-20260930/acceptance-36824523628-clean.json)；完整A轮未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 36824523628正常GUI企业登录租户1、workspace owner tenant:1；升级及恢复保持同账号与归属。设备绑定及客户账号尚未核销 |
| G6 | 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 | 真实业务与 AI 任务 | YELLOW | 已测候选36824523628 GUI采购入库10、销售、送货单XLSX实际数量2/规格10/重量20/单价12.5/金额250、出库2及库存8；正常审批f771525c7f2047de8ff840fc66ade3ce执行1/1，界面读回AI客户ID2。[原始JSON](evidence/e2e/windows-closeout-20260930/gui-36824523628.json)；完整A/B/C未完成 |
| G8 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G9 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 | 覆盖升级读回 | YELLOW | 36824523628受支持旧版1.0.0.1正常GUI创建客户/产品ID1，已测候选覆盖后同账号、租户1及owner tenant:1正常界面读回原ID及关键字段。[旧版输入](evidence/e2e/windows-closeout-20260930/gui-36824523628-seed.json)、[升级读回](evidence/e2e/windows-closeout-20260930/gui-36824523628-upgrade.json)；完整B轮未核销 |
| G11 | 升级后业务 | YELLOW | 同已测候选升级后GUI创建客户/产品ID2，完成采购入库、销售、送货单导出、出库及库存8；审批63b51a1ced234225980007fdccb1c886执行1/1，界面读回AI客户ID3。[原始JSON](evidence/e2e/windows-closeout-20260930/gui-36824523628-upgrade.json)；完整B轮未核销 |
| G12 | 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 | 备份恢复 | YELLOW | 已测候选Daily/Weekly经任务引擎手动启动生成1880064字节备份，SHA-256 e382df7a91fe6de56102501fcd455d278bb9bec9fdd6bf20d9d184409a67e559；隔离恢复同账号GUI读回旧版客户/产品ID1及关键字段。[调度JSON](evidence/e2e/windows-closeout-20260930/acceptance-36824523628-upgrade.json)、[旧数据读回](evidence/e2e/windows-closeout-20260930/gui-36824523628-legacy-restored.json)。另独立runner库存999拒绝保持8，正常拒绝审批cedca1730e054606a85c0a5de9a0823b未执行且客户不存在：[故障JSON](evidence/e2e/windows-closeout-20260930/gui-36824523628-recovery.json)。自然到点触发未测，完整C轮未完成 |

## 6. 实机验收任务

| 轮次 | 必测范围 | 状态 |
|---|---|---|
| A | 最终候选干净首装、GUI 登录绑定、完整采购/销售/出货导出、重开、已审批 AI 实际产物 | 首装/业务已实测；绑定、权益及正常重开未测 |
| B | 受支持旧版创建记录，记下 ID/企业/工作区/字段；覆盖升级后同账号 GUI 读回并继续业务 | 升级/继续业务已实测；完整B轮未核销 |
| C | 独立环境或恢复快照；受控故障、授权取消、正式计划任务备份、隔离恢复及应用读取 | 故障/取消/恢复已实测；自然调度未测 |

## 8. 发版复用 Runbook

候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
