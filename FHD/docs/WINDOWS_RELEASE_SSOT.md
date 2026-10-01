# Windows 发布交付 SSOT

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。每轮按本文件回填事实；实机证据不足不得标记交付完成。
> 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。
> macOS 发布状态见 [MACOS_RELEASE_SSOT.md](MACOS_RELEASE_SSOT.md)。
> Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。

## 1. 当前版本信息

**未闭环。** 版本 1.0.0.5，stable OTA 关闭。2026-09-30 客户指针实测为 main 83939363、SHA-256 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf；其说明仍误写 macOS 稳定版。本轮最终安装器尚未冻结。
#2103/#2104 已进入83939363；#2096由#2107进入main e5b2412替代；main #2111/#2112已纳入#2109集成分支，待保护检查与合入。历史API诊断原始记录在 `C:\xcagi-delivery-closeout\evidence-final-clean\acceptance.json`、`C:\xcagi-delivery-closeout\evidence-final-upgrade\acceptance.json`，不能核销GUI业务。配对503已恢复；全源扫描36716312096仍有3严重、61高危，最终SHA复扫未完成。用户无可用客户测试机/快照，独立Windows runner继续实装验证；最终包、A/B/C和客户发布未完成。

## 4. Release Gate 状态

| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | main e5b2412ace 实装通过，私有包哈希核对一致；#2109 未合入，最终包未冻结 |
| G2 | 首装 | YELLOW | runner clean 安装通过；客户入口重下及 GUI 首装未完成 |
| G3 | 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 | 首次启动 | YELLOW | runner 健康并 readyForUi；客户界面和进程/端口核验未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 原生 PostgreSQL 恢复后，同包 36732341444 clean/upgrade 通过；[36737817121 正常 GUI 登录及租户 1](evidence/e2e/windows-closeout-20260930/gui-36737817121.json)通过；设备绑定未核销 |
| G6 | 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 | 真实业务与 AI 任务 | RED | 私有86包36792475338已核对SHA-256 091dfb1e77c98b5df0d99b26b502815253a61d343ab8f6ba7eed902804eb17f5；[记录](evidence/e2e/windows-closeout-20260930/gui-36792475338.json)、[日志](evidence/e2e/windows-closeout-20260930/backend-36792475338.log)、[截图](evidence/e2e/windows-closeout-20260930/ai-36792475338.png)：正常采购入库10、订单、文件内容导出、出库2及界面库存8通过；AI审批名称正确且回执称执行完成，返回客户列表未读回新记录。保留完整回执、正常界面刷新后的同包复验36793733617进行中；A/B/C未完成，WinError1314未核销 |
| G8 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G9 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 | 覆盖升级读回 | YELLOW | 1.0.0.1安装身份2e6f03bf、哈希ed957f9d核对通过；36793964883客户ID1与姓名/联系人/电话/地址均已实际保存并由界面加载。旧界面地址列误显示“-”，并非数据丢失；产品保存响应不返回ID，后续从界面加载列表取得原始ID再覆盖升级，尚未通过 |
| G11 | 升级后业务 | UNKNOWN | 未在最终候选上完成客户 GUI 业务 |
| G12 | 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 | 备份恢复 | YELLOW | [36775708452](https://github.com/42433422/XCMAX/actions/runs/36775708452)：私有917包 Daily/Weekly正式调度均产生1691648字节备份；隔离恢复应用的实际数据目录、同账号同企业API读回通过。最终候选未冻结，GUI恢复读取已补入升级流程但尚待实跑，不能判C轮通过 |

## 6. 实机验收任务

| 轮次 | 必测范围 | 状态 |
|---|---|---|
| A | 最终候选干净首装、GUI 登录绑定、完整采购/销售/出货导出、重开、已审批 AI 实际产物 | 未测 |
| B | 受支持旧版创建记录，记下 ID/企业/工作区/字段；覆盖升级后同账号 GUI 读回并继续业务 | 未测 |
| C | 独立环境或恢复快照；受控故障、授权取消、正式计划任务备份、隔离恢复及应用读取 | 未测 |

三轮必须各自记录运行号、时间、输入、结果和原始证据，且使用同一最终安装器 SHA。stable OTA 不参与本轮。

## 8. 发版复用 Runbook

候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
