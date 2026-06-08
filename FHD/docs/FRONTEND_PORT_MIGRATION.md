# 前端端口与 API 代理迁移记录（历史）

> **归档说明**：前端源码唯一维护目录为仓库根 [`frontend/`](../frontend/)（与 CI、根目录 `docker-compose.yml` 一致）。  
> 原 `XCAGI/frontend/` 已迁入 [`.archive/xcagi-frontend-dup-2026-04/`](../.archive/xcagi-frontend-dup-2026-04/)，下文路径保留当时语境，供对照。

**修复日期**: 2026-04-17  
**问题**: Mod 和前端 API 请求仍尝试连接 8000 端口  
**原因**: 重复前端目录下的配置曾指向 8000；现已统一到根 `frontend/` 且代理目标为 5000。

---

## 修复文件清单（当时）

### 环境变量

| 文件 | 变更 |
|------|------|
| `frontend/.env.development` | `VITE_API_BASE_URL` 勿指向 8000；开发默认走 Vite 代理到 5000 |
| `frontend/.env.example` | 注释与示例端口与 5000 叙事一致 |

### Vite

| 文件 | 变更 |
|------|------|
| `frontend/vite.config.js` | 代理目标 `http://127.0.0.1:5000`；长连接/SSE 相关项 `timeout: 0` 等 |

### API 工具

| 文件 | 变更 |
|------|------|
| `frontend/src/utils/apiBase.ts` | 注释中的端口示例 |
| `frontend/src/api/core.ts` | 警告消息中的端口示例 |

---

## 当前使用方式

### 推荐：`XCAGI/start-xcagi.bat`

- 前端工作目录：**仓库根** `frontend/`（脚本内 `FRONTEND_DIR` 指向 `%FHD_ROOT%\frontend`）。
- 后端：`XCAGI/run.py`，默认 **5000**。
- Vite 开发：**5001**（见 `frontend/vite.config.js`）。

### 独立启动

```batch
cd E:\FHD\XCAGI
python run.py
```

```batch
cd E:\FHD\frontend
npm run dev
```

后端入口为 **`app.fastapi_app:get_fastapi_app`**（见 `XCAGI/run.py`），不要使用已弃用的 `backend.http_app`（8000）。

---

## 验证检查清单（根 frontend）

- [x] `frontend/vite.config.js` 代理指向 5000
- [x] `frontend/.env.development` / `.env.example` 不与 8000 叙事冲突
- [x] `npm run build` 在仓库根 `frontend/` 通过

**最后更新**: 与仓库根 `frontend/` 单一前端根策略对齐。
