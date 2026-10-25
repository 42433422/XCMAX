# DEBT19 still-9 follow-up

- date: 2026-10-25 Asia/Shanghai
- base: main@86c1a720 (#2631)
- branch: debt/19-still-followup

## Scope

Clear remasure STILL after #2631 merge tip: ports/layers/legacy/same-name/merged/>100KB/pregel/fastapi_routes/package.json.

## Changes

- Delete application/mod_sdk `ports.py` compat shims (keep domain + contracts + infra + modstore = 12); layers → application/domain/infrastructure
- Rename fastapi_routes `**/routes.py` → `<dir>_routes.py` (routes.py = 0); move HTTP `port_contracts` out of fastapi_routes (301)
- Remove nested compat-resource-glob `package.json` (12→10)
- Delete first-party same-name shims (types/base/paths/convert) that #2631 CI red-fixes reintroduced
- Restore debt19 giant-file split for pregel / evals / three MODstore `*_merged.py` (facade + <100KB parts)
- Ratchet G12 `py_gt_100kb_nontest` 3→0 and `routes_total` 304→298

## Non-goals

- No deploy; hotfix a8850107 untouched
- Vendored LangGraph body kept in split modules (not deleted)

Artifact: `DEBT19_MEASUREMENT.json`
