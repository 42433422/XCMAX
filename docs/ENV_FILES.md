# 环境变量文件（M0 盘点）

> **统计口径**：自 XCMAX 仓根 `find . -maxdepth 2 -name '.env*'`（2026-06-05）。XCMAX 仓根下无 `.env*`；**合计 5 个**，均在 `FHD/`。

| 路径 | 入库 | 用途 |
|------|------|------|
| `.env.example` | 是（模板） | 本地/开发主配置 SSOT 模板 |
| `.env.fhd-docker.example` | 是（模板） | Docker Compose 全栈模板 |
| `.env.monitoring.example` | 是（模板） | 本地 Grafana/Prometheus 栈 |
| `.env` | **否**（`.gitignore`） | 开发者本机真值 |
| `.env.fhd-docker` | **否**（`.gitignore`） | Docker 本机真值 |

## 约定

1. **真值不入库**：仅提交 `*.example`；复制后改名并填写密钥（见 [`QUICK_START.md`](QUICK_START.md)）。
2. **禁止**在 PR 中新增含密码、`SECRET_KEY`、DB 连接串的 `.env` 文件。
3. CI 与 e2e 使用 workflow `env:` 或 mock，不依赖仓内 `.env`。

## 相关

- [`.gitignore`](../.gitignore) — Secrets 节
- [`scripts/README.md`](../scripts/README.md) — 脚本目录约定
