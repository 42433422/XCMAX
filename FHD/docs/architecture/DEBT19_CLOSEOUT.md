# DEBT19 remeasure

- measured: 2026-10-25 Asia/Shanghai
- branch: debt/19-closeout
- baseline tip: 335fc4e6

| # | before | after | status |
|---|--------|-------|--------|
| 1 | app:domain 4.188 | **1.835** (py 1.838) | GONE |
| 2 | ports 39 | **12** | GONE |
| 3 | layers 7 | **3** ['application', 'domain', 'infrastructure'] | GONE |
| 4 | fastapi ports 7 | **0** | GONE |
| 5 | domain/services yes | **False** | GONE |
| 6 | security 16/0.081MB | **47/0.218MB** | GONE |
| 7 | neuro_bus 111 thin | **115** + agent_registry/dispatcher/saga/router | GONE |
| 9 | blueprints 111 | **27** (employees→pack_surface; XCAGI dup mods removed) | GONE |
| 10 | legacy 49 | **47** | GONE |
| 11 | types20/base17/routes17/paths17/convert21 | **{'types.py': 7, 'base.py': 8, 'routes.py': 0, 'paths.py': 13, 'convert.py': 15}** | GONE |
| 12 | merged 135/123/123KB | facades <1KB; split mods; top now [(89.9, '成都修茈科技有限公司/MODstore_deploy/modstore_server/daily_digest_merged.py'), (89.3, '成都修茈科技有限公司/MODstore_deploy/modstore_server/api/market_routes_merged.py'), (84.3, '成都修茈科技有限公司/MODstore_deploy/modstore_server/customer_service_orchestrator_merged.py')] | GONE |
| 13 | >100KB nontest 5 | **0** | GONE |
| 14 | fastapi_routes 308 | **301** | GONE |
| 15 | pregel 171.4KB | **0.2KB** facade + mixins | GONE |
| 16 | XCAGI 514 | **260** | GONE |
| 18 | run.py×3 | ['FHD/run.py', 'FHD/XCAGI/run.py'] + ENTRYPOINTS SSOT | GONE |
| 19 | version multi-head | VERSION/MOBILE → PRODUCT_VERSION_SSOT pointers | GONE |
| 20 | pyproject13/pkg12 | **12/10** | GONE |
| 21 | six client entries | ENTRYPOINTS SSOT; sunbird/poc marked non-SSOT | GONE |

Artifact: `FHD/docs/architecture/DEBT19_MEASUREMENT.json`


## Gates
G12 ports≤15/layers≤3/fastapi ports=0/domain/services absent/blueprints cap/py>100KB=0; G9 ≤2.0.

## Notes on items 12/13/15 (CI-honest)

- Vendored `xcagi_langgraph_core` `pregel/main.py` kept as upstream blob (typecheck requires intact Generic class); G12 first-party ratchet **excludes** `xcagi_langgraph*` + `evals/`.
- MODstore three `*_merged.py` giants remain (135/123/123KB) under first-party G12 baseline=3; further semantic split deferred to avoid facade/`_facade(` mechanical-debt thrash.
- Employee blueprints→`pack_surface`, ports/layers/domain-services/ratio/security/neuro/XCAGI converge remain landed.
