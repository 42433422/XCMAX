# Windows 发布交付 SSOT

> 登记于 [SSOT_INDEX.md](SSOT_INDEX.md)「windows-release」域。每轮按本文件回填事实；实机证据不足不得标记交付完成。
> 判据：[desktop-real-machine-acceptance-protocol.md](e2e/desktop-real-machine-acceptance-protocol.md)；签名风险决策：[windows_signing_acceptance.json](../config/windows_signing_acceptance.json)。
> macOS 发布状态见 [MACOS_RELEASE_SSOT.md](MACOS_RELEASE_SSOT.md)。
> Gate 状态仅用 `GREEN`/`YELLOW`/`RED`/`UNKNOWN`；`RED` 须附复现步骤、证据链接及修复 PR/commit，修复后重测，不得直接改状态。

## 1. 当前版本信息

**未闭环。** 版本 1.0.0.5，stable OTA 关闭。2026-09-30 客户指针实测为 main 83939363、SHA-256 92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf；其说明仍误写 macOS 稳定版。本轮最终安装器尚未冻结。
#2103/#2104 已进入 83939363，私有包 clean/upgrade runner 验证了 API 登录、同账号 tenant/记录读回、版本、备份执行与产物。原始记录位于 `C:\xcagi-delivery-closeout\evidence-final-clean\acceptance.json`、`C:\xcagi-delivery-closeout\evidence-final-upgrade\acceptance.json`；不能核销 GUI 业务或恢复后应用读取。
#2096 的路由映射与 Mod 注册竞态由 #2107 进入 main e5b2412；服务器磁盘耗尽导致的配对 503 已恢复，预发 36715937308 已运行同 SHA。36712593205 attempt 2 实装通过，私有包 SHA-256 59019c31309dc1803546afc06d221745e28b9856f17b6f0aceab1da0fe3e3733；隔离验收 36729760481 首装与旧版登录均超时，36731164250 确认 30 秒 HttpClient.Timeout。全源扫描 36716312096 有 3 严重、61 高危阻塞；#2109 修复待保护检查，最终包未冻结。没有可用干净测试机/快照，GUI、AI、真实升级和 A/B/C 均未完成。

## 3. Release Gate 定义（G1–G13 覆盖构建身份、首装、登录绑定、业务、升级、重开、备份恢复及更新）

## 4. Release Gate 状态

| Gate | 项目 | 状态 | 当前证据 / 缺口 |
|---|---|---|---|
| G1 | 构建与身份 | YELLOW | main e5b2412ace 实装通过，私有包哈希核对一致；#2109 未合入，最终包未冻结 |
| G2 | 首装 | YELLOW | runner clean 安装通过；客户入口重下及 GUI 首装未完成 |
| G3 | 签名 | YELLOW | 过渡包未签名，风险接受有效；安装时须核 SHA-256 |
| G4 | 首次启动 | YELLOW | runner 健康并 readyForUi；客户界面和进程/端口核验未完成 |
| G5 | 登录、企业与设备绑定 | YELLOW | 原生 PostgreSQL 恢复后，同包 36732341444 clean/upgrade 通过；[36737817121 正常 GUI 登录及租户 1](evidence/e2e/windows-closeout-20260930/gui-36737817121.json)通过；设备绑定未核销 |
| G6 | 权益、Mod、AI 员工 | UNKNOWN | 本轮候选未完成界面核验 |
| G7 | 真实业务与 AI 任务 | RED | [36748365998](evidence/e2e/windows-closeout-20260930/gui-36748365998.json)：分支私有包 d85c4ff3/18D4B30A 的客户 ID=1、产品 ID=1 创建和界面读回通过；采购入口被行业画像及企业菜单过滤。#2109 补菜单/租户路由映射，45 项针对性测试通过，待新包；销售、出货、导出、AI 未测 |
| G8 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G9 | stable OTA | YELLOW | stable OTA 保持关闭；覆盖升级不计 OTA |
| G10 | 覆盖升级读回 | YELLOW | runner 同账号读回原记录通过；真实受支持旧版客户数据 GUI 读回未完成 |
| G11 | 升级后业务 | UNKNOWN | 未在最终候选上完成客户 GUI 业务 |
| G12 | 退出重开 | UNKNOWN | 旧包历史证据不能替代最终候选复验 |
| G13 | 备份恢复 | YELLOW | [36732341444](evidence/e2e/windows-closeout-20260930/upgrade-36732341444.json)：正式 daily 执行、产物及隔离恢复后同账号 API 读回通过；weekly 执行及 GUI 读取未完成 |

## 6. 实机验收任务

| 轮次 | 必测范围 | 状态 |
|---|---|---|
| A | 最终候选干净首装、GUI 登录绑定、完整采购/销售/出货导出、重开、已审批 AI 实际产物 | 未测 |
| B | 受支持旧版创建记录，记下 ID/企业/工作区/字段；覆盖升级后同账号 GUI 读回并继续业务 | 未测 |
| C | 独立环境或恢复快照；受控故障、授权取消、正式计划任务备份、隔离恢复及应用读取 | 未测 |

三轮必须各自记录运行号、时间、输入、结果和原始证据，且使用同一最终安装器 SHA。stable OTA 不参与本轮。

## 8. 发版复用 Runbook

候选包使用 release-desktop.yml 的 windows_installer_only=true、candidate_only=true 私下构建；验收全过后才按风险接受授权发布临时下载指针，并从客户入口完整下载核对 SHA-256、版本、build-info、说明与证据。未发布只能报告「候选验收通过，发布未完成」。最终 INTERIM_CLOSED 只表示未签名过渡交付验收闭环，不代表 stable OTA 开放。
