# ELT-E2E-FULL-001 final report

Verdict: **BLOCKED**. This is not an ELT full-business-loop PASS. No customer workbook was uploaded, classified, confirmed, committed, read back from ERP, or exported. Prior per-branch PASS claims were not reused.

This file is an evidence snapshot for the review candidate. It is not a product SSOT and it is not a release record.

## Identity

| Item | Value |
|---|---|
| Tested `origin/main` | `566cf2a446d92cf12635a41c6622ce8ac8864ab8` (`fix(excel, erp): formula caches, shipment cell lineage, AI employee read permissions (#3087)`, 2026-11-07) |
| Integration branch | `cursor/elt-e2e-full-001-826b` |
| Candidate before this report | `ac7531d32f921d69d01b6e9a34e0c3d90202bc3d` |
| Candidate SHA | `e1ce4e470dca994d90a14b028a7a7702c23843c6` plus the follow-up commit that records the empty CI list. The pushed head is authoritative. |
| Product version | `1.0.0.7` (`FHD/VERSION.md`; live `GET /api/health` on the restarted desktop backend) |
| Toolchain mapping | `1.0.0` |
| Client | XCAGI enterprise, edition full, `XCAGI_DESKTOP_MODE=1`, Electron from `FHD/desktop` with `--no-sandbox` |
| Frontend build | `VITE_XCAGI_PRODUCT_SKU=enterprise VITE_XCAGI_EDITION=full npm run build:full` in `FHD/frontend`, exit 0, 52.44s. Vite warned that `%VITE_XCAGI_GIT_SHA%` was unset. Output is gitignored `FHD/templates/vue-dist` and is not a release artifact. |
| Isolated data dir | `~/.config/XCAGI-elt-e2e-826b` (previous `~/.config/XCAGI-unmerged` was left in place) |
| Live backend | `FHD/.venv/bin/python FHD/XCAGI/run.py --desktop --headless --host 0.0.0.0 --port 17500`. `GET /health` reported `git_sha` `ac7531d32f921d69d01b6e9a34e0c3d90202bc3d` before this report commit. |
| Delivery channel | Review candidate only. Not merged to `main`. Not a customer installer. |

Open PRs re-listed with `gh pr list --state open` before branching: #3085, #3086, #3088, #3089, #3090, #3091, #3092. All were `CONFLICTING` with `main`. No newer ELT/ETL PR was open. #3087 is already on `origin/main` and was kept, including `2026_11_07_read_tool_permissions`.

## Security gate — customer files were not accessed

Repository `42433422/xcmax-Li`:

| Check | Result |
|---|---|
| Visibility | **PUBLIC** (`gh repo view` and unauthenticated `GET https://api.github.com/repos/42433422/xcmax-Li` HTTP 200, `private: false`) |
| Default branch | `main` |
| Files reachable | Yes. Anonymous metadata shows the default branch. A tree listing (names not copied here) contains **23 spreadsheets: 22 `.xlsx` and 1 `.xls`**, plus other business documents. |
| History | Public `main` includes commits from 2026-11-05 and 2026-11-06, including the commit that added the October 2026 business upload. Those blobs are in the reachable history, not only the tip. |
| This agent | Did **not** clone the repo, did **not** download workbook bytes, did **not** open a sheet, and did **not** compute SHA256. No customer cell, name, price, or attendance mark is in this report or the branch. |
| Local copy | `/opt/cursor/artifacts/etl-b01-b31` is absent. No isolated copy was made. |
| Who must fix it | `gh` on this machine is read-only. The owner must make `42433422/xcmax-Li` private and remove the files from the reachable history. Making the repo private later does not erase copies already fetched while it was public. |

Because there is no authorized isolated copy, every customer-file acceptance item below is **BLOCKED**. The code integration and the synthetic regression do not change that.

## What was integrated

Base: `origin/main` `566cf2a44`.

1. Merge of `740eff866` (PR #3092 head), which already contained #3085 `1f4b924be`, #3086 `65f548f45`, #3088 `2c184819e`, #3090 `f11782f49`, #3091 `b42ccb933`, and the slice-coverage work through `57a78f6e8`.
2. Cherry-pick of `d4195b730` (“Fill saved delivery notes from committed shipment rows”), the extra commit on #3089 that was **not** inside `740eff866`.
3. Conflict resolution kept `main`'s #3087 formula-cache and view-permission behavior, and kept the unmerged non-empty cell preview bound of 100000.
4. Fix `c59c510dc`: the enterprise shipment-download facade now passes the request into the tenant-scoped download function.
5. Line baseline raised `2441638` → `2443610` (+1972). Reason is in `FHD/metrics/line_baseline.json`. Source-growth records for files over 800 lines are review requests, not approval.

`FHD/mods/attendance-industry/` was already untracked, was not committed, and was not deleted.

## Files executed

No customer spreadsheet was executed. Original SHA256, sheet counts, and business roles were **not** measured. The 23 public spreadsheets stay unread. Print templates, the legacy `.xls`, and any non-business file were not given a fake import result; their disposition is **not evaluated**.

## Focus cases (not run)

| Case | Required check | Result |
|---|---|---|
| Attendance workbook, 17 months | Every month identified | **BLOCKED**. File not opened. |
| 85 employee-month records | Each has a disposition; date, employee, mark, and month not shifted | **BLOCKED**. No count and no disposition was produced. |
| 140 merged regions | Valid data not dropped | **BLOCKED**. |
| 2 previously ambiguous marks | Resolved by rule, or left as a real human-confirm block | **BLOCKED**. Not guessed. |
| Attendance DB vs final Excel | Match | **BLOCKED**. No DB rows and no final workbook. |
| Shipment ledger, 537 source rows | Source and final disposition for every row; duplicates, overwrites, exclusions, pending confirms; quantity, price, amount, customer links | **BLOCKED**. Importing any smaller delivery-note sample was not treated as completion. |
| Mixed workbook | Multi-table split, repeated headers, totals, hidden sheets, formulas, previously missed cells | **BLOCKED**. No structural coordinates were taken, because reading the file would copy customer data from a public repo. |

## Full loop

Every step below was required on a real customer file, the real enterprise client or its real business API, a real model where classification needs one, and an isolated database. None of them ran.

| Step | Result |
|---|---|
| Real file upload | BLOCKED |
| Original encrypted archive, recoverable and unmodified | BLOCKED |
| File version and SHA256 | BLOCKED |
| Full workbook structure recognition | BLOCKED |
| Real model classification | BLOCKED (no customer file; model output was not invented) |
| Table location | BLOCKED |
| Slice and logical grouping, 100% coverage of valid data | BLOCKED |
| Human candidate selection | BLOCKED |
| Extract | BLOCKED |
| Load raw snapshot before Transform | BLOCKED |
| Transform mapping and cleaning | BLOCKED on customer bytes |
| Validation | BLOCKED on customer bytes |
| Business preview and per-row disposition | BLOCKED |
| Human confirm rejects old revision and unconfirmed content | BLOCKED |
| Transactional commit matches preview | BLOCKED |
| Real ERP read of committed data | BLOCKED. No customer commit, so no ERP read record. |
| AI employee actually calls tools | BLOCKED. No business tool-call record was produced. |
| Business calculation vs independent baseline | BLOCKED. No baseline was guessed. |
| Export from committed data | BLOCKED |
| HTTP download 200 and file opens | BLOCKED |
| Reconciliation of original / DB / business / Excel | BLOCKED |
| Idempotent resubmit | BLOCKED |
| Recovery after restart, crash, or lost receipt | BLOCKED |
| No cross-tenant access on the customer task | BLOCKED for the customer task |
| Audit trail of that task | BLOCKED |
| Preview vs commit counts | Not produced |
| Final Excel SHA256 | Not produced |

## B01–B80

Customer-loop result for **B01 through B80 is BLOCKED individually**. The same reason applies to each: the authorized customer bytes were not available, and a synthetic or historical PASS was not promoted.

Synthetic tests on this candidate, where they exist, are regression only:

| IDs | Synthetic result on this candidate | Customer loop |
|---|---|---|
| B01–B08 | Upload/archive regression tests passed (disguised, corrupt, encrypted, read-only original paths covered by the integrated suite). Not a rerun of `b01-b08-report.json`. | BLOCKED |
| B09–B24 | No customer execution. Formula-cache and workbook inspection tests in the suite passed on synthetic workbooks. | BLOCKED |
| B25–B32 | Auto-slice, table segmentation, and acceptance-repair tests passed on synthetic sheets. The #3089 customer corpus was not rerun. | BLOCKED |
| B33–B42 | `tests/test_etl_validation_value_fidelity.py` passed. | BLOCKED |
| B43–B49 | Preview confirmation and preview-boundary tests passed on synthetic rows. | BLOCKED |
| B50–B56 | No customer execution. Snapshot and replay tests passed on synthetic runs only. | BLOCKED |
| B57 | `tests/test_application/test_elt_import_audit.py` passed. | BLOCKED |
| B58, B60, B62 | Already on `main` via #3087. Buyer-meta tests passed. | BLOCKED |
| B59, B61, B63, B64 | No customer execution and no new case result. | BLOCKED |
| B65–B71 | Shipment layout-fill and export regression tests passed on synthetic notes. | BLOCKED |
| B72–B80 | No customer execution. Not marked pass. | BLOCKED |

The product gate in `app/application/elt/customer_excel_gate.py` (B31-01 through B31-56) also stays blocked without a customer original. `tests/release_gate/test_etl_customer_excel_b31.py` passed as a gate-behavior test: it checks that a missing original cannot be reported as a release pass. That pass is not a customer pass.

`test_real_customer_workbooks_classify_without_size_or_fidelity_rejection` was **skipped** because `/opt/cursor/artifacts/etl-b01-b31` is absent. The skip is not a pass.

## Three runs and fault injection

Not started. There is no customer database result to repeat.

| Run | Result |
|---|---|
| Fresh data, real client or real business API | BLOCKED |
| Same business again (idempotent, history kept) | BLOCKED |
| Clean baseline restored and rerun | BLOCKED |

| Fault | Verified against the customer database |
|---|---|
| Upload interrupted | No |
| Snapshot load crash | No |
| Transform interrupted | No |
| Model timeout or bad content | No |
| Preview edited, then old revision submitted | No |
| Two clients submit concurrently | No |
| Crash before DB commit | No |
| Commit succeeds, receipt lost | No |
| Crash after partial business writes | No |
| Backend and worker restart during the business task | No |
| Final file generation failure | No |
| Download failure | No |
| Rollback interrupted | No |
| Cross-user and cross-tenant access denied on the customer task | No |

Synthetic RBAC tests did pass for the shipment download facade, including same-tenant 200 and other-tenant 404, after the fix below. That is not the customer-task fault injection.

## Defect found on this candidate

| Item | Detail |
|---|---|
| Failure | `tests/test_routes/test_windows_business_rbac_boundaries.py::test_mod_shipment_routes_keep_permission_and_file_tenant_scope[23-True-200]` |
| Symptom | `TypeError: shipment_download() missing 1 required positional argument: 'request'` at `FHD/app/mod_sdk/erp_domain_compat.py` |
| Root cause | `d4195b730` requires the HTTP request so the download stays inside the signed-in tenant directory. The enterprise facade still called it with only the filename. |
| Fix | `c59c510dc` `fix(elt): pass the request into tenant shipment downloads` |
| Retest | The RBAC file, shipment layout fill, and export regressions: 34 passed. Full ELT suite rerun after the fix: **878 passed, 1 skipped, 0 failed** in 647.64s. |
| Assertions | Not deleted, not weakened, and no answer key was edited by this integration. |

First suite run, before the fix: **1 failed, 877 passed, 1 skipped** in 457.31s. The failure is the row above. The skip is the missing local customer-artifact test.

## Automated regression that did not need customer bytes

Suite (pytest 9.1.1, `FHD/.venv`):

- ELT upload, archive, cleaning, preview, slice, audit, export, segmentation, shipment layout, formula cache, buyer metadata, snapshot, replay, source-first, ELT routes, shipment RBAC, customer-excel release gate.

Second run on the fixed candidate: 878 passed, 1 skipped, exit 0.

`python scripts/dev/push_preflight.py --fix` from `FHD/` passed after the capability page date refresh (`成都修茈科技有限公司/capabilities/feature/erp-shipment.html`, date only, still the pre-existing “已验证” label). That label is the generator output. It is not this task’s acceptance result.

`python scripts/dev/source_growth_review.py --base origin/main --head` (before the report commit) reported no binding errors. Files still over the advisory cap and requiring human review, not approval:

- `FHD/app/application/elt/table_segmentation.py` (new, 935 lines)
- `FHD/app/application/reviewed_excel_structural_index.py` (892 → 909)
- `FHD/app/application/reviewed_excel_template.py` (1375 → 1376)
- `FHD/app/fastapi_routes/reviewed_excel_template.py` (2030 → 2039)
- `FHD/frontend/src/components/template/ReviewedExcelTemplate.vue` (2060 → 2069)

## CI

`e1ce4e470dca994d90a14b028a7a7702c23843c6` was pushed to `origin/cursor/elt-e2e-full-001-826b`. `gh run list --branch cursor/elt-e2e-full-001-826b` returned no workflow runs.

`.github/workflows/fhd-ci-cd.yml` runs on `pull_request` to `main` (and on `push` only for `main`, `develop`, and `master`). A branch push alone does not start that pipeline. Required checks therefore have no result: not green, not red, not started.

Pull request: https://github.com/42433422/XCMAX/pull/3094. Opening it is what starts `fhd-ci-cd.yml`. Those checks were not terminal when the PR was opened, so CI is not green.

CI remains a release blocker until the checks on this head are terminal and green. This report does not call them passed.

## Production release

**Not met.**

- Customer loop did not run.
- `xcmax-Li` is still public.
- B01–B80 customer results are blocked, not passed.
- Three runs and the fault list were not verified on a customer database.
- Architecture-review records are not approvals.
- The line baseline was raised by 1972 lines because the integrated fixes are the behavior under review.
- User instruction: do not merge while any P0, P1, or CI blocker remains. This branch is not merged.

## Unfinished items

1. Owner makes `42433422/xcmax-Li` private and removes the business files from reachable git history.
2. An authorized isolated copy is provided outside the product git tree, without committing customer bytes.
3. Run the full customer loop on the recognizable business workbooks only, including the attendance, shipment-ledger, and mixed-workbook cases, with a real model where classification needs one and with a recorded human confirm where a mark stays ambiguous.
4. Produce preview-vs-commit counts, ERP read evidence, AI employee tool-call records, final Excel SHA256, and HTTP download proof.
5. Run the three continuous database runs and every listed fault against that database.
6. Human architecture review of the five over-800-line records.
7. CI on this candidate SHA terminal and green. Even then, do not merge until the customer loop is actually complete.
