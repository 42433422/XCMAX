# 凭据统一托管 · 迁移手册（第一版）

> 用户 2026-10-19 批准的架构改造第三项。本手册只写步骤，**每一步改生产都要用户单独批准后才执行**。
> 全程不得在聊天、日志、工单、PR 或命令行参数里出现任何凭据值。

## 1. 代码里已经就绪的部分

| 位置 | 作用 |
| --- | --- |
| `成都修茈科技有限公司/MODstore_deploy/modstore_server/cred_vault.py` | MODstore（工单 + Para 派发）凭据层：`get_credential(name, task_id, purpose)`、审计、任务短期授权、日志脱敏 |
| `FHD/scripts/autonomy/runtime_tools/credential_vault.mjs` | Mac 执行端（Para 代理 / Codex 包装）同等能力 |
| `FHD/scripts/security/check_plaintext_credentials.py` | CI `gitleaks / credential-guard`：拦新增明文凭据，只输出 文件:行号:规则 |

后端顺序（MODstore 用 `MODSTORE_CREDENTIAL_*`，Mac 用 `XCMAX_CREDENTIAL_*`）：

- `*_CREDENTIAL_BACKENDS`：逗号分隔，默认 `env`；配置了 `*_CREDENTIAL_FILE_DIR` 时默认 `file,env`。
- `file`：目录内一个凭据一个文件，文件名就是变量名，权限必须 `0600`（目录建议 `0700`），否则拒读。
- `vault` / `kms`：只预留接口，选用会明确报「尚未实现」，不会静默回退。

审计位置（只有 谁/何时/任务/用途/后端/结果，没有值）：

- MODstore：`$MODSTORE_CREDENTIAL_AUDIT_DIR`，未设时为 `$MODSTORE_RUNTIME_DIR/credential_audit/credential_access.jsonl`，超过 20MB 轮转一份。
- Mac：`$XCMAX_CREDENTIAL_AUDIT_LOG`，未设时为 `~/.xcmax/credential-audit.jsonl`（`0600`）。

短期授权：MODstore 每次派单签发授权（默认 1 小时，`MODSTORE_CREDENTIAL_GRANT_TTL_SECONDS` 可调，最长 24 小时），
作用域取 `MODSTORE_CREDENTIAL_GRANT_SCOPES`（默认 `OPENAI_API_KEY,CODEX_API_KEY`）。派单提示词末尾只附
`MODSTORE_CREDENTIAL_GRANT={grant_id, task_id, scopes, expires_at}`，不含值和签名。Mac 代理据此审计子进程环境；任务结束即在本机作废。
`MODSTORE_CREDENTIAL_TASK_GRANTS=0` 可关闭签发。

## 2. 第一版做不到、需要后续的部分

- Para 云端不在本仓库，无法新增「凭授权换凭据」接口；授权目前只在 MODstore 与 Mac 代理两端校验和审计，签名供下一版兑换接口使用。
- `MODSTORE_CREDENTIAL_GRANT_SIGNING_KEY` 未配置时，签名用进程内随机钥，只在本进程内可校验。
- Mac 子进程「只给作用域内密钥」默认关闭（`XCMAX_CREDENTIAL_SCOPED_CHILD_ENV=1` 开启），需先在 Mac 上确认 Codex 只依赖作用域内变量或 `~/.codex` 登录态。
- 日志脱敏覆盖：消息文本；异常堆栈原文不改写。

## 3. 生产迁移步骤（待批准，按顺序）

### 3.1 先轮换已公开的凭据（仓库是公开的，删代码不等于失效）

见 PR 报告里的「需轮换」清单。每项：在源系统改密 → 写入新位置（3.2/3.3）→ 验证 → 再作废旧值。

### 3.2 MODstore 服务器（`modstore.env`、`mac-control.env`）

1. 建目录：`install -d -m 0700 -o <服务用户> /etc/xcmax/credentials/modstore`。
2. 逐个把 env 里的密钥迁成文件：变量名即文件名，`install -m 0600 -o <服务用户> /dev/stdin <目录>/<变量名>`，
   值从安全输入框/密码管理器粘贴，**不要**用 `echo 值 >`（会进 shell 历史）。
3. 在 env 里新增 `MODSTORE_CREDENTIAL_FILE_DIR=/etc/xcmax/credentials/modstore`、
   `MODSTORE_CREDENTIAL_BACKENDS=file,env`、`MODSTORE_CREDENTIAL_GRANT_SIGNING_KEY`（新随机值，同样放文件后端）。
4. 重启前先只读核对：按确切变量名检查文件存在、权限 `0600`，不打印内容。
5. 经用户批准重启 MODstore；看 `credential_access.jsonl` 出现 `outcome=hit backend=file`。
6. 稳定一个发布周期后，再经批准从 env 中删除已迁走的明文行（先备份 env，备份权限 `0600`）。
   注意 `modstore.env` 第 132 行有语法错误，迁移前先修。

### 3.3 Mac mini（Para 代理 / Codex）

1. `install -d -m 0700 ~/.xcmax/credentials`，把 `DEVFLEET_DEVICE_TOKEN`、`OPENAI_API_KEY` 等写成 `0600` 文件。
2. LaunchAgent 环境加 `XCMAX_CREDENTIAL_FILE_DIR=~/.xcmax/credentials`（绝对路径），删掉 plist 里的明文值。
3. 用 `install_para_e2e_agent.sh` 重装代理（已包含 `credential_vault.mjs`），确认审计文件有 `para_device_ws` 命中。
4. 观察一轮派单无误后，再设 `XCMAX_CREDENTIAL_SCOPED_CHILD_ENV=1`，确认 Codex 正常、审计里 `mode=scoped`。
5. `~/.codex/config.toml` 不放密钥；Codex 登录态或 API Key 只走作用域内变量。17632 端口旧进程不在本次范围。

### 3.4 测试账号

- SUNBIRD 验收脚本已改为读 `SUNBIRD_ACCOUNT_PASSWORD`；管理员测试账号读 `MODSTORE_ADMIN_PASSWORD`。
- 演示账号、试点商家、E2E 账号：轮换后写入 CI Secrets 与服务器文件后端，再删除仓库里的默认值（另开 PR）。
