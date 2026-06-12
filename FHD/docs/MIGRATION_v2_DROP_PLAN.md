# `*_v2` 应用服务收敛计划

> **状态（2026-06）**：**已收敛（受控双入口）** — 允许名单内 24 个模块为 Neuro 事件 SSOT；HTTP 同步 API 仍走 V1 getter（见 `app_service_pair_registry`）。新增 `*_vN.py` **禁止**；新能力扩展既有 V2 或 `domains/*` SSOT。  
> **Guard**：`scripts/guard_no_new_v2_files.py` + [`scripts/ci/v2_versioned_py_allowlist.txt`](../../scripts/ci/v2_versioned_py_allowlist.txt) + `scripts/ci/check_broad_except_gate.py`

---

## 1. 背景

Flask → FastAPI / NeuroBus 迁移期间，部分域同时存在 v1 路由服务与 `*_app_service_v2.py`。  
v2 模块现为 **应用层 SSOT**（见 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)），与「历史 CHANGELOG 写已清零」不一致 — **以本计划与 allowlist 为准**。

---

## 2. 允许名单（24）

路径相对于仓根；更新 allowlist 须同步本表。

| 模块 | 说明 |
|------|------|
| `FHD/app/application/*_app_service_v2.py`（23 个） | 各业务域应用服务 |
| `FHD/app/mod_sdk/sdk_v2.py` | Mod SDK 兼容层 |

完整列表见 [`scripts/ci/v2_versioned_py_allowlist.txt`](../../scripts/ci/v2_versioned_py_allowlist.txt)。

---

## 3. 策略

### 3.1 HTTP 路由

- **保持 HTTP V1** 对外稳定；Neuro 事件路径优先走 v2 应用服务。
- 新 HTTP 能力：优先 [`app/fastapi_routes/domains/`](../../app/fastapi_routes/domains/) SSOT，勿新增平行 `*_v3.py`。

### 3.2 禁止项

- 禁止新增 `FHD/app/**/*_v[0-9]+.py`（pre-commit / CI 拦截）。
- 禁止「复制粘贴 v2 → v3」式分叉；应合并到既有 v2 或拆 domain 包。

### 3.3 v1 → v2 alias（暂缓）

T12 结论：registry 判定 V1/V2 **非 drop-in**，本轮不做全局 alias 桥接。逐域迁移见 [`reports/COMPAT_LAYER_INVENTORY.md`](reports/COMPAT_LAYER_INVENTORY.md)。

**Wave 4 辅助**：[`app_service_pair_registry.py`](../app/application/app_service_pair_registry.py) 新增 `resolve_http_getter` / `resolve_neuro_getter` — HTTP 仍 V1、Neuro 仍 V2，待内联合并后改 `http_layer`。

---

## 4. 收敛顺序（建议）

1. `purchase` — 文档化「仅 V2」策略（已完成口径）
2. 将 deprecated routes 流量迁至 `xcagi_compat` / `domains/*` SSOT
3. 当某域 v1 零引用时，删除 v1 实现（**不**删除 v2 文件名，除非整域合并进无后缀模块）
4. 最终目标：文件名去 `_v2` 后缀（大 rename），非短期任务

---

## 5. 本地检查

```bash
# 应无输出（除 allowlist 外）
git ls-files 'FHD/app/**/*_v*.py' | while read f; do
  grep -qxF "$f" scripts/ci/v2_versioned_py_allowlist.txt || echo "NOT IN ALLOWLIST: $f"
done

# pre-commit 模拟
python scripts/guard_no_new_v2_files.py FHD/app/application/new_foo_app_service_v2.py
# 期望 exit 1
```

---

## 6. 相关文档

- [`MIGRATION_REGISTRY.md`](MIGRATION_REGISTRY.md)
- [`reports/COMPAT_LAYER_INVENTORY.md`](reports/COMPAT_LAYER_INVENTORY.md)
- [`V10_REMAINING_DEBT.md`](V10_REMAINING_DEBT.md)
