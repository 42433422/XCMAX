# Windows 发布交付 SSOT
## 1. 当前版本信息
> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域；Gate 仅用 GREEN/YELLOW/RED/UNKNOWN。判据：[真实机协议](e2e/desktop-real-machine-acceptance-protocol.md)；[未签名风险决策](../config/windows_signing_acceptance.json)。历史证据保持原样，失败须修复后实装重测。
**未闭环。** 2026-10-07：私有主线候选 15b7180b 的安装器 SHA256 6d0a78be…49176ad 已核验，新 A 虚拟机的安装/登录仍待独立核实；生产 CVM 已获授权升级并重启至 5.4.241-24.0017.44，九项关键服务正常，yum 无待修安全公告。集成 #2179 包含前端覆盖率修复 b1d4a4bd0 与历史启动修复的替代提交 3f55745f8，尚未合入；最终冻结、同包 A/B/C、两次独立安全扫描和客户入口重下仍待完成。以下保持上轮实装证据：候选为主线 #2165 `f16373d1eb7f59a5e27b289e72c8df9329cacb02`、1.0.0.5，私有构建37336952721；安装器250233484字节、SHA-256 `3d2ecb78b96304db89f1384d7d8c8187828a2d55b21fe14988f1d7154c8291a7`、未签名。运行后端与包内身份一致；这是冻结前定向回归，未完成最终冻结、A/B/C及发布，stable OTA关闭。25道最终闸门2026-10-06为0 GREEN（[gates.json](evidence/e2e/final-acceptance-1.0.0.5/gates.json)）；主线604ab1531安装包仅做只读[预演核验](evidence/e2e/final-acceptance-1.0.0.5/prefreeze-artifacts-604ab1531.json)，未实装，不替代冻结候选。
原始运行 `WIN-VM-REGRESSION-F16373D-20261006-001`：[运行索引](evidence/e2e/windows-closeout-20261006/run.json)、[销售订单字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)。f16373d[正常重下文件](evidence/e2e/windows-closeout-20261006/redownloaded-inventory.content.json)核销空白子窗口；沿用旧任务文件不计新AI执行。旧be136e3的[库存Excel字段](evidence/e2e/windows-closeout-20261005/ai-inventory-downloaded.content.json)仅核销该包空表故障。#2096由#2107替代，#2103/#2104已入主线；[5197历史](evidence/e2e/windows-closeout-20260930/gui-36841870956.json)不能替代同一最终包复验。
## 3. Release Gate 定义
GREEN须本最终包实测通过；YELLOW为有限证据或过渡方案，RED为实测失败/门禁阻塞，UNKNOWN为未测；PR与CI不能替代客户验收。
## 4. Release Gate 状态
| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | f16373d安装与运行身份、17500所属后端已核对；最终冻结和客户入口重下未完成 |
| G2 | 首装 | YELLOW | 本轮f16373d为既有A测试机正常覆盖安装；干净首装完整A轮未完成 |
| G3 | 签名 | YELLOW | 当前包NotSigned；仅允许未签名过渡交付，不得称正式签名发布 |
| G4 | 首次启动 | YELLOW | f16373d后端PID4068从安装目录启动并进入SUNBIRD首页；完整干净A/C未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 同账号界面读回P006/W006库存20；设备绑定、工作区归属完整验收未完成 |
| G6 | 权益、Mod、AI员工 | RED | 复现：f16373d SUNBIRD正常员工空间开关已启用、托管1待命1；[定位](evidence/e2e/windows-closeout-20261006/g6-panorama-triage.json)确认[企业全景](evidence/e2e/windows-closeout-20261006/normal-enterprise-panorama-enabled-mod-not-ready.png)L1/L2/L4暂无员工Mod为预期渲染（承诺仅attendance_ai，归L3服务层），非授权或代码缺陷；缺口：最终包实机由L3考勤ai助手完成一次考勤表转化；#2163已入主线604ab1531待正式部署，生产内核TSSA-2026:1026已核销；新主线安全扫描及授权Mod实机验收待完成 |
| G7 | 真实业务与AI任务 | RED | 复现：f16373d正常审批入口和拒绝已实测；SALES ORDER 2 P006 A006 10→正常审批→SO20261006004727金额20，但product_model被忽略，订单行产品ID/名称为空；[字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)、[审批输入](evidence/e2e/windows-closeout-20261006/normal-sales-create-order-correct-approval.png)；对话另报[最大迭代失败](evidence/e2e/windows-closeout-20261006/normal-sales-conversation-max-iterations.png)，审批后[原运行与任务仍待审批](evidence/e2e/windows-closeout-20261006/post-approval-run-task-diagnostic.json)；修复#2168后须换包复验及完成出库、单据、导出、UI查询 |
| G8 | stable通道 | YELLOW | stable OTA保持关闭；本轮尚未发布客户下载指针；10-06公网曾由灾备节点接管（/xcagi-v*/与/releases/回落为首页HTML），16:50Z DNS回切旧主后stable feed latest.yml为404，下载页仍列出临时包83939363（[可用性](evidence/e2e/production-availability-20261006/run.json)） |
| G9 | OTA升级 | YELLOW | 本轮OTA关闭，覆盖安装与升级证据不得记为OTA通过 |
| G10 | 覆盖升级读回 | UNKNOWN | 支持旧版B002/PB02原ID证据已保留；最终同包升级及同账号界面读回未完成 |
| G11 | 升级后业务 | UNKNOWN | 最终候选B轮新增业务未完成 |
| G12 | 退出重开 | UNKNOWN | 旧cfa230d正常退出零进程再开读回20已实测；不能替代最终候选复验 |
| G13 | 备份恢复与故障取消 | UNKNOWN | cfa230d正式Daily产物已核对，Weekly自然触发及最终同包隔离恢复应用读回未完成；f16373d[任务与进程](evidence/e2e/windows-closeout-20261006/backup-registration-and-runtime-20261006.json)仅证明注册、未触发；f16373d[正常拒绝错误请求](evidence/e2e/windows-closeout-20261006/normal-approval-rejected-pending-zero.png)后库存仍20；不能替代最终C轮 |
## 6. 实机验收任务
最终同包独立A首装完整业务、B受支持旧版原ID同账号读回并新增、C故障取消与正式调度备份隔离恢复；每轮独立时间、输入、结果及原始证据，逐项记入[windows-a/b/c.run.json](evidence/e2e/final-acceptance-1.0.0.5/)，未完成项保持未闭环。
## 8. 发版复用 Runbook
验收全过后才按既有授权发布临时下载指针，重新从客户入口完整下载核对哈希、版本、运行构建、说明及原始证据；候选验收通过但未发布须报告「候选验收通过，发布未完成」。最终INTERIM_CLOSED仅表示未签名过渡交付闭环，stable OTA仍关闭。
