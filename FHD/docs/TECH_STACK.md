# FHD (XCAGI) 技术栈

> 本文件为 XCAGI v10.0 项目的**栈选型**权威说明。其它位置若出现栈选型不一致，以本文为准。
> **部署主从不以本文为准**：部署范式以 [`architecture/ADR-route-a-desktop-private.md`](architecture/ADR-route-a-desktop-private.md) 为准（路线 A：桌面私有化 + 现网单 CVM 滚动；Docker/K8s 为 experimental）。
> 更新日期：2026-10-24

---

## 一、总体架构

| 维度 | 选型 | 说明 |
|------|------|------|
| 架构模式 | Neuro-DDD | 领域驱动设计 + AI 用例编排 |
| 交付形态 | 桌面版 + Web 版 | Electron 桌面壳 + FastAPI 子进程 / Nginx + FastAPI |
| 部署方式 | **主路径**：桌面安装包 + 私有化节点 + 现网单 CVM 滚动；**experimental**：Docker / Compose / K8s | 主从见 ADR-route-a；禁止「多官方等权」表述 |

---

## 二、后端技术栈

### 2.1 核心框架

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| HTTP 框架 | FastAPI | 0.100+ | REST API 服务，自动 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn | 0.20+ | 异步 WSGI 服务器 |
| 生产服务器 | Gunicorn | 21.0+ | 进程管理 + Uvicorn worker |
| Python | Python | 3.10+ | 运行环境 |

### 2.2 数据库

| 场景 | 技术 | 说明 |
|------|------|------|
| **桌面 SKU / Mod 业务主库** | SQLite | **业务数据主路径**（ADR-route-a）；本地无需额外服务 |
| **云 API 侧** | PostgreSQL | 账号、市场代理、会话/配置等云侧库；**非** Mod 业务主库 |
| ORM | SQLAlchemy | 2.0+ 版本，类型安全 |
| 迁移 | Alembic | 数据库版本管理 |

### 2.3 缓存与队列

| 云 API 侧 | 桌面 SKU | 用途 |
|-----------|----------|------|
| Redis | 内存队列 | 缓存、会话、限流 |
| Celery | 本地队列 | 异步任务处理 |

> 桌面 SKU 不依赖 Redis/Celery 作为签约主路径运行时。

### 2.4 AI 与机器学习

| 能力 | 技术 | 说明 |
|------|------|------|
| LLM 调用 | OpenAI SDK | 兼容 DeepSeek、GPT 等 |
| 意图识别 | Rasa NLU | 本地 NLU 模型 |
| 意图识别 | BERT / sentence-transformers | 语义理解 |
| OCR | PaddleOCR | 表格识别、文字提取 |
| TTS | Edge TTS / 阿里云 | 语音合成 |
| 规则引擎 | 自研 | 快速规则匹配 |

### 2.5 开发与测试

| 工具 | 用途 |
|------|------|
| pytest | 单元测试框架 |
| Ruff | 代码格式化 / lint / import sort |
| mypy | 类型检查 |

---

## 三、前端技术栈

### 3.1 Web 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.x | 前端框架 |
| TypeScript | 4.9+ | 类型安全 |
| Vite | 4.x | 构建工具 |
| Vue Router | 4.x | 路由管理 |
| Pinia | 2.x | 状态管理 |
| Axios | 1.x | HTTP 客户端 |
| Element Plus | 2.x | UI 组件库 |

### 3.2 桌面端

| 技术 | 用途 |
|------|------|
| Electron | 桌面应用框架 |
| TypeScript | 主进程代码 |
| electron-builder | 安装包打包 |

---

## 四、基础设施

### 4.1 部署与运维

| 技术 | 用途 | 主从 |
|------|------|------|
| 桌面安装包 + ops/CVM 滚动 | 签约交付与现网发布 | **主路径**（见 ADR-route-a、`ops/README.md`） |
| Nginx | 反向代理（云 API / 站点） | 主路径配套 |
| GitHub Actions | CI/CD | 主路径配套 |
| Docker / Docker Compose | 容器化实验、部分云 API 镜像 | **experimental**（非签约主路径） |
| Kubernetes | 可选云形态编排 | **experimental**（现网默认单机 CVM，非多节点写扩展） |

### 4.2 监控与日志

| 技术 | 用途 |
|------|------|
| 结构化日志 | 应用日志 |
| Prometheus | 指标采集（规划中） |
| Loki | 日志聚合（规划中） |

---

## 五、环境变量（后端常用）

| 变量 | 作用 |
|------|------|
| `DATABASE_URL` | 数据库连接字符串 |
| `REDIS_URL` | Redis 连接字符串（Web 版） |
| `XCAGI_DESKTOP_MODE` | 启用桌面运行时（=1 时启用 SQLite/本地队列） |
| `CORS_ORIGINS` | 跨域允许来源 |
| `OPENAI_API_KEY` | LLM API 密钥 |
| `OPENAI_BASE_URL` | LLM API 端点 |
| `ENABLE_RASA` | RASA NLU 开关 |
| `AUDIT_LOG_PATH` | 审计日志路径 |
| `FHD_API_KEYS` | API 密钥（粗粒度接入控制） |

---

## 六、相关文档

- [架构设计](./ARCHITECTURE.md)
- [发布与部署入口](./SSOT_INDEX.md)
- [快速开始](./QUICK_START.md)
- [企业级能力](./ENTERPRISE_AUDIT.md)
