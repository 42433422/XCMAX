# Windows 发布交付 SSOT
> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。实机证据不足不得标记交付完成。 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。

## 1. 当前版本信息
**未闭环。** 版本1.0.0.5、stable OTA关闭；当前已测候选RELEASE_SHA 91c73f2c576799f42c6d8600871d4bd497f9669a，安装器SHA-256 f7c5eb4a006267634e758b1abe0af20b6a6cb6643cd8964a4f6f928f340b7733，250135221字节、未签名。构建36850651269；[冻结身份](evidence/e2e/windows-closeout-20260930/frozen-91c73-36850651269.json)与[实际包内资源](evidence/e2e/windows-closeout-20260930/resources-91c73-36850651269.json)一致，#2115修复已入包、ERP Mod与行业种子均1.0.0.4。36852779407四个独立runner完成首装、GUI业务、故障取消与旧版升级恢复，[同包原始索引](evidence/e2e/windows-closeout-20260930/independent-36852779407.json)、[实际导出字段](evidence/e2e/windows-closeout-20260930/export-36852779407.json)、[旧版ID及归属读回](evidence/e2e/windows-closeout-20260930/legacy-comparison-36852779407.json)已核对；完整A/B/C、绑定权益、正常退出重开、自然调度未核销。[新建发货单位GUI核销](evidence/e2e/windows-closeout-20260930/shipment-unit-36855210625.json)及[升级后同项回归](evidence/e2e/windows-closeout-20260930/gui-36855210625-upgrade.json)：正常界面新建、刷新重选查询记录ID1，数量2/规格10/重量20/单价12.5/金额250；36855210625本轮独立输入，未复用36852779407素材。客户指针仍为83939363包（SHA-256 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf），本轮未发布。 历史两次全量扫描均仅生产内核TSSA-2026:1026高危阻塞，内核安装重启授权待答；用户确认无可用测试机/快照。#2096由#2107替代，#2103/#2104及#2113/#2114已纳入主线；历史5197原始证据保留。
## 3. Release Gate 定义
下表5197历史证据不得替代91c73复验；G1–G13必须以同一最终安装包核销；缺测、失败和阻塞均不得判交付通过。正式调度须核对备份产物，恢复须由应用读回；覆盖升级不计 OTA。
## 4. Release Gate 状态
| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | 已测主线候选36841870956正常设置显示1.0.0.5，包内build-info与运行SHA均为5197dd66；ERP Mod与种子版本1.0.0.3。[实装JSON](evidence/e2e/windows-closeout-20260930/gui-36841870956.json)；客户入口重下未完成 |
| G2 | 首装 | YELLOW | 已测候选干净runner实装与正常GUI业务通过；客户入口重下及完整A轮未完成 |
| G3 | 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 | 首次启动 | YELLOW | 已测候选独立runner首次启动就绪，17500归安装目录后端，数据目录与预期一致。[首装JSON](evidence/e2e/windows-closeout-20260930/acceptance-36841870956-clean.json)；完整A轮未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 36841870956正常GUI企业登录租户1、workspace owner tenant:1；升级及恢复保持同账号与归属。设备绑定及客户账号尚未核销 |
| G6 | 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 | 真实业务与 AI 任务 | YELLOW | 已测候选36841870956 GUI采购入库10、销售、送货单XLSX实际数量2/规格10/重量20/单价12.5/金额250、出库2及库存8；正常审批00be44612187457b90aea908fa14b90a执行1/1，界面读回AI客户ID2。[原始JSON](evidence/e2e/windows-closeout-20260930/gui-36841870956.json)；完整A/B/C未完成 |
| G8 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G9 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 | 覆盖升级读回 | YELLOW | 36841870956受支持旧版1.0.0.1正常GUI创建客户/产品ID1，已测候选覆盖后同账号、租户1及owner tenant:1正常界面读回原ID及关键字段。[旧版输入](evidence/e2e/windows-closeout-20260930/gui-36841870956-seed.json)、[升级读回](evidence/e2e/windows-closeout-20260930/gui-36841870956-upgrade.json)；完整B轮未核销 |
| G11 | 升级后业务 | YELLOW | 同已测候选升级后GUI创建客户/产品ID2，完成采购入库、销售、送货单导出、出库及库存8；审批8f6a1f772b604c7087e1329db1c23458执行1/1，界面读回AI客户ID3。[原始JSON](evidence/e2e/windows-closeout-20260930/gui-36841870956-upgrade.json)；完整B轮未核销 |
| G12 | 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 | 备份恢复 | YELLOW | 已测候选Daily/Weekly经任务引擎手动启动生成1880064字节备份，SHA-256 262fc221c584f14b9539429d590e1ec89e03e9bc76069ebc34cf8bed922f00ef；隔离恢复同账号GUI读回旧版客户/产品ID1及关键字段。[调度JSON](evidence/e2e/windows-closeout-20260930/acceptance-36841870956-upgrade.json)、[旧数据读回](evidence/e2e/windows-closeout-20260930/gui-36841870956-legacy-restored.json)。另独立runner库存999拒绝保持8，正常拒绝审批e10f5511f0144398b17d9b1a274c250c未执行且客户不存在：[故障JSON](evidence/e2e/windows-closeout-20260930/gui-36841870956-recovery.json)。自然到点触发未测，完整C轮未完成 |
## 6. 实机验收任务
## 8. 发版复用 Runbook
候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
