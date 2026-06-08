# 本地到服务器推送 / 部署流程说明

面向在 **Windows（PowerShell）** 上操作、目标为 **单机 Linux（SSH）** 的典型场景。与你当前机器的配置类似：SSH 配置文件里可加 `Host` 别名，`remote-sre` / `sync` 脚本里则用 `-SshTarget` 传入 `root@IP` **或该别名**（例如 `tencent-cvm`）。

> 更深入的单机 SRE（备份、回滚、`scheduler` 等）：见 [remote-server-operations.md](./remote-server-operations.md)。

---

## 先有的事：本机环境与 SSH

1. **能非交互登录**：本机装好 OpenSSH 客户端，`ssh Key`/`~/.ssh/config` 已对目标主机配好，`ssh -o BatchMode=yes your-host` 不报密码交互。
2. **服务器路径约定**：
   - **Docker / Git 拉代码**：常见 **`/root/modstore-git`**，下面有 **`MODstore_deploy`**（与 `scripts/remote_sre_ops.sh` 的探测逻辑一致）。
   - **宿主机 systemd + Python**：`modstore.service` 的 `WorkingDirectory`、`ExecStart` 必须指向**同一棵** `/…/MODstore_deploy`，否则表现为「同步了代码但跑的仍是旧目录」。
3. **减少每次敲参数**：在 `MODstore_deploy` 下放 **`deploy-target.local.ps1`**（已 gitignore），可从范例复制改名：

```powershell
Copy-Item deploy-target.local.ps1.example deploy-target.local.ps1
```

在 `deploy-target.local.ps1` 中设置 `$env:DEPLOY_SSH`、`$env:DEPLOY_REMOTE_REPO`、`$env:DEPLOY_GIT_BRANCH` 后，`remote-sre.ps1` 会自动读入。

---

## 路线一：远端 Git + Docker Compose（推荐：与 `remote-server-operations.md` 一致）

**含义**：不把本机源码树整体推上去，而是由**服务器在自己的 clone 里** `git fetch/reset`，再用 **`docker compose --profile app up -d --build`** 构建并启动（含 **`api`、`market`、`scheduler`、payment、postgres、rabbitmq、redis** 等，视 compose 而定）。

**入口**：在 `MODstore_deploy` 下执行：

```powershell
.\scripts\remote-sre.ps1 `
  -Action deploy `
  -SshTarget tencent-cvm `
  -RemoteRepo /root/modstore-git `
  -Branch main
```

**远端实际顺序**（[`scripts/remote_sre_ops.sh`](../../scripts/remote_sre_ops.sh)）：

1. **preflight**：检查 Git、Docker、Compose、磁盘、`docker compose config`
2. **`git fetch` + `git reset --hard origin/<branch>`**
3. **`python scripts/backup_modstore.py`**
4. **`docker compose --profile app up -d --build`**
5. **`python scripts/sre_smoke_check.py`**（HTTP 探测 + **校验 `scheduler` 服务为 running**）

**发布前你的工作**：把要上线的提交 **push 到服务器拉取的远端仓库**（例如 `origin/main`）。

**顺带装 Docker**：若机器上还没有 Docker，可用 [`scripts/ssh-install-docker-and-deploy.ps1`](../../scripts/ssh-install-docker-and-deploy.ps1)：`install_docker_engine.sh` → 再调上面的 `deploy`。

---

## 路线二：`sync-modstore-to-server.ps1`（ tarball + 远端全链解压构建）

**适用**：希望把**当前本机工作区**（含未 push 的修改）打成包推到服务器；远端走 **解压 + pip/npm/mvn（及 systemd 重启）** 的传统链路，而不是「纯 Git reset + 容器 build」。

**入口**：

```powershell
cd MODstore_deploy
.\scripts\sync-modstore-to-server.ps1 -SshTarget tencent-cvm
```

可选：

- **`$env:DEPLOY_REMOTE_BASE`** 或脚本参数 **`-RemoteBase`**：服务器上的**父目录**（默认等价于 `/root/modstore-git`，脚本里经 Base64 固定为 ASCII）。
- **`-AlignSystemd`**：同步完成后上传并执行 [`scripts/align_modstore_systemd_to_deploy.sh`](../../scripts/align_modstore_systemd_to_deploy.sh)，把 `modstore.service` drop-in 指到 **`$RemoteBase/MODstore_deploy`**。

**本机侧大致步骤**（[`scripts/sync-modstore-to-server.ps1`](../../scripts/sync-modstore-to-server.ps1)）：

1. 在公司仓库根用 **tar** 打 **`modstore_deploy_sync.tgz`**（排除 `.venv`、`node_modules`、`dist`、Java `target`、本地库与运行时目录等）。
2. 若存在与公司根同级的 **`yuangon/``，会一并打进包。
3. **scp**：`tgz` + **`remote_sync_extract.sh`** + **`remote_sync_bootstrap.sh`** + 远程基底路径（Base64 单行文件）。
4. **ssh** 执行 **`remote_sync_bootstrap.sh`** → 设置 **`MODSTORE_ALLOW_LEGACY_FULLCHAIN=1`** 后调用 **`remote_sync_extract.sh`**。

**远端 `remote_sync_extract.sh` 要点**（[`scripts/remote_sync_extract.sh`](../../scripts/remote_sync_extract.sh)）：

- 文档中标为 **legacy / deprecated**，仍可被 sync 脚本以显式环境变量放行。
- **备份 `.env`**、必要时备份 SQLite/运行时目录，再按 tar **顶层目录整树覆盖解压**，还原 `.env` 与状态目录。
- 后续执行 pip / npm / mvn、`systemctl` 重启等（脚本后半部分；与「是否全盘 Docker」可并存于你司当前混合架构）。

**与你路线一的区别**：这里是「**本机树 = 真源**」；路线一是「**远端 clone = 真源**」。

---

## 路线三：只更新 Market 前端（Git 在远端拉代码 + npm build）

**入口**：[`scripts/push-market-to-server.ps1`](../../scripts/push-market-to-server.ps1)

```powershell
.\scripts\push-market-to-server.ps1 -SshTarget tencent-cvm
```

- 默认远端目录可能是 **`RemoteRepo`/…**：脚本默认里曾出现 **`/root/成都修茈科技有限公司`** ——请以你机器上的 **`DEPLOY_REMOTE_REPO`** 与实际 clone 为准。
- 可加 **`-GitPush`**：会先在本仓库根 **`git push origin <Branch>`**，再 SSH 远端 **`git fetch`、`reset --hard`、`npm install`、`npm run build`**（设置 `VITE_PUBLIC_BASE=/market/`）。

这只动 **Vue market**，不替你发布 Python/Java 后端。

---

## 常用环境与动作速查

| 变量 / 脚本 | 作用 |
| --- | --- |
| `DEPLOY_SSH` | SSH 目标，如 `root@x.x.x.x` 或 `Host` 别名 |
| `DEPLOY_REMOTE_REPO` / `RemoteRepo` | 服务器上 Git 仓库根目录（内含 `MODstore_deploy`） |
| `DEPLOY_GIT_BRANCH` / `Branch` | `deploy`、`push-market` 使用的分支 |
| `DEPLOY_REMOTE_BASE` | `sync-modstore-to-server.ps1` 的服务器解压父路径 |
| `remote-sre.ps1 -Action preflight\|smoke\|backup\|deploy\|rollback` | [remote-server-operations](./remote-server-operations.md) 中的标准动作 |

---

## 流程对照（我该用哪条？）

```text
需要先 push 到 Git，服务器只拉镜像/compose 重建？
  → 路线一 remote-sre deploy（或 ssh-install-docker-and-deploy）

本机有一批未提交的改动，整块覆盖到服务器宿主树？
  → 路线二 sync-modstore-to-server.ps1（注意 legacy 与 systemd 对齐）

只改 Vue 前端、后端不动？
  → 路线三 push-market-to-server.ps1
```

若生产使用 **Compose** 且要走路线一：务必保证发布后 **`scheduler` 与其它 `app` profile 服务一起 up**，否则会缺后台定时任务（见运维手册「后台任务」一节）。
