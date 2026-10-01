# Windows 发布交付 SSOT

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。实机证据不足不得标记交付完成。
> 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。

## 1. 当前版本信息

**未闭环。** 版本 1.0.0.5，stable OTA 关闭。2026-09-30 客户指针实测为 main 83939363、SHA-256 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf；其说明仍误写 macOS 稳定版。本轮最终安装器尚未冻结。
#2103/#2104 已进入83939363；#2096由#2107进入main e5b2412替代；main #2111/#2112/#2113/#2114已纳入#2109集成分支；Mod初始化清理采用#2114主线替代实现并保留三类异常重试回归，36815134200全量检查37956通过、2失败：评估打印夹具未使用租户输出路径、送货单断言仍按旧无模板行位；本轮修正夹具与标准模板业务值/合计断言，局部回归通过，完整保护检查与合入仍待完成。历史API诊断原始记录在 `C:\xcagi-delivery-closeout\evidence-final-clean\acceptance.json`、`C:\xcagi-delivery-closeout\evidence-final-upgrade\acceptance.json`，不能核销GUI业务。配对503已恢复；最新诊断扫描36802829978仍有2严重、23高危（7个子锁文件14项urllib3告警已复扫清零；主线Dependabot、CodeQL身份与生产内核仍阻塞），最终SHA复扫未完成。用户无可用客户测试机/快照，独立Windows runner继续实装验证；最终包、A/B/C和客户发布未完成。

## 3. Release Gate 定义

G1–G13 必须以同一最终安装包的实际结果核销；缺测、失败和阻塞均不得判交付通过。正式调度须核对备份产物，恢复须由应用读回；覆盖升级不计 OTA。

## 4. Release Gate 状态

| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | 19e8af2db包36812420025正常设置显示1.0.0.5，安装与运行SHA一致，实际包内ERP Mod版本1.0.0.3；本地全文件SHA-256 fe2ed5ac44b2f1c8dddf65f4f474b32a4edd37cb86f2b2951600adf4800f64ee。[实装JSON](evidence/e2e/windows-closeout-20260930/gui-36812420025.json)。历史版本缺陷已实装核销；此为分支诊断包，最终主线包未冻结 |
| G2 | 首装 | YELLOW | runner clean 安装通过；客户入口重下及 GUI 首装未完成 |
| G3 | 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 | 首次启动 | YELLOW | 36809497696新隔离runner正常GUI登录；17500属于安装目录内后端，实际AppData目录与预期一致，运行SHA b26ebf748。最终A轮仍未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 36809497696正常GUI企业登录租户1，正常界面响应workspace owner为tenant:1；升级和恢复均保持同账号与归属。设备绑定及客户账号尚未核销 |
| G6 | 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 | 真实业务与 AI 任务 | YELLOW | 19e8af2db包36812420025完整12项GUI通过：采购入库10、销售、送货单XLSX导出、出库2、界面库存8；正常审批239fbab234fc409d92f8496648385a01执行1/1，界面读回AI客户ID2、联系人与电话。[实装JSON](evidence/e2e/windows-closeout-20260930/gui-36812420025.json)；仍须最终包A/B/C |
| G8 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G9 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 | 覆盖升级读回 | YELLOW | b26ebf748同包36811187839：旧版1.0.0.1正常GUI创建客户/产品ID1；覆盖后同账号、租户1及workspace owner tenant:1读回原ID和名称、联系人、电话、地址、型号、规格、单价。[实装JSON](evidence/e2e/windows-closeout-20260930/gui-36811187839-upgrade.json)；最终包未冻结，不计最终B轮 |
| G11 | 升级后业务 | YELLOW | 同包36811187839复测：GUI新建客户/产品ID2，完成采购入库10、销售、送货单导出、出库2与库存8；审批59491dc7b1ec4db48140532da7b6180d执行1/1后界面读回AI客户ID3。[原始JSON](evidence/e2e/windows-closeout-20260930/gui-36811187839-upgrade.json)。前次5秒列表加载失败证据保留，30秒诊断窗口复跑通过；最终主线包仍须复验 |
| G12 | 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 | 备份恢复 | YELLOW | 同一19e8af2db包36813277882：计划任务引擎手动启动Daily/Weekly生成1880064字节备份，SHA-256 6511d13e18e8d57ce09f2deb2957335e9f9c68fed80532a97fe5f136bd5446e4；隔离恢复实际应用同账号、租户1及workspace owner tenant:1读回旧版原始客户/产品ID1和关键字段。[调度证据](evidence/e2e/windows-closeout-20260930/acceptance-36813277882-upgrade.json)、[原数据GUI读回](evidence/e2e/windows-closeout-20260930/gui-36813277882-legacy-restored.json)。同包36812420025库存故障及拒绝授权未写入已验证；自然到点触发未测，最终C轮未完成 |

## 6. 实机验收任务

| 轮次 | 必测范围 | 状态 |
|---|---|---|
| A | 最终候选干净首装、GUI 登录绑定、完整采购/销售/出货导出、重开、已审批 AI 实际产物 | 未测 |
| B | 受支持旧版创建记录，记下 ID/企业/工作区/字段；覆盖升级后同账号 GUI 读回并继续业务 | 未测 |
| C | 独立环境或恢复快照；受控故障、授权取消、正式计划任务备份、隔离恢复及应用读取 | 未测 |

## 8. 发版复用 Runbook

候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
