# Mac mini：staging 与 GitHub Actions Self-hosted Runner

本页配合「三层部署」：在 Mac mini 上常驻 Runner，监听 `staging` 分支或 workflow 条件，并设置 **`MODSTORE_DEPLOY_TIER=staging`**（写入 launchd / shell profile / Runner 服务环境）。

## 1. 安装 Actions Runner（GitHub）

1. 仓库 **Settings → Actions → Runners → New self-hosted runner**，按官方步骤在 macOS 上解压 `actions-runner`。
2. `./config.sh --url https://github.com/<org>/<repo> --token <token>`，标签建议：`mac-mini`、`staging`。
3. 用 `svc.sh install` / `svc.sh start` 或 `launchctl` 保持常驻。

## 2. Workflow 要点（示例）

- `on.push.branches: [staging]` 或 `workflow_dispatch`。
- `runs-on: [self-hosted, mac-mini]`（与配置的标签一致）。
- `env`：`MODSTORE_DEPLOY_TIER: staging`、`MODSTORE_REPO_ROOT` 指向本机 clone 路径。
- 步骤：`git pull` → 安装依赖 → 构建/测试 → 部署到本机 Docker 或脚本。

## 3. 与 MODstore 后端

部署在本机的 API 进程请在 `.env` 中设置同一 `MODSTORE_DEPLOY_TIER=staging`，以便 `/api/health` 与「推送更新员工」读取的档位一致。

## 4. 安全

Runner 机器持有仓库与机密：限制登录、启用 FileVault、密钥仅放 GitHub Encrypted secrets / 本机钥匙串，勿把生产密钥放在 staging 机。
