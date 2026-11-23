# Python 依赖锁定与可重复构建

## 当前依赖声明与安装入口

依赖声明以 [`pyproject.toml`](../../pyproject.toml) 为准：`[project.dependencies]` 包含固定 Codex SDK/CLI 和受管 LangGraph 基础运行时；`server-api`、`dev`、`ml` 分别补充服务器、测试与可选 ML/GPU 依赖。所有下列命令都在 `FHD/` 执行。

使用 [`uv.lock`](../../uv.lock) 安装已解析的完整依赖集合：

```bash
uv sync --frozen --extra server-api --extra dev
```

仅安装服务器运行环境时省略 `--extra dev`。`tool.uv.sources` 将 LangGraph 指向仓库内受管源码，固定 Codex SDK/CLI 已是基础依赖，旧 `codex-runtime` extra 只保留安装命令兼容。

既有 pip、桌面构建和容器构建使用 [`requirements-server-api.txt`](../../requirements-server-api.txt)，其中包含基础运行时、服务器依赖和 `./packages/...` 本地源码条目。源码开发环境可按现有 Windows 后端构建方式安装：

```bash
python -m pip install -c ops/deploy/requirements-server-api.lock.txt -r requirements-server-api.txt -e ".[server-api]"
```

[`ops/deploy/requirements-server-api.lock.txt`](../../ops/deploy/requirements-server-api.lock.txt) 约束顶层包的精确版本；它不替代安装清单中的本地源码依赖，也不是完整传递依赖锁。容器和 CI 的实际安装参数以各自构建文件为准。

## 文件职责

| 文件 | 用途 |
|------|------|
| `pyproject.toml` | 基础运行时与各 extra 的依赖声明 |
| `uv.lock` | 主仓完整依赖锁，配合 `uv sync --frozen` 使用 |
| `requirements.txt` | `server-api` extra 的传统清单，不单独提供完整基础运行时 |
| `requirements-ml.txt` | ML/GPU 可选 |
| `requirements-server-api.txt` | CI、部署与桌面安装入口，含固定 SDK/CLI 和仓库内本地包 |
| `ops/deploy/requirements-server-api.lock.txt` | 服务端顶层版本约束与依赖告警的稳定路径 |
| `XCAGI/requirements.txt` / `XCAGI/requirements.lock.txt` | 保留的传统清单与锁身份；旧锁未包含完整固定 Agent 运行时 |

`XCAGI/requirements.lock.txt` 与服务端锁均保留原路径，安全版本维护继续关联原有依赖告警。新安装使用上面的当前入口；现有 Docker 构建已消费 `requirements-server-api.txt`。

## 更新与验证

依赖升级需同步 `pyproject.toml`、对应安装清单与版本约束，并运行 `uv lock` 更新主仓锁。保留锁文件各自的职责，不用旧 `XCAGI` 锁替换主仓解析结果。

```bash
uv lock --check
python scripts/dev/check_requirements_lock.py
python scripts/dev/ssot_plugins/deps.py check
```

`check_requirements_lock.py` 核对服务端安装清单的顶层包是否在约束文件中；`deps.py check` 核对传统 extra 清单的包名集合。这些检查不等于安装或平台验收。当前 CI 入口为仓根 `.github/workflows/fhd-ci-cd.yml` 和 `.github/workflows/fhd-test.yml`，两者均从服务端安装入口准备后端依赖；PostgreSQL 事务任务使用上述 `uv sync --frozen` 命令。
