# 部署主从索引（DEPLOY_PATH）

> **SSOT**：部署范式主从以本页 + [`ADR-route-a-desktop-private.md`](ADR-route-a-desktop-private.md) 为准。
> 生成/修订：2026-10-24 Asia/Shanghai（架构重构阶段二 · 文档止血入仓）
> 依据：`arch-refactor-phase1/05-deploy-path-rulings.md` 十条裁定

## 总主从

| 角色 | 路径 |
|------|------|
| **主路径（official）** | 桌面私有化（路线 A）+ 现网单 CVM `119.27.178.147` 滚动部署（见仓库根 `ops/README.md`） |
| **实验 / 遗留（experimental）** | Docker / Compose / K8s 清单 / `health_k8s` 探针及同类容器资产 |
| **禁止** | TECH_STACK / 发布手册出现「Docker·K8s·桌面」等权「灵活多官方」表述 |

## 主路径入口

| 入口 | 说明 |
|------|------|
| `ops/README.md` | 单 CVM 生产运维手册 |
| 桌面安装包 / 私有化节点 | ADR-route-a 桌面 SKU |
| GitHub Actions 发布链 → CVM 滚动 | 现网发版主线 |

## experimental 容器资产（不删、阶段三前不物理迁 extras）

| 资产 | 备注 |
|------|------|
| `FHD/docker-compose.yml` 及 `docker-compose.*.yml` | 文件头已标 experimental |
| `FHD/docker/docker-compose.fhd-*.yml`、`Dockerfile.*` | 非桌面 SKU；非签约主路径 |
| `FHD/XCAGI/docker-compose*.yml` | 同上 |
| `FHD/app/fastapi_routes/health_k8s.py` | K8s 风格探针；桌面健康走通用 health |

CI 可继续构建容器作 **非阻断** 旁路；**不得**把容器绿当作发布主线门禁。

## 与 TECH_STACK 的边界

- **栈选型**（语言/框架/库）→ `FHD/docs/TECH_STACK.md`
- **部署主从** → 本页 + ADR-route-a
