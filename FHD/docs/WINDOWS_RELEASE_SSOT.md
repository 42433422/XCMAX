# Windows 发布交付 SSOT

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。每轮按本文件回填事实；实机证据不足不得标记交付完成。
> 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。
> macOS 发布状态见 [MACOS_RELEASE_SSOT.md](MACOS_RELEASE_SSOT.md)。
> Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。

## 1. 当前版本信息

**未闭环。** 产品版本 1.0.0.5；Windows stable OTA 关闭。公开临时下载指针目前指向非 main 构建 3ab4874b17974fae2b52dcabc033f07092206771，SHA-256 9f081078d116859a6ad36eb17aaceb07a86963f9fe6b1449ce7b6092fab0b834。该包的候选清单为 acceptance=NOT_RERUN，不能作为本轮验收包。

#2103 已合并（37fbabed），#2104 已合并（main 83939363）。它们修复市场 API 登录与租户数据读回、首次启动就绪、备份任务注册/参数和解析随包 backend、安装器版本显示及 build-info。对应 exact-main 私有候选 SHA-256 为 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf；隔离 Windows runner 的 clean 与 upgrade 检查通过，含同账号租户身份、记录读回、安装器显示版本、计划任务执行和非空备份文件。原始记录：`C:\xcagi-delivery-closeout\evidence-final-clean\acceptance.json`、`C:\xcagi-delivery-closeout\evidence-final-upgrade\acceptance.json`。这些是 runner/API 验收，不等于客户 GUI 业务链验收，也没有验证恢复后应用读回。

#2096 仍 OPEN 且与 main 冲突。其租户业务页映射和登录后 Mod 路由注册竞态尚未进入 main/上述候选。本轮在 codex/windows-route-backup-fix 从 main 83939363 适配该修复，并补充应用读取备份恢复记录的候选回归；合并并重建前不冻结本轮 RELEASE_SHA。

当前机器实际运行的是旧分支包 3ab4874b，不是 main 候选；其自定义安装目录下备份触发失败不能用于否定 #2104 的主线修复。最新候选的备份脚本从随包脚本目录解析 backend，runner 已成功执行计划任务并生成数据库文件。

## 3. Release Gate 定义

G1–G13 覆盖构建身份、首装、登录绑定、业务、升级、重开、备份恢复及更新；stable OTA 另行保持关闭。

## 4. Release Gate 状态

| Gate | 状态 | 当前证据 / 缺口 |
|---|---|---|
| G1 构建与身份 | YELLOW | main 83939363 私有候选有回执；本轮路由修复尚未合并、未重建 |
| G2 首装 | YELLOW | runner clean 安装通过；客户入口重下及 GUI 首装未完成 |
| G3 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 首次启动 | YELLOW | runner 健康并 readyForUi；客户界面和进程/端口核验未完成 |
| G5 登录、企业与设备绑定 | YELLOW | runner API 登录及 tenant 身份通过；GUI 绑定未验证 |
| G6 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 真实业务与 AI 任务 | UNKNOWN | 当前候选未完成客户/产品、采购、销售、出货、送货单、导出及审批后 AI 执行 |
| G8–G9 stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 覆盖升级读回 | YELLOW | runner 同账号读回原记录通过；真实受支持旧版客户数据 GUI 读回未完成 |
| G11 升级后业务 | UNKNOWN | 未在最终候选上完成客户 GUI 业务 |
| G12 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 备份恢复 | YELLOW | runner 任务产物存在；候选恢复回归待运行，恢复后应用查询及业务界面读取未完成 |

## 6. 实机验收任务

| 轮次 | 必测范围 | 状态 |
|---|---|---|
| A | 最终候选干净首装、GUI 登录绑定、完整采购/销售/出货导出、重开、已审批 AI 实际产物 | 未测 |
| B | 受支持旧版创建记录，记下 ID/企业/工作区/字段；覆盖升级后同账号 GUI 读回并继续业务 | 未测 |
| C | 独立环境或恢复快照；受控故障、授权取消、正式计划任务备份、隔离恢复及应用读取 | 未测 |

三轮必须各自记录运行号、时间、输入、结果和原始证据，且使用同一最终安装器 SHA。stable OTA 不参与本轮。

## 8. 发版复用 Runbook

候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
