# Windows 发布交付 SSOT
## 1. 当前版本信息
> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域；Gate 仅用 GREEN/YELLOW/RED/UNKNOWN。判据：[真实机协议](e2e/desktop-real-machine-acceptance-protocol.md)；[未签名风险决策](../config/windows_signing_acceptance.json)。历史证据保持原样，失败须修复后实装重测。
**未闭环。** 当前实装候选为主线 #2165 `f16373d1eb7f59a5e27b289e72c8df9329cacb02`、1.0.0.5，私有构建37336952721；安装器250233484字节、SHA-256 `3d2ecb78b96304db89f1384d7d8c8187828a2d55b21fe14988f1d7154c8291a7`、未签名。运行后端与包内身份一致；这是冻结前定向回归，未完成最终冻结、A/B/C及发布，stable OTA关闭。
原始运行 `WIN-VM-REGRESSION-F16373D-20261006-001`：[运行索引](evidence/e2e/windows-closeout-20261006/run.json)、[销售订单字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)。旧be136e3的[库存Excel字段](evidence/e2e/windows-closeout-20261005/ai-inventory-downloaded.content.json)仅核销该包空表故障。#2096由#2107替代，#2103/#2104已入主线；[5197历史](evidence/e2e/windows-closeout-20260930/gui-36841870956.json)不能替代同一最终包复验。
## 3. Release Gate 定义
GREEN须本最终包实测通过；YELLOW为有限证据或过渡方案，RED为实测失败/门禁阻塞，UNKNOWN为未测；PR与CI不能替代客户验收。
## 4. Release Gate 状态
| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | f16373d安装与运行身份、17500所属后端已核对；最终冻结和客户入口重下未完成 |
| G2 | 首装 | YELLOW | 本轮f16373d为既有A测试机正常覆盖安装；干净首装完整A轮未完成 |
| G3 | 签名 | YELLOW | 当前包NotSigned；仅允许未签名过渡交付，不得称正式签名发布 |
| G4 | 首次启动 | YELLOW | 新后端PID9588从安装目录启动并进入SUNBIRD首页；完整干净A/C未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 同账号界面读回P006/W006库存20；设备绑定、工作区归属完整验收未完成 |
| G6 | 权益、Mod、AI员工 | RED | 复现：SUNBIRD正常登录→员工平台→员工空间，考勤AI助手未启用、已托管0；[实机证据](evidence/e2e/windows-closeout-20261005/normal-employee-space-not-ready.png)。#2163 SDK源修复仍待正式部署，生产内核TSSA-2026:1026门禁阻塞 |
| G7 | 真实业务与AI任务 | RED | 复现：f16373d正常审批入口和拒绝已实测；SALES ORDER 2 P006 A006 10→正常审批→SO20261006004727金额20，但product_model被忽略，订单行产品ID/名称为空；[字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)、[审批输入](evidence/e2e/windows-closeout-20261006/normal-sales-create-order-correct-approval.png)；修复6375eea15690cd1c40b89b6c04ea1b11e4edc46f后须换包复验及完成出库、单据、导出、UI查询 |
| G8 | stable通道 | YELLOW | stable OTA保持关闭；本轮尚未发布客户下载指针 |
| G9 | OTA升级 | YELLOW | 本轮OTA关闭，覆盖安装与升级证据不得记为OTA通过 |
| G10 | 覆盖升级读回 | UNKNOWN | 支持旧版B002/PB02原ID证据已保留；最终同包升级及同账号界面读回未完成 |
| G11 | 升级后业务 | UNKNOWN | 最终候选B轮新增业务未完成 |
| G12 | 退出重开 | UNKNOWN | 旧cfa230d正常退出零进程再开读回20已实测；不能替代最终候选复验 |
| G13 | 备份恢复与故障取消 | UNKNOWN | cfa230d正式Daily产物已核对，Weekly自然触发及最终同包隔离恢复应用读回未完成；f16373d[正常拒绝错误请求](evidence/e2e/windows-closeout-20261006/normal-approval-rejected-pending-zero.png)后库存仍20；不能替代最终C轮 |
## 6. 实机验收任务
最终同包独立A首装完整业务、B受支持旧版原ID同账号读回并新增、C故障取消与正式调度备份隔离恢复；每轮独立时间、输入、结果及原始证据，未完成项保持未闭环。
## 8. 发版复用 Runbook
验收全过后才按既有授权发布临时下载指针，重新从客户入口完整下载核对哈希、版本、运行构建、说明及原始证据；候选验收通过但未发布须报告「候选验收通过，发布未完成」。最终INTERIM_CLOSED仅表示未签名过渡交付闭环，stable OTA仍关闭。
