# FHD-个人/ 迁出 monorepo — 检查清单

> **状态（2026-06）**：**已迁** — 物理目录在 [`FHD/docs/_archive/FHD-个人/`](../FHD/docs/_archive/FHD-个人/)；仓根 [`FHD-个人/`](../FHD-个人/) 保留 ≤10 行 stub。  
> **计划**：[`plan-2026-06-checklist.md`](plan-2026-06-checklist.md) T45 ✅

---

## 1. 迁出目标

| 项 | 说明 |
|----|------|
| 源路径（现） | [`FHD/docs/_archive/FHD-个人/`](../FHD/docs/_archive/FHD-个人/) |
| 仓根 stub | [`FHD-个人/README.md`](../FHD-个人/README.md) |
| 原则 | 日常开发统一在 `FHD/`；CI 不扫描归档树 |

---

## 2. 引用扫描（2026-06-04 收口）

| 文件 / 区域 | 动作 |
|-------------|------|
| `README.md` | ✅ 指向 `_archive` |
| `FHD/config/xcmax_path_employee_map.json` | ✅ prefix 改为 `FHD/docs/_archive/FHD-个人/` |
| `xcmax_path_employee_map.json`（仓根） | ✅ 同步 |
| `scripts/build-xcmax-tree-data.py` | ✅ 映射更新 |
| `成都修茈…/xcmax_admin_api.py` | ✅ 注释去硬编码路径 |
| `specs/checklist.md` / `specs/tasks.md` | 旧计划（deprecated） |
| `.cache/xcmax/*` | 生成物，重跑脚本即可 |

**CI / workflow**：无 `FHD-个人` 硬编码路径（2026-06 扫描为 0）。

---

## 3. 迁出步骤

- [x] **M1** 无脚本依赖 `FHD-个人` 绝对路径（CI 已确认）
- [ ] **M2** 可选：`git filter-repo` 导出独立远程历史
- [ ] **M3** 可选：组织规范远程空仓
- [x] **M4** 本仓删除大目录 / 保留 stub
- [x] **M5** 更新 README、checklist T45
- [x] **M6** 端口说明仍见 `FHD/.env.example`

---

## 4. 验收

- [x] `FHD-个人/` 仅剩 redirect stub
- [x] 归档内容在 `FHD/docs/_archive/FHD-个人/`
- [x] CI / pre-commit 无 `FHD-个人/` 路径依赖
