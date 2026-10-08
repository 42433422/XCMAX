# Windows 发布交付 SSOT
## 1. 当前版本信息
> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域；Gate 仅用 GREEN/YELLOW/RED/UNKNOWN。判据：[真实机协议](e2e/desktop-real-machine-acceptance-protocol.md)；[未签名风险决策](../config/windows_signing_acceptance.json)。历史证据保持原样，失败须修复后实装重测。
**未闭环。** 2026-10-08：#2184已合入 main `edf274051b0e6cb5e5d25d99c2bbeb3cb0cf857b`；对应私有 Windows 候选 1.0.0.5、250115722字节、SHA-256 `8b54e1773c25240314e5900bb785c2cb2f934bdbb321b33aeb50605415d36060`，独立A经正常NSIS向导安装完成，但首启 `/api/ping` 180000ms超时；后台随后真实就绪，托盘正常退出后重开到登录页，不能覆盖首启失败。已登记本轮五项：许可公司名乱码、CI跳过既有WPF安装界面、冷初始化超时且失败页不恢复、Windows系统键遮挡注册/购买、未登录先显示通用助理且会话404后跳登录。许可UTF8签名、真实代理探测及入口避让仅为待接入#2186的审阅补修；冷启动与登录时序待修、安装界面待恢复路径审查，均须准确main新包实机复验。原始截图/日志保留在隔离证据区；连续录屏、TEST客户正常UI输入和16节点冻结复验仍未完成，不能笼统记为缺权限。官网604ab1531/公共后台201d1f69未部署本轮候选；安全处置、同客户原始工单、AI接单、客户关闭及发布授权仍待落实，stable OTA关闭。以下历史记录不能替代本轮证据。
原始运行 `WIN-VM-REGRESSION-F16373D-20261006-001`：[运行索引](evidence/e2e/windows-closeout-20261006/run.json)、[销售订单字段](evidence/e2e/windows-closeout-20261006/sales-order-persistence-diagnostic.json)。f16373d[正常重下文件](evidence/e2e/windows-closeout-20261006/redownloaded-inventory.content.json)核销空白子窗口；沿用旧任务文件不计新AI执行。旧be136e3的[库存Excel字段](evidence/e2e/windows-closeout-20261005/ai-inventory-downloaded.content.json)仅核销该包空表故障。#2096由#2107替代，#2103/#2104已入主线；[5197历史](evidence/e2e/windows-closeout-20260930/gui-36841870956.json)不能替代同一最终包复验。
## 3. Release Gate 定义
GREEN须本最终包实测通过；YELLOW为有限证据或过渡方案，RED为实测失败/门禁阻塞，UNKNOWN为未测；PR与CI不能替代客户验收。
## 4. Release Gate 状态
| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | f16373d安装与运行身份、17500所属后端已核对；最终冻结和客户入口重下未完成 |
| G2 | 首装 | YELLOW | 本轮f16373d为既有A测试机正常覆盖安装；干净首装完整A轮未完成 |
| G3 | 签名 | YELLOW | 当前包NotSigned；仅允许未签名过渡交付，不得称正式签名发布 |
| G4 | 首次启动 | RED | 复现：[本轮A原始截图/日志及五项登记](evidence/e2e/final-acceptance-1.0.0.5/windows-first-start-20261008/run.json)：EDF首启180000ms超时，迟到就绪和正常重开未核销失败；修复#2186后须新main包重测 |
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
