# Evolution Closed-Loop Evidence · v3 (T-C11 real listing)

- **Date**: 2026-07-20
- **Task**: T-C11 真实上架试点（≤5 文件 employee_pack）
- **Goal state**: S6 (evolution self-implement self-publish closed loop)
- **Dry-run**: `false` (real listing)
- **trace_id**: `ecb5cfb59eaf`
- **Spec**: [docs/superpowers/specs/2026-07-20-evolution-self-implement-design.md](file:///Users/a4243342/Desktop/XCMAX/docs/superpowers/specs/2026-07-20-evolution-self-implement-design.md)
- **Prior evidence**: [evolution-closed-loop-2026-07-20-v2.md](file:///Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/evolution-closed-loop-2026-07-20-v2.md)

---

## 1. 试点 employee_pack 概要

| Field | Value |
|-------|-------|
| pack_id | `pilot-low-risk-clerk@1.0.0` |
| department | engineering |
| files | `manifest.json`, `prompt.txt`, `skills.json` (3 files, ≤ 5 cap) |
| HIGH_RISK_PATTERNS hit | none |
| pack dir | `成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files/pilot-low-risk-clerk@1.0.0/` |
| declared skills | trace-validation, ledger-append |
| declared tools | read_file, append_event |
| acceptance criteria | trace_id consistent / pack_listed event with final_status=closed_loop_completed / no HIGH_RISK_PATTERNS / ≤ 5 files |

---

## 2. 执行步骤（dry-run=false 全程 ledger）

```
1. 加载 manifest.json → validate_pack_schema()             PASS
2. register_in_packages_json(manifest, files_dir=PACK_DIR) PASS
   → pack_id = pilot-low-risk-clerk@1.0.0
3. evaluate_employee_pack(pack_id)                          PASS
   → risk=low  reason="pack approved: 3 files, no high-risk paths"
4. append_event pack_built  (trace_id=ecb5cfb59eaf)        PASS
   → event_id=a3d5ad20-0d7d-4283-ad1e-cbc49eb8dfde
     final_status=pack_listed
5. append_event pack_listed (trace_id=ecb5cfb59eaf)        PASS
   → event_id=db4a0614-4ff7-45a7-b3c8-59508ac126ba
     final_status=closed_loop_completed
     files=["manifest.json","prompt.txt","skills.json"]
     file_count=3  market_visible=true
```

## 3. 5 接通点验收

| # | 接通点 | 状态 | 证据 |
|---|-------|------|------|
| 1 | collect-signals | (复用 v2 trace 3195d01b0b32) | PASS — v2 已交付 |
| 2 | propose-pack | (复用 v2 trace 3195d01b0b32) | PASS — v2 已交付 |
| 3 | open-issue | (复用 v2 trace 3195d01b0b32) | PASS — v2 已交付 |
| 4 | implement-pack | (复用 v2 trace 3195d01b0b32) | PASS — v2 已交付 |
| 5 | publish-pack | **本次真实执行** | **PASS** — 见下表 |

### 接通点 #5 真实交付证据

| 验收项 | 期望 | 实际 | PASS |
|--------|------|------|------|
| pack 文件数 | ≤ 5 | 3 (manifest.json + prompt.txt + skills.json) | ✅ |
| HIGH_RISK_PATTERNS | none | none | ✅ |
| evaluate_employee_pack risk | low | low | ✅ |
| packages.json 注册 | id 存在 | line 704 `"id": "pilot-low-risk-clerk@1.0.0"` | ✅ |
| packages.json files_dir | 指向 pack 目录 | `"files_dir": "files/pilot-low-risk-clerk@1.0.0"` | ✅ |
| packages.json created_at | 新鲜日期 | `2026-07-20T13:59:13.436978+00:00` | ✅ |
| ledger pack_built 事件 | trace_id 贯穿 | trace_id=ecb5cfb59eaf, final_status=pack_listed | ✅ |
| ledger pack_listed 事件 | final_status=closed_loop_completed | final_status=closed_loop_completed | ✅ |
| market_visible | true | true | ✅ |
| ledger 中 trace 可查 | 2 条事件同 trace_id | pack_built + pack_listed 都带 ecb5cfb59eaf | ✅ |

---

## 4. ledger 事件摘录（trace_id=ecb5cfb59eaf）

文件：[成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl)

| # | event_type | event_id | final_status | pack_id | timestamp |
|---|-----------|----------|--------------|---------|-----------|
| 1 | pack_built | a3d5ad20-0d7d-4283-ad1e-cbc49eb8dfde | pack_listed | pilot-low-risk-clerk@1.0.0 | 2026-07-20T13:59:13.438478+00:00 |
| 2 | pack_listed | db4a0614-4ff7-45a7-b3c8-59508ac126ba | closed_loop_completed | pilot-low-risk-clerk@1.0.0 | 2026-07-20T13:59:13.439637+00:00 |

`pack_built` 关键字段：
```json
{
  "event_type": "pack_built",
  "trace_id": "ecb5cfb59eaf",
  "pack_id": "pilot-low-risk-clerk@1.0.0",
  "commit_sha": "pilot-tc11",
  "risk_level": "low",
  "risk_reason": "pack approved: 3 files, no high-risk paths",
  "dry_run": false,
  "final_status": "pack_listed"
}
```

`pack_listed` 关键字段：
```json
{
  "event_type": "pack_listed",
  "trace_id": "ecb5cfb59eaf",
  "pack_id": "pilot-low-risk-clerk@1.0.0",
  "market_visible": true,
  "files": ["manifest.json", "prompt.txt", "skills.json"],
  "file_count": 3,
  "dry_run": false,
  "final_status": "closed_loop_completed"
}
```

---

## 5. packages.json 注册摘录

文件：[成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/packages.json](file:///Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/packages.json) line 704-710

```json
{
  "id": "pilot-low-risk-clerk@1.0.0",
  "name": "pilot-low-risk-clerk",
  "version": "1.0.0",
  "department": "engineering",
  "files_dir": "files/pilot-low-risk-clerk@1.0.0",
  "created_at": "2026-07-20T13:59:13.436978+00:00"
}
```

> 注：与既有 `packages.json` 中其它富字段 schema 条目（带 `artifact`/`industry`/`commerce`/`license`/`sha256` 等）不同，此条目由 evolution pipeline 的 `register_in_packages_json()` 写入，schema 与 `build_employee_pack.py` 的注册路径一致（id/name/version/department/files_dir/created_at）。

---

## 6. 与 v2 的差异

| 维度 | v2 (T-C10 dry-run) | v3 (T-C11 real) |
|------|-------------------|-----------------|
| dry_run | true | **false** |
| trace_id | 3195d01b0b32 | ecb5cfb59eaf |
| event count | 7（含 collect/propose/issue/implement/publish） | 2（pack_built + pack_listed） |
| market_visible | dry_run=true, 不可见 | **true** |
| packages.json 注册 | 无（dry-run 不真注册） | **有**（line 704-710） |
| pack files | 无 | manifest.json + prompt.txt + skills.json |
| evaluate_employee_pack | 跳过 | **PASS, risk=low** |
| 覆盖范围 | 全闭环 5 接通点 | 仅接通点 #5（publish-pack）真跑 |

> T-C11 是 publish-pack 接通点的真实试点，前 4 接通点的真实执行待 Wave A 通电后接入；本次 trace 仅贯穿接通点 #5，不要求覆盖 collect→propose→issue→implement。

---

## 7. 回滚预案（如需）

如果试点需要回滚（owner 审计判定不应上架）：

1. 从 packages.json 移除 `pilot-low-risk-clerk@1.0.0` 条目
2. 删除 `成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files/pilot-low-risk-clerk@1.0.0/` 目录
3. 写 `pack_delisted` 事件到 ledger，trace_id=ecb5cfb59eaf，final_status=`pack_delisted`

回滚是否触发：**否**（保留上架状态作为 T-C11 验收证据）

---

## 8. 验收总结

- [x] dry-run=false 跑通接通点 #5（publish-pack）
- [x] ≤ 5 文件硬限制（实际 3 文件）
- [x] 低风险 employee_pack（evaluate_employee_pack risk=low）
- [x] market 可见包（packages.json 含 `pilot-low-risk-clerk@1.0.0`，market_visible=true）
- [x] 全程 ledger（trace_id=ecb5cfb59eaf 贯穿 pack_built + pack_listed 2 事件）
- [x] trace 可查（ledger grep ecb5cfb59eaf 命中 2 行）
- [x] final_status=closed_loop_completed

**T-C11 验收：PASS**
