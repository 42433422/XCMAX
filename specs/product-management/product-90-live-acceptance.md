# Product 90: local desktop and account acceptance

Observed on 2026-09-05, approximately 18:45–19:00 Asia/Shanghai. This is an isolated local acceptance run, not a production or customer sign-off.

## Identity and boundaries

- Desktop product version: `1.0.0.1`; build SHA: `4966e9a39e5a395f812193721865222e0e7bdc77`; built at `2026-09-05T10:23:31.853Z`.
- App is a separate task-owned macOS arm64 bundle. Developer ID signature, hardened runtime, embedded backend, and all 16 runtime dependency packages were verified. It is not notarized, installed in `/Applications`, or published.
- App/backend PIDs at observation: `76523`/`76529`; local desktop API: `127.0.0.1:17593`. Fresh task-owned userdata is `acceptance-userdata` under `/private/tmp/xcmax-product-90-20260905`.
- The existing installed app and its backend on port `17500` remain unchanged.
- Account service is the real local MODstore API on `17594`, with a disposable enterprise test account and zero wallet balance. Its database was bootstrapped; this does not verify its migration chain. No purchase, payment, customer message, or real printer submission occurred.
- The Market browser frontend on `17595` was archived from `4966e9a39`. Wallet backend checks after the connection fix used the task worktree based on `fe9d46484`, with uncommitted catalog changes; they are not final-SHA acceptance.

## Observed user journeys

| Journey | Observed result | Remaining work |
|---|---|---|
| Fresh desktop startup and ordinary login | Native app opened and login succeeded through the visible form. Required Mod routes and database were ready; original app stayed available. | Repeat on the final bundle, then qualify formal release and customer platforms. |
| Runtime status | Visible `部分 AI 能力未就绪` correctly distinguished reachable business service from unavailable local AI. | No configured cloud-model task was accepted as passed. |
| First-use discovery | New enterprise account with 9/9 preinstalled core modules landed in chat with no industry selection. The tutorial was discoverable under `副窗 → 新手教程 → 宿主入门`. | Correct the narrow fresh-account onboarding gate without resetting existing users. |
| Industry preparation | Selecting the entitled coating scenario showed recommended functionality ready and added the data-docking/inventory navigation. | Final bundle must preserve entitlement and custom attendance boundaries. |
| Launch first order from tutorial | `跟 AI 员工做第一单` queued the prompt but returned to the source page. Opening chat manually consumed it. | Fix tutorial launch to navigate directly to chat. Ordinary tutorial return remains separate. |
| First-order confirmation | Run `run_abbf9cbfe0114058b58be3c5846032f5` reached 67% after queries and waited for confirmation. Opening its independent workspace exposed `审批并执行`; a deliberate click completed it at 100%. | Make the task card's next action directly discoverable. |
| First-order business effect | Visible shipment records for `XC 演示客户` contained one `XC 演示产品` record, with one tin and status `未打印`, created at `2026-09-05T18:51:48.537943`. | This synthetic local order is not commercial acceptance or physical printing. |
| Product CSV import | A two-row, 273-byte synthetic file was selected through the native file picker, targeted to `客户及产品`, and submitted. Run `1da409cc-2485-45f2-b078-2f5195747a50` stayed at parsing 5%. | Fix the actual worker failure, then repeat import, manual edit, and rollback through the rebuilt UI. No rollback pass is claimed. |
| Label output discovery | Print page listed the real demo product but no label template. It told the user to use the label editor without providing a creation link; the adjacent template library opened the Excel/Word workflow. | Add a visible label-creation entry and return to output; then create and inspect the PDF through UI. |
| Wallet and model catalog | Before repair, the wallet's parallel provider discovery exhausted the SQLAlchemy pool and also stalled health checks. After short-session credential snapshots, wallet displayed zero balance, empty records, and unconfigured providers; health returned in approximately 21 ms. | Verify the final frontend's failure/retry states and final backend SHA. Empty order/refund claims require explicit successful reads because the legacy overview omits those fields. |

## Reproduced defects and evidence

The catalog connection regression used an isolated real SQLite pool with size one: three tests failed against archived pre-fix source and three passed after the repair. A separate review reproduced the same lifetime issue in platform model discovery and fixed that caller too. Related catalog/runtime tests and exact CI formatter versions were checked independently.

The stalled CSV job was reproduced on a SQLite backup, not by changing the running acceptance database. Exact `4966e9a39` source raised `TypeError: complete_structured() got an unexpected keyword argument 'conversation_service'`. The advisory call and background worker caught only recoverable exceptions, so the task stayed at 5% without a persisted failure. The repair retains the owner-specific provider through structured invocation, degrades advisory failures to deterministic mapping, and records unexpected preview-task failures. A repeat on a second backup, with its copied job reset to a fresh queue, reached `preview_ready` while the real local account API returned an unavailable-model response. The first post-fix diagnostic retained an expired job and correctly returned `interrupted`; it is not the successful replay. Focused regression and rebuilt UI acceptance are still required.

Local diagnostic files are under `/private/tmp/xcmax-product-90-20260905`: `desktop-runtime-acceptance/launch.json`, `etl-live-diagnostic/result.log`, `etl-live-diagnostic/fixed-v2-result.log`, `catalog-connection-regression/`, and `catalog-independent-review/`. Runtime databases and credential files are private test materials and are not committed.

## Delivery status

Pre-build focused checks completed after the observations above: 444 onboarding/login/router tests, including the actual login composable, profile hydration, router guard, and industry gate; 117 wallet/read-state tests; 20 label-output/editor tests; and 53 task-navigation/control tests. The latter include 13 cases mounting the actual Mod, shared task card, runtime bridge, and workspace, with navigation producing no approval and an explicit approval producing one submission. The old onboarding gate failed the fresh-user case through the same actual router chain, while all six cases passed after repair. Full frontend type checking and scoped lint passed. These results are source-level evidence; the new UI still requires rebuilding and visible acceptance.

Real CSV execution tests also exposed a second ETL defect after preview: `hasattr(adapter, "execute_batch")` classified row-based customer/product adapters as external batches because their base class defines a rejecting stub. Execution now checks for an actual implementation override and uses that same decision for both the operation kind and dispatch. Twelve new CSV/SQLite integration tests passed, including confirmed creation of one customer and two products followed by real rollback, owner-specific provider routing, advisory degradation, task failure/lease release, SQL rollback without replay, and external unknown outcomes. The same tests against an isolated `4966e9a39` snapshot produced nine failures and three passes. Evidence is in `etl-preview-integration-review/current-aggregate.log` and `old4966-isolated.log`; visible UI acceptance is still pending.

Draft PR: <https://github.com/42433422/XCMAX/pull/1768>. At head `fe9d46484`, the Market, desktop, frontend, security, and source-governance checks observed in this run passed. MODstore backend was stopped by import sorting in two handoff tests; its precise correction passed the local Black 26.3.1 and isort 6.1 gates. The main backend test was still in progress at that observation. Final changes must receive their own complete CI and artifact checks.

The separate release-readiness ledger remains authoritative for exact-main-SHA deployment, two consecutive UTC-day security scans, Windows signing, production convergence, and real customer evidence. This document does not award 90 points or close those gates.
