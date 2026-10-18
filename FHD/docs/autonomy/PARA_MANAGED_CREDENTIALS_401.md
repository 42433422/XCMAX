# Para 受管凭据 401 恢复手册

## 现象
- Mac merge-worker 日志出现 `para auth 401`（新版为 `para auth 401 managed_para_credentials_rejected`），合并队列停摆。
- 设备代理 `request-merge` 同样失败（共用 `requestManagedParaSession`）。

## 结论口径（2026-10-19 只读核查）
- 这是**配置漂移**，不是代码缺陷：`MERGE_WORKER_PARA_CREDENTIALS_FILE` 指向的 owner-login.json 与
  `managed-identity/control-credentials.json` 内容一致，owner 邮箱与 id 也与 Para `users` 表一致，
  但两份文件里的密码都与 `users.password_hash` 校验不通过。
- 首条 401：2026-09-09 04:25（北京时间），即 9 月 9 日 03:18 cutover apply 之后约一小时，此后每 30 秒一条，持续至今。
- 工单类 Para 任务均为 `auto_merge=0`，merge-worker 本就不消费；401 不是工单 40 没开 PR 的原因
  （那是 auto_merge=0 路径缺少开 PR 环节，已在设备代理补上）。

## 恢复步骤（需用户批准；会改生产 Para 凭据）
1. 排空：确认 Para 无 `running/pending` 子任务，备份 `devfleet.db` 与两份凭据文件（0600）。
2. 只做一处真相：新生成 owner 密码，**同一事务**写 `users.password_hash`（bcrypt），再原子替换
   owner-login.json 与 control-credentials.json 的 `password` 字段；全程不打印密码。
3. 自检：用凭据文件调一次 `POST /api/auth/login`，只看 HTTP 状态与 `user.id == owner_id`。
4. merge-worker 不需重启：下一轮轮询会重读文件；日志应出现「队列 N 个任务」或无鉴权报错。
5. 若 401 再次出现，先查是谁改了 `users.password_hash`（备份恢复、手工注册/改密），再重复第 2 步。

## 禁止
- 不得改回 guest 模式绕过；不得把密码写进命令行、日志、聊天或 PR。
