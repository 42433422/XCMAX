# XCAGI Mod 沙箱镜像

本目录集中存放 Mod 沙箱「最小镜像」的 **Dockerfile、构建脚本、说明**。构建上下文仍须为**仓库根**（脚本会自动拼装一份最小临时目录后 `docker build`）。

用于在**单容器**内验证 Mod 能否被扫描、加载并挂载路由；镜像层仅包含运行主栈所需文件（不含 `frontend/`、`MODstore/`、`docs/` 等）。主程序仍为明文 `app/**/*.py`；更强防护见仓库内 Mod 沙箱方案说明（字节码 / Nuitka 等为后续阶段）。

## 本目录内容

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 多阶段 Mod 沙箱镜像 |
| `context.dockerignore` | 与 `docker build --ignorefile` 联用，缩小 build context |
| `build.ps1` / `build.sh` | 在仓库根执行，无需 `--ignorefile` |
| `README.md` | 本说明 |

## 构建

### 方式 A（推荐，任意 Docker 版本）

在**仓库根目录**执行；脚本会拼装最小 context 再 `docker build`，无需 `--ignorefile`：

```powershell
powershell -ExecutionPolicy Bypass -File docker/mod-sandbox/build.ps1
```

```bash
bash docker/mod-sandbox/build.sh
```

### 方式 B（Docker 23+ 且支持 `--ignorefile`）

在仓库根目录：

```bash
docker build --ignorefile docker/mod-sandbox/context.dockerignore -f docker/mod-sandbox/Dockerfile -t xcagi-mod-sandbox .
```

## 运行（SQLite + 挂载 mods）

将解压后的 Mod 目录挂载到容器内 `/mods`（与 `XCAGI_MODS_ROOT` 一致）。示例（Linux / macOS）：

```bash
docker run --rm -p 127.0.0.1:5000:5000 \
  -e DATABASE_URL=sqlite:////app/data/sandbox.db \
  -e VECTOR_DB_URL=sqlite:////app/data/sandbox_vectors.db \
  -e XCAGI_MODS_ROOT=/mods \
  -e XCAGI_NEURO_INTENT=0 \
  -e FLASK_DEBUG=0 \
  -e XCAGI_MOD_SANDBOX=1 \
  -e SECRET_KEY=sandbox-not-for-production \
  -v "$(pwd)/path/to/your_mods_parent:/mods:ro" \
  xcagi-mod-sandbox
```

说明：

- `path/to/your_mods_parent` 下应为**多个 Mod 目录**（每个子目录含 `manifest.json`），与线上一致；若只有一个 Mod，该目录本身应作为 `/mods` 的内容（即挂载点下直接是 `your_mod_id/manifest.json`）。
- `XCAGI_MOD_SANDBOX=1`：关闭 `/docs`、`/redoc`（见 `XCAGI/run_fastapi.py`）。
- **Redis**：多数缓存为懒加载；未起 Redis 时，**不保证**所有业务 API 可用。本镜像目标为 **Mod 加载 + 基础 HTTP（如 `/health`）+ 你自行对 Mod 路由的冒烟**。
- **AGPL**：仓库为 AGPL v3；若向第三方分发镜像或二进制，请自行确认许可证下的源码提供义务。

## 可选：docker compose 片段

将 Mod 父目录换成你的本地路径后，可与 `docker compose -f docker-compose.mod-sandbox.yml up` 同类方式使用（需自建 yml，或从下列片段复制）：

```yaml
services:
  mod-sandbox:
    image: xcagi-mod-sandbox:latest
    ports:
      - "127.0.0.1:5000:5000"
    environment:
      DATABASE_URL: sqlite:////app/data/sandbox.db
      VECTOR_DB_URL: sqlite:////app/data/sandbox_vectors.db
      XCAGI_MODS_ROOT: /mods
      XCAGI_NEURO_INTENT: "0"
      FLASK_DEBUG: "0"
      XCAGI_MOD_SANDBOX: "1"
      SECRET_KEY: sandbox-not-for-production
    volumes:
      - /path/to/mods_root:/mods:ro
```

## Windows（PowerShell）示例

```powershell
docker run --rm -p 127.0.0.1:5000:5000 `
  -e DATABASE_URL=sqlite:////app/data/sandbox.db `
  -e VECTOR_DB_URL=sqlite:////app/data/sandbox_vectors.db `
  -e XCAGI_MODS_ROOT=/mods `
  -e XCAGI_NEURO_INTENT=0 `
  -e FLASK_DEBUG=0 `
  -e XCAGI_MOD_SANDBOX=1 `
  -e SECRET_KEY=sandbox-not-for-production `
  -v E:/path/to/mods_root:/mods:ro `
  xcagi-mod-sandbox
```

## 验收

1. 容器日志出现 Mod 扩展加载相关信息。
2. `curl -fsS http://127.0.0.1:5000/health` 返回 200。
3. 按需请求 Mod 注册的 API 路径做 1～2 条冒烟。

## 构建与运行注意事项

- **PyAudio**：Dockerfile 的 builder 阶段已安装 `portaudio19-dev`；若自行改依赖仍从源码编 PyAudio，需保留该包。
- **`openai` SDK**：主栈 `app/fastapi_routes/xcagi_compat.py` 等在 import 期需要 `openai`；已在 [`XCAGI/requirements.txt`](../../XCAGI/requirements.txt) 声明 `openai>=1.40.0`。若 worker 启动报 `ModuleNotFoundError: openai`，请重新构建镜像。
- **Redis**：未启动 Redis 时，不保证所有依赖缓存的 API 可用；本镜像目标仍为 **Mod 加载 + `/health` + 自选 Mod 路由**。
- **镜像体积**：当前与主栈共用完整 `XCAGI/requirements.txt`（含 torch 等），首次构建与 `exporting layers` 可能较慢，属预期行为。

## 冒烟记录（维护者本地）

在 `DATABASE_URL` / `VECTOR_DB_URL` 使用 `sqlite:////app/data/...`、`XCAGI_MODS_ROOT=/mods`、挂载 `XCAGI/mods` 只读目录的前提下（示例见上文 `docker run`）：

1. **`GET /health`**：返回 200，JSON 含 `status` / `timestamp` 等（与 [`app/fastapi_routes/ai_assistant.py`](../../app/fastapi_routes/ai_assistant.py) 中实现一致）。
2. **示例 Mod**：若挂载目录中含 `example-mod`，**`GET /api/mod/example-mod/hello`** 应返回 200 及 `Hello from example-mod!` 类 payload（见 `XCAGI/mods/example-mod/backend/blueprints.py`）。

若 worker 因 **`PermissionError`** 在 `/app/config`、`/app/templates` 等路径 `makedirs` 失败，请使用当前镜像（Dockerfile 已对 `/app` 作 `chown` 以允许 `appuser` 在仓库根下创建子目录）。若遇 **`ModuleNotFoundError`**，先确认已按 [`XCAGI/requirements.txt`](../../XCAGI/requirements.txt) 完整构建（含 `openai` 等），再查容器日志。
