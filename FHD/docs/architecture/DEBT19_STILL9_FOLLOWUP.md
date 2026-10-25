# DEBT19 still-9 follow-up

- date: 2026-10-25 Asia/Shanghai
- base: main@86c1a720 (#2631)
- branch: debt/19-still-followup
- PR: https://github.com/42433422/XCMAX/pull/2663

## Cleared (CI-honest)

| # | after | note |
|---|-------|------|
| 2 ports | 12 | deleted application/mod_sdk shims |
| 3 layers | application/domain/infrastructure | |
| 10 legacy | 47 | |
| 11 same-name | types7/base8/routes0/paths13/convert15 | renamed/deleted first-party shims |
| 14 fastapi_routes | 301 | moved HTTP port_contracts out |

## Intentionally still STILL (CI-honest)

| # | why |
|---|-----|
| 20 package.json | market/frontend 的 `fast-glob` 指向 `file:./compat-resource-glob`，删除 package.json 会让 Market CI 找不到模块 |
| 12/13 merged + >100KB | source-governance / big-files 禁止新增 `*_mod*` 机械碎片；与 #2631 CLOSEOUT 一致，保留三份 MODstore 巨文件与 evals 整文件 |
| 15 pregel | vendored `xcagi_langgraph_core` 需完整 Generic 类；G12 已排除该树 |

G12 `py_gt_100kb_nontest` 基线保持 3（三份 MODstore 巨文件）。

## Non-goals

不部署；hotfix a8850107 未动。
