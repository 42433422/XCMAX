# XCAGI v7.0 快速开始

> 约 5 分钟跑通本地：**FastAPI 主入口**在 `XCAGI/run.py`（默认 `http://127.0.0.1:5000`）。根目录旧 `backend/http_app.py`（8000 端口）已移除，详见归档说明与 `CHANGELOG.md`。

---

## 前置条件

- **操作系统**：Windows 10/11、Linux 或 macOS  
- **Python**：3.11+（与 `requirements.txt` 一致）  
- **Node.js**：18+（可选，仅前端独立开发时需要）  
- **Redis**：按需（缓存 / 队列）  
- **Git**

验证：

```bash
python --version   # Python 3.11.x+
node --version     # 可选
```

---

## 1. 获取代码

```bash
git clone https://github.com/42433422/ai-excel-helper.git
cd ai-excel-helper
```

（若远程为历史 `xcagi` 仓库名，与上同源树等价，以你实际克隆地址为准。）

---

## 2. 安装依赖（仓库根）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. 配置环境变量

在仓库根或 `XCAGI/` 下按项目约定放置 `.env`（可参考 `resources/config/.env.example` 或各模块文档）。至少配置数据库、密钥等生产必填项。

---

## 4. 数据库迁移

迁移脚本位于仓库根 `alembic/`：

```bash
alembic upgrade head
```

---

## 5. 启动后端（含内置前端托管方式）

```bash
cd XCAGI
python run.py
```

浏览器打开：**http://127.0.0.1:5000/** ，API 文档：**http://127.0.0.1:5000/docs** 。

---

## 6. 仅开发 Vue SPA（可选）

另开终端：

```bash
cd frontend
npm install
npm run dev
```

默认 Vite 端口见 `frontend/vite.config.js`，开发时 API 通过代理指向本机 5000。

---

## 7. Windows / macOS 桌面版（可选）

使用仓库内脚本构建安装包（需已安装 Node、Python、PyInstaller 等，见 `scripts/package/build-installer.ps1` 注释）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package/build-installer.ps1 -Version 7.0.0
```

详见根目录 `README.md` 与 `CHANGELOG.md` **v7.0.0** 说明。

---

## 8. Docker（若使用 compose）

```bash
docker compose up -d --build
```

具体服务名、镜像与环境变量以仓库内 `compose` 文件为准；完整说明见 [DEPLOYMENT.md](./DEPLOYMENT.md)。

---

## 延伸阅读

- [架构说明](./ARCHITECTURE.md)  
- [部署指南](./DEPLOYMENT.md)  
- [功能地图](./FEATURE_MAP.md)  
- [根目录 README](../README.md)  
- [变更日志](../CHANGELOG.md)

---

*最后更新：2026-04-30 · 文档版本：v7.0*
