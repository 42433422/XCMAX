# yuangon AI 员工矩阵 — 共享资源

本目录存放跨 area 共享的规范与约定。

## 目录结构

```
成都修茈科技有限公司/yuangon/
├── _shared/              ← 跨岗共享规范（本目录）
├── craft-workshop/       ← 制品工坊岗（构建/验证流水线内部岗）
├── modstore-backend/     ← MODstore 后端岗
├── modstore-frontend/    ← MODstore 前端岗
├── partner-ecosystem/    ← 生态伙伴岗
├── platform-core/        ← 平台核心岗（发版、移动、维护）
├── quality-and-docs/     ← 质量与文档岗
├── server-and-ops/       ← 服务器运维岗
└── site-and-marketing/   ← 营销站点岗
```

## 生成与同步

yuangon 骨架由 `FHD/scripts/dev/bootstrap_yuangon.py` 从 manifest 反向生成。  
yuangon 变更触发链：`yuangon.def.changed` → `push-update-context-officer.skill-yuangon-resync` → `onboard_yuangon_employees.py`

## 规范约定

每个岗位目录包含：
- `employee.yaml` — SSOT：id / area / depends_on / actions.handlers / scope_globs
- `README.md` — 岗位说明
- `runbook.md` — 联调 handoff 契约（P1 核对项落点）

## 版本锁定

v10 线内迭代，不升主版本号。见 `FHD/VERSION.md`。
