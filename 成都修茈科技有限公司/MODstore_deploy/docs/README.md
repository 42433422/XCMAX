# MODstore 文档

- **性能与容量公开基线**（k6 摘要、复现命令、与 FHD 脚本对照）：[`perf-benchmark-public.md`](perf-benchmark-public.md)。
- **定位（推荐主入口）**：扩展的制作、校验、与 `XCAGI/mods` 同步，以本目录 **独立 MODstore Web**（`MODstore/web` + `modstore_server`）为准；XCAGI 主前端 `/mod-store` 默认嵌入该站点，仅将「本机 .xcmod 简易目录」作为兼容入口。
- **API（自动生成）**：服务启动后访问 Swagger UI `/docs`、ReDoc `/redoc`、OpenAPI JSON `/openapi.json`。
- **制作向导（Web `/author`）**：展示内置 `extension_surface.json`（manifest/蓝图约定）；可合并宿主 `openapi.json` 中 `/api*` 路由摘要；各 Mod 详情「蓝图/API」页签静态扫描 `backend/blueprints.py`。
- **架构决策（ADR）**：[docs/adr/](adr/) 目录。
- **贡献指南（代码分层与门禁）**：[CONTRIBUTING.md](../CONTRIBUTING.md) — T1 核心 / T2 脚本 / T3 兼容层 / T4 生成产物。
- **公网 Catalog（/v1）**：`modstore_server` 挂载 `GET/POST /v1/*`；数据目录由环境变量 `MODSTORE_CATALOG_DIR` 控制（默认 `modstore_server/catalog_data/`）；上传需 `Authorization: Bearer <MODSTORE_CATALOG_UPLOAD_TOKEN>`。CLI：`modman publish <zip> --catalog-url URL --token TOKEN`（需 `pip install httpx`）。

## 运行环境与 Uvicorn（必读）

- **Python 版本**：`pyproject.toml` 中 `requires-python = ">=3.10"`。请勿使用系统自带的 **Python 3.6** 或 `/usr/local/bin/uvicorn` 指向 3.6 的环境启动服务，否则会在 `from __future__ import annotations` 或 `dict | None` 等处直接报错。
- **推荐做法**：安装 **Python 3.10+**（如 3.11），单独建虚拟环境，在虚拟环境内安装依赖并启动：

```bash
cd /path/to/MODstore_deploy
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[web]"
uvicorn modstore_server.app:app --host 127.0.0.1 --port 8000
```

- 腾讯云 TencentOS / CentOS 系可先查仓库是否提供 `python3.11` 包；若无，可用 [pyenv](https://github.com/pyenv/pyenv)、官方源码编译，或用自带 **Python 3.10+** 的容器镜像部署同一套代码。

### 跨域（CORS）

- **公网若经 Nginx**：请确认 **`/api/` 请求先到 Flask**（仓库根目录 `app.py` 反代 + CORS），而不是 Nginx 直接把 `/api/` `proxy_pass` 到 Uvicorn；否则浏览器预检永远收不到 Flask 写入的 CORS 头。参考 **`deploy/nginx-api-via-flask.conf.example`**。
- 若暂时无法让请求经过 Flask，可在 **Nginx 层** 为 `/api/` 统一注入 CORS 并处理 OPTIONS（与上游是 Flask 还是 Uvicorn 无关）：**`deploy/nginx-xiu-ci-api-cors.conf.example`**。
- 前端与 API **不同源**（例如页面在 `https://*.edgeone.cool`、API 在 `https://xiu-ci.com`）时，必须在 API 进程配置允许的来源。
- 环境变量 **`CORS_ORIGINS`**：逗号分隔的完整 Origin 列表；设置后**仅**使用列表中的地址（不再使用代码里的默认开发域名列表，需自行包含生产前端域名）。
- 环境变量 **`CORS_ORIGIN_REGEX`**：单个正则，与 `CORS_ORIGINS` 叠加匹配；设为 `0` / `false` / `none` / `-` 可关闭。未设置时默认允许 `https://*.edgeone.cool`（腾讯云 EdgeOne 预览域名）。
