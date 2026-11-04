# Windows 业务验收

日期：2026-10-10
版本：1.0.0.5
git SHA：`b1f2d0a6a0391d1467394503b27fa97fc17186c0`
安装包 SHA-256：`548eb64999ff64792bb61483aa92d087fbc299c3987b193b5d63f60183cb6949`
设备标识保留在客户数据目录，升级前后未变。本文件不含客户数据库、考勤源表、结果工作簿或登录凭据。

## 1. 真实业务 — PASS

在已登录的 SUNBIRD 企业会话上完成一次考勤转换。

- 转换接口 HTTP 200，`success=true`
- `rows_in=1`，`employees_matched=1`，`personnel_roster_count=1`，`month=2026-10`，无未匹配姓名
- 工作表为「明细」「月度统计」
- 结果工作簿 26251 字节，SHA-256 `8894c8209480d50b87ef4f13bb16ec4a0f7c529e69f0224303716672ebf1d6aa`
- 同一会话下载该结果 HTTP 200，大小和 SHA-256 与落盘文件一致
- 前台点击「考勤」后，对话区出现「打开通用考勤模块」

## 2. 审批规则与读回 — PASS

- 审批规则 HTTP 200：工作日 `08:00-12:00`、`13:30-17:30`，周日空班
- 规则说明 HTTP 200：周一到周六正班同上，周日按加班
- 员工读回 HTTP 200：验收工号 `XCAGI-LOOP-20261009`，所有者 SUNBIRD，共 1 条

## 3. 绑定 — PASS

市场身份 HTTP 200，用户 SUNBIRD，市场用户 id 29。

- 产品登录幂等回执 HTTP 200，`duplicate=true`，设备标识与本机一致，`user_id=29`，`status=installed`。该历史回执的构建 SHA 是更早一次登录的 `df3ab41f75093e473b6ad7bdf8b1adfe765a62db`
- 当前构建另报一条回执，HTTP 200，`duplicate=false`，`user_id=29`，`status=installed`，`installed_build_sha=b1f2d0a6a0391d1467394503b27fa97fc17186c0`

## 4. 备份与恢复 — PASS

打包桌面没有挂载 `POST /api/database/backup`（HTTP 405）。备份入口是随包的 `XcagiBackup.ps1` / `XcagiRestore.ps1`。

按客户数据目录显式备份后，备份文件通过 `xcagi-backend.exe --verify-backup`。完全退出后恢复该备份：测试标记消失，SUNBIRD 会话、验收工号和结果工作簿都还在。重新打开后窗口标题为「智能对话 - XCAGI」。

## 5. 退出后重开 — PASS

进程退出且本地健康检查不可用之后，用同一客户数据目录重新打开。会话校验 HTTP 200，用户 SUNBIRD。考勤状态 HTTP 200，验收工号仍能读回。

## 6. 隔离环境旧版升级 — PASS

旧版 `df3ab41f75093e473b6ad7bdf8b1adfe765a62db` 安装在独立目录，数据使用客户目录的副本，端口 17511。覆盖安装当前公开包后，健康检查 SHA 变为 `b1f2d0a6a0391d1467394503b27fa97fc17186c0`。副本中的验收工号和结果文件 SHA-256 与客户目录一致。

客户实例在此期间保持在 17500。客户目录的安装标识、结果文件大小、SHA-256 和工号读回没有变化。

## 7. 计划任务指向客户数据目录 — PASS

修复前，每日和每周任务只调用备份脚本，没有 `-DataDir`，因此会备份默认的 Roaming 目录，而不是当前客户数据目录。

现已把两个任务登记为客户数据目录。隔离副本上的验证：

- `XcagiDailyBackup` 上次结果 0
- `XcagiWeeklyBackup` 上次结果 0，并生成 weekly 备份
- 恢复 weekly 备份后，隔离库中的测试标记消失，用户仍是 SUNBIRD，验收工号仍在
- 这两次定时执行没有往客户备份目录新增文件
- 验证前后客户结果文件 SHA-256、工号条数和安装构建都没有变化
- 验证结束后，每日任务参数含客户数据目录；每周任务在同一目录上另带 `-Weekly`

后续安装会把默认数据目录写进计划任务。桌面若使用自定义数据目录，启动时会按实际 `userData` 重新登记每日和每周任务。
