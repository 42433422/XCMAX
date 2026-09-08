# Agent 共享记忆协议（四设备统一）

> 状态：v1（2026-09-09 由 Windows 端 Trae 建立，首条记忆已验证写入+检索闭环）
> 存储位置：生产 FHD 知识库 `persy-knowledge` 数据集（管理端 知识库 页面可见）

## 目的

Mac 主控、Win32、生产服务器、灾备服务器四台设备上的智能体（Trae / Codex / 其他 Agent）记忆互不相通。
本协议把跨会话、跨设备需要记住的**事实、决策、教训、当前状态**统一写入生产知识库，
任何设备开工前先读，收工前写回——形成共同的外部记忆。

## 通道（当前唯一已验证可用）

```
任意设备 ──SSH 隧道──▶ 生产 FHD (127.0.0.1:5100) ──▶ 知识库 API
                        安全边界 = LAN CIDR 门禁（公网直连 403）
```

### 1. 建立隧道（每台设备一条）

```bash
# Windows / Mac / 任意有 xcmaxpara SSH 权限的设备
ssh -N -L 15100:127.0.0.1:5100 \
  -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -o BatchMode=yes \
  root@119.27.178.147
# 之后知识库地址 = http://127.0.0.1:15100/api/knowledge/v1
```

服务器本机（生产/灾备 bridge）直接用 `http://127.0.0.1:5100/api/knowledge/v1`，无需隧道。

### 2. 身份与权限（可信数据集头）

每个请求携带（`XCAGI_TRUST_DATASET_ACCESS_HEADERS=1` 已在生产启用）：

```
X-Dataset-Actor-ID: agent-<device>-<agent>   # 例 agent-win32-trae / agent-mac-trae
X-Dataset-Tenant-ID: default
X-Dataset-Permissions: dataset.read,dataset.write
```

### 3. 写入（POST 需 CSRF 双提交）

```bash
# 第一步：GET 换 csrf_token cookie
curl -s -c jar.txt "$BASE/api/knowledge/v1/health" -H "$HEADERS" -o /dev/null
CSRF=$(grep csrf_token jar.txt | awk '{print $7}')
# 第二步：POST 记忆文档
curl -s -X POST "$BASE/api/knowledge/v1/datasets/persy-knowledge/documents" \
  -H "$HEADERS" -H "X-CSRF-Token: $CSRF" -b jar.txt -H "Content-Type: application/json" \
  -d '{
    "source": "agent-shared-memory/<device>-<topic>-<yyyymmdd>.md",
    "document_id": "agent-shared-memory-<device>-<topic>-<yyyymmdd>",
    "text": "# 标题\n\n事实1: ...\n决策1: ...",
    "metadata": {"type": "agent-shared-memory", "device": "<device>", "author": "<agent>"},
    "tenant_id": "default",
    "chunk_strategy": "fixed"
  }'
```

### 4. 读取 / 检索

```bash
# 语义检索（开工前先查相关记忆）
curl -s -X POST "$BASE/api/knowledge/v1/datasets/persy-knowledge/query" \
  -H "$HEADERS" -H "X-CSRF-Token: $CSRF" -b jar.txt -H "Content-Type: application/json" \
  -d '{"query":"<要找的主题>","top_k":5}'
```

## 记忆约定

**写什么**：跨会话/跨设备有用的信息——关键决策及理由、环境坑（依赖缺失、配置开关）、
版本基线变更、通道地址变更、验收结论。**不写**：密码/密钥（系统敏感模式会拦截）、
大段日志、一次性的临时状态。

**document_id 命名**：`agent-shared-memory-<device>-<topic>-<yyyymmdd>`（同 ID 重复写入=更新版本）。

**每次会话流程**：
1. 开工：`query` 检索与本任务相关的既有记忆，避免重复踩坑
2. 收工：把本次沉淀的新事实/决策写成文档（1 个主题 1 篇，不要流水账）
3. 若修正了旧记忆：更新对应 document_id 的版本

## 历史故障与修复记录（2026-09-09）

- 生产 FHD 缺 `reportlab` 包 → 延迟路由注册线程死锁（fast-start 模式）或崩溃（同步模式），
  AIOPEN `/api/aiopen/*` 从未挂载。已安装 reportlab 5.0.1 并启用
  `XCAGI_DESKTOP_FAST_START=0`（同步注册，systemd drop-in `98-agent-dataset-headers.conf`）修复。
- 待办：把 reportlab 补进生产部署清单、drop-in 收编进仓库 deploy 配置（避免下次发布回退）。

## AIOPEN（浏览器/无 SSH 设备的备选通道）

`https://www.xiu-ci.com/api/aiopen/mcp`（X-AIOPEN-Key 鉴权，已修复挂载）。
当前 AIOPEN 的 api_call 未注入 X-Dataset 可信身份，memories 读写会报 scope 缺失；
短期内共享记忆一律走 SSH 隧道。若需放开 AIOPEN 通道，需在 `_tool_api_call` 中补充
`X-Dataset-*` 头（改动点：`app/application/aiopen/service_part01_part02.py`）。
