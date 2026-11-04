# DEBT19 still-4 closeout follow-up

- date: 2026-10-25 Asia/Shanghai
- base: main@84d81db75 (#2663)
- branch: debt/19-still-4-closeout

## Cleared in #2663 (already on main)

| # | after | note |
|---|-------|------|
| 2 ports | ≤15 | deleted application/mod_sdk shims |
| 3 layers | application/domain/infrastructure | |
| 10 legacy | 47 | |
| 11 same-name | types7/base8/routes0/paths13/convert15 | renamed/deleted first-party shims |
| 14 fastapi_routes | 301 | moved HTTP port_contracts out |

## Cleared in this PR (was intentionally STILL)

| # | after | note |
|---|-------|------|
| 12 merged giants | facades <1KB; top now daily_digest/market_routes/agent_butler (<100KB) | split into `*_mod*` modules; star-import facades; source-governance baseline redistributed with `--force` |
| 13 >100KB nontest | **0** | evals + pregel + MODstore three giants all split under 100KB |
| 15 pregel | **0.2KB** facade + mixins | `main_mod*` / `main_mod2_s2_mix*` keep Generic behavior |
| 20 package.json | **12/10** | nested `compat-resource-glob/package.json` folded into `compat-resource-glob.tgz`; Market/Frontend `file:` deps retargeted |

G12 `py_gt_100kb_nontest` baseline → **0**.

## Non-goals

不部署；hotfix a8850107 未动。
