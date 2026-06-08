# 组件化发布契约（拆仓前的统一门禁）

本文件是 CI 拆分与部署解耦之后，Python / Node / Java 三个组件的"发布契约"。
它规定了每个组件的版本号来源、健康检查端口、回滚步骤与禁止跨语言的边界。

> 配套脚本：
> - Python：[`MODstore_deploy/scripts/python-release.sh`](../../scripts/python-release.sh)
> - Node：[`MODstore_deploy/scripts/node-release.sh`](../../scripts/node-release.sh)
> - Java：[`MODstore_deploy/scripts/java-release.sh`](../../scripts/java-release.sh)
>
> 配套部署工作流（GitHub Actions）：
> - `deploy.yml`（Backend Python）
> - `market-live-deploy.yml`（Market frontend）
> - `deploy-payment-java.yml`（Payment Java）

## 1. 边界约束

1. 每个发布脚本只做一件事；禁止在 Python 脚本里跑 `npm`/`mvn`，反之亦然。
2. 跨语言的全链发布（旧脚本 `remote_sync_extract.sh` / `_remote_deploy_extract.sh`）已标记
   `[DEPRECATED]`，需显式设 `MODSTORE_ALLOW_LEGACY_FULLCHAIN=1` 才能继续使用；
   Phase 3 完成后将删除。
3. 每个部署入口的 `workflow_run` 只监听对应组件的 CI：
   - Backend 监听 `CI - Backend Python`
   - Market 监听 `CI - Market`
   - Payment-Java 监听 `CI - Payment Java`

## 2. 版本号来源

| 组件 | 版本号来源 | 打包产物 |
| --- | --- | --- |
| Python (`modstore_server`) | `MODstore_deploy/pyproject.toml` `project.version` + `git rev-parse --short HEAD` | `.venv` + editable install（源码直跑，无 wheel 发布） |
| Node (`market`) | `MODstore_deploy/market/package.json` `version` + `git rev-parse --short HEAD` | `MODstore_deploy/market/dist/` |
| Java (`java_payment_service`) | `pom.xml` `<version>` + `git rev-parse --short HEAD` | `target/*.jar` |

**约定**：发布完成后在服务器 `/opt/modstore/releases.log`（或 systemd journal）追加一行
`<timestamp> <component> <version>-<sha> deployed` 以便排障时对齐版本。

## 3. 健康检查端口

| 组件 | 健康路径 | 默认监听端口 | 备注 |
| --- | --- | --- | --- |
| Python FastAPI | `/api/health` | 9999 或 8765 或 8000 | `MODSTORE_API_HEALTH_PORTS` 可覆盖探测顺序；脚本按序重试最多 120s |
| Java Spring Boot | `/actuator/health` | 8080 | 冷启动 30-90s 属正常；脚本最多等待 120s |
| Market | 由 nginx 直接 serve `dist/`，不单独做健康探测 | 80（nginx） | 通过 `wget -qO- http://127.0.0.1/nginx-health` 即可 |

## 4. 回滚步骤（按组件）

### Python
```bash
cd $BACKEND_DIR
git reset --hard <previous-sha>
bash scripts/python-release.sh
```
若 `pip install -e` 因依赖冲突失败，可回退到上一次工作版本：`git stash && git checkout <prev>`，
再次运行 `python-release.sh`。

### Market
```bash
cd $MARKET_DIR
git reset --hard <previous-sha>
bash ../scripts/node-release.sh
```
`dist/` 由 nginx 静态服务；构建失败时不会覆盖旧 `dist/`，天然回滚。

### Java
```bash
cd $PAYMENT_DIR
git reset --hard <previous-sha>
bash ../scripts/java-release.sh
```
若需保留上版 JAR，可在 `java-release.sh` 之前 `cp target/*.jar /opt/modstore/releases/`。

## 5. 未拆仓兼容

- GitHub Actions 部署工作流优先读组件级 `Variables`（`DEPLOY_BACKEND_REMOTE_DIR` /
  `DEPLOY_MARKET_REMOTE_DIR` / `DEPLOY_PAYMENT_REMOTE_DIR`）。
- 若仅设置 `DEPLOY_REMOTE_REPO`，会自动映射到 `${REPO}/MODstore_deploy[/market|/java_payment_service]`，
  过渡期可继续工作。
- 三个变量都不设置时，workflow 会**失败而不是**回落到硬编码的 `/root/成都修茈科技有限公司`；
  这是刻意设计，避免误发布。

## 6. 拆仓后的工作流迁移

当组件抽离到独立仓库时：
1. 对应 `.github/workflows/ci-*.yml` + `deploy-*.yml` 随源码迁走。
2. 本仓库删除对应工作流，避免双触发。
3. 新仓库继续使用相同的组件化发布脚本（复制到新仓库 `scripts/` 目录）。
4. 健康检查端口与回滚步骤保持不变。
