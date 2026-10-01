# Windows 发布交付 SSOT

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。实机证据不足不得标记交付完成。
> 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。

## 1. 当前版本信息

**未闭环。** 版本 1.0.0.5，stable OTA 关闭。2026-09-30 客户指针实测为 main 83939363、SHA-256 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf；其说明仍误写 macOS 稳定版。本轮最终安装器尚未冻结。
#2103/#2104 已进入83939363；#2096由#2107进入main e5b2412替代；main #2111/#2112已纳入#2109集成分支，待保护检查与合入。历史API诊断原始记录在 `C:\xcagi-delivery-closeout\evidence-final-clean\acceptance.json`、`C:\xcagi-delivery-closeout\evidence-final-upgrade\acceptance.json`，不能核销GUI业务。配对503已恢复；最新诊断扫描36800587594仍有2严重、37高危（根Python依赖已清零，7个子锁文件14项urllib3告警已定向修复，待复扫；主线告警与内核仍阻塞），最终SHA复扫未完成。用户无可用客户测试机/快照，独立Windows runner继续实装验证；最终包、A/B/C和客户发布未完成。

## 3. Release Gate 定义

G1–G13 必须以同一最终安装包的实际结果核销；缺测、失败和阻塞均不得判交付通过。正式调度须核对备份产物，恢复须由应用读回；覆盖升级不计 OTA。

## 4. Release Gate 状态

| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | fa63a729f私有包SHA-256 ead6b24e0d4f7def97c79f0f725533719c220cb76af1d776294fcad6be7ce4cb实算一致；36800629547/36802110909运行后端与安装身份相符。#2109未合入，最终主线包未冻结 |
| G2 | 首装 | YELLOW | runner clean 安装通过；客户入口重下及 GUI 首装未完成 |
| G3 | 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 | 首次启动 | YELLOW | runner 健康并 readyForUi；客户界面和进程/端口核验未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 原生 PostgreSQL 恢复后，同包 36732341444 clean/upgrade 通过；[36737817121 正常 GUI 登录及租户 1](evidence/e2e/windows-closeout-20260930/gui-36737817121.json)通过；设备绑定未核销 |
| G6 | 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 | 真实业务与 AI 任务 | YELLOW | 同一fa63a729f安装包36800629547完整11项GUI业务通过：采购入库10、销售订单、送货单文件内容、出库2、界面库存8；正常对话审批c39905ca3f6b4baa9bb8a7a0d3d170c6执行后读回AI客户ID2、原名、联系人AI验收员和电话13800000002。原始证据C:\xcagi-delivery-closeout\evidence-fa63-gui-36800629547。独立复跑36802110909登录定位失败已修正，仍须同一最终包A/B/C |
| G8 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G9 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 | 覆盖升级读回 | YELLOW | 1.0.0.1安装身份2e6f03bf、哈希ed957f9d核对通过；36793964883客户ID1与姓名/联系人/电话/地址均已实际保存并由界面加载。旧界面地址列误显示“-”，并非数据丢失；产品保存响应不返回ID，后续从界面加载列表取得原始ID再覆盖升级，尚未通过 |
| G11 | 升级后业务 | UNKNOWN | 未在最终候选上完成客户 GUI 业务 |
| G12 | 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 | 备份恢复 | YELLOW | fa63a729f包36802110909：Daily/Weekly正式调度均成功产生1945600字节备份，SHA-256 c2006afbd6fa35d1445c2a3998efaf61fda79a8b8e0a10063117b5928a48397b；隔离恢复同账号GUI读回客户/产品ID1及客户联系人、电话、地址。授权拒绝0b410f9f28c04fb4be321859e4b56790未执行且界面无取消客户。原始证据C:\xcagi-delivery-closeout\evidence-fa63-recovery-36802110909；工作区字段null，最终包未冻结，不计最终C轮 |

## 6. 实机验收任务

| 轮次 | 必测范围 | 状态 |
|---|---|---|
| A | 最终候选干净首装、GUI 登录绑定、完整采购/销售/出货导出、重开、已审批 AI 实际产物 | 未测 |
| B | 受支持旧版创建记录，记下 ID/企业/工作区/字段；覆盖升级后同账号 GUI 读回并继续业务 | 未测 |
| C | 独立环境或恢复快照；受控故障、授权取消、正式计划任务备份、隔离恢复及应用读取 | 未测 |

三轮必须各自记录运行号、时间、输入、结果和原始证据，且使用同一最终安装器 SHA。stable OTA 不参与本轮。

## 8. 发版复用 Runbook

候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
