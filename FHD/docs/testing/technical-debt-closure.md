# Technical debt closure acceptance

Baseline: origin/main `d7a90a8e599afa391e60ec2fef9cce9828a06cd5`.
This work implements the five areas discussed in the developer assessment.
Completion requires each item below to have current evidence; local green tests alone are insufficient.

| Requirement | Acceptance evidence | Status |
| --- | --- | --- |
| D1: trustworthy checks | Monorepo mutation path regression, missing-report failure, intentional-defect rejection, generated workflow consistency | In progress |
| D2: task and AI evaluation | Explicit observe/gate modes, valid thresholds, exact case/trial accounting, independent model evaluation identity and raw results, business state assertions | Pending |
| D3: architecture convergence | Incremental Agent responsibility extraction, explicit dependencies, old entry compatibility, removal of superseded dynamic back-reference paths | Pending |
| D4: durable recovery | Two-process claim, stale owner fencing, restart/cancel, write-before-receipt crash and unknown-external-result behavior | Pending |
| D5: evidence and delivery | SHA-bound reports, historical/current distinction, one integration PR merged normally, mainline artifact/runtime/UI identity, preserved entitled Mods and data | Pending |
| Cleanup | Only task-owned temporary objects removed; durable evidence retained; workspace and available disk checked | Pending |

Existing work must be preserved. PR #1809 owns attendance upgrades and the missing live intent evaluator; PR #1804 owns AI control expansion; PR #1806 owns Mac/Para control. Their unfinished branches are not silently merged here. Mainline inclusion or a reviewed adaptation will be recorded when relevant to acceptance.

## Current evidence and remaining defects

- Quote input contracts now accept either customer ID or customer name, with
  shared domain validation used by the service, capability entry and Agent tool
  validator. The registry requires items while domain validation enforces the
  customer alternative and valid quantities/prices. Missing-customer interaction
  exposes a named field; answering it reaches a separate write approval without
  calling a tool. 173 existing regressions and 43 contract/clarification checks
  passed. Natural-language planning and nested line-item clarification remain
  outstanding; this does not claim the sales benchmark scenarios are complete.

- Quote's static registry no longer claims unconditional idempotency: its
  deduplication key is optional and does not prove crash/concurrency-safe replay.
  Recovery now requires both the persisted step and current registry to permit
  replay; it never upgrades an unsafe historical step. Tests exercise the real
  quote registry with both new and legacy optimistic task records and verify
  recovery blocks without invoking the executor. 159 related regressions and
  eight queue/recovery checks passed. Durable business-write fencing and atomic
  deduplication are still required for D4.

- Quote services now resolve exact customer names and product model references
  before adding an order. Missing/ambiguous names and conflicting product ID/model
  pairs reject without leaving an order even if the caller commits afterward.
  A real SQLite case verifies canonical customer/product IDs and amount 100;
  234 related sales/tool regressions passed. This is service preparation only:
  registry support, natural-language planning, missing-input interaction and
  approval-bound resolved values remain outstanding.

- Sales quote creation previously converted missing/invalid quantities or prices
  into zero and could write an order. A dedicated input validator now checks all
  rows before touching the session: finite positive quantities and explicitly
  supplied finite nonnegative prices are required. File-backed SQLite tests
  commit after rejecting a later invalid row and verify no partial order exists;
  explicit zero-price quotes remain supported without mutating caller inputs.
  228 sales/tool regressions passed, followed by 53 facade checks including the
  zero-price case. Natural-language order/quote planning is still outstanding.

- Sales export now plans `reports.export` and reads persisted sales before writing
  an artifact. Unspecified periods are described as all recorded sales; explicit
  current-month requests preserve month boundaries. The golden export case now
  requires a real workbook, opens its verified bytes and checks one product row,
  quantity 3 and amount 1099 across three seeded sales. Three full trials passed
  this case, raising the development observation to 17/22; 31 focused regressions
  passed, including wrong-amount and missing-artifact rejection. Evidence:
  `sales-export-trials`. Actual rendered download and released-runtime acceptance
  remain pending.

- Agent report export now stores spreadsheet bytes as a task artifact rather than
  embedding binary data in its JSON receipt. The download endpoint checks the run
  owner and content hash. An HTTP test opens the downloaded workbook and verifies
  its product/amount cells, rejects another owner and rejects tampered bytes;
  124 related tests passed. The task panel now exposes an authenticated download
  action outside technical details, permits retry after failure, and only offers
  artifacts belonging to its active run. Eighteen frontend tests and the build
  type check passed. The subsequent seeded export trials above verify planner
  wiring and file contents; rendered runtime acceptance remains outstanding.

- Explicit revenue/expense recording now plans the finance tool with the canonical
  transaction type and preserved amount/counterparty. The revenue scenario uses
  exact scripted approval and asserts one committed row with revenue, 5000 and
  the named counterparty. Three trials passed, along with 26 related tests; the
  observation is 16/22. Evidence: `finance-revenue-trials`. The earlier incorrect
  income enum was rejected without a write and is retained in `finance-write-trials`.

- Model-specific inventory lookup routes to the inventory report with an exact
  model filter. The fixture contains A100=50 and B200=77; three trials returned
  only A100 with total/available quantity=50. All 132 report/tool/benchmark tests
  passed, and the full observation is 15/22. Evidence: `inventory-query-trials`.

- Ledger-month acceptance seeds balanced 25 and 75 vouchers at the month's edges
  plus a prior-month 999 voucher. Three trials returned exactly the two current
  vouchers with matching debit/credit totals and balanced=true; 18 related tests
  passed. Evidence: `seeded-ledger-trials`.

- Sales-month evidence now seeds 25 at the first instant of the month, 75 at the
  final instant, and 999 immediately before the month. All three trials returned
  total_amount=100 and quantity=2 with the expected product detail; 45 related
  tests passed. This verifies the current month's inclusive boundaries and
  excludes the prior month in the real report query. Evidence: `seeded-sales-period-trials`.

- Dashboard acceptance now seeds two products and requires product_count=2 from
  the completed report tool output. All three trials returned exactly 2; ten
  benchmark/assertion tests passed. Sales totals and ledger contents still need
  equivalent seeded-value evidence. Evidence: `seeded-dashboard-trials`.

- Sales-month summaries, ledger queries and operational dashboards now route to
  their own read tools; month boundaries include the final day. Snapshot report
  tools no longer ask for date/grouping parameters their handlers do not accept.
  Sales summaries declare the existing product grouping default. Seventy-four
  related tests passed and three trials now score 14/22 under current assertions.
  These new report scenarios still need seeded nonzero figures and output-field
  assertions before business correctness is certified. Evidence:
  `report-contract-trials`; the preceding `report-read-trials` failures are retained.

- Underspecified standalone product creation now plans only clarification and the
  deferred product step, without a customer-creation dependency. The critical
  scenario explicitly requires waiting_user, zero actual tool calls and zero
  product records; planned future creation is distinguished from execution.
  All three trials passed this scenario, with 33 related tests passing and an
  11/22 full observation. Evidence: `product-missing-trials`.

- Standalone model-based product creation preserves model/price and requires only
  the product name/model. The current service creates catalog products without
  customer ownership; mandatory customer `unit_name` was an obsolete contract in
  three registry/schema locations. Those definitions now agree. The product
  scenario passed three real database trials; 121 tool/registry/benchmark tests
  passed and the full observation is 10/22. Clarification tests now use a customer
  creation with a truly missing customer name. Legacy explicit customer-product
  binding plans still require separate product-flow review. Evidence:
  `product-contract-trials` (the earlier `product-create-trials` failed and is retained).

- Explicit destructive SQL execution requests are rejected before planning tools.
  Empty blocked plans no longer become completed merely because the executor's
  step loop is empty. The raw-SQL scenario was blocked with zero tool calls in
  all three trials; 53 related tests passed. The observation is now 9/22, and this
  narrow policy test is not a comprehensive security audit. Evidence: `sql-refusal-trials`.

- Named customer creation now enters the guarded write path without requiring
  database terminology. Both customer-create scenarios include explicit,
  parameter-bound scripted approvals and verify committed customer/contact data.
  Three trials passed both writes; the full observation is now 8/22. Thirty
  benchmark/intent/orchestrator regressions passed. This does not certify other
  business domains or HTTP approval durability. Evidence: `customer-write-trials`.

- Customer read fallback now preserves customer routing and search terms instead
  of defaulting to products. 56 targeted regressions passed. Three full trials
  now score 6/22 under the existing assertions, still not acceptance: the named
  customer case initially returned an empty list because it had no fixture.
  Dataset v2 now seeds two customers and asserts exact returned counts and
  customer/contact contents. All three trials passed both customer scenarios;
  five negative/positive assertion tests reject empty, wrong, extra and failed
  results. Full business acceptance is still outstanding. Raw outputs are retained under
  `customer-routing-trials` in the task evidence directory.
  The strengthened outcome trials are in `seeded-customer-trials`; their receipts
  describe a development observation, not mainline or installed-product acceptance.

- Checkpoint `97df226b5` fixes mutation scope, enabled benchmark execution,
  acceptance thresholds, and source/data-bound receipts. Its targeted regression
  suite passed 33 tests; generated workflow copies matched their sources.
- The task runner now uses the product `AgentOrchestrator`, recording step and
  tool-call outcomes even when routing assertions fail. It permits only explicit
  scenario approvals with matching action and parameters. This benchmark does
  not claim HTTP authorization or durable-recovery coverage.
- Three isolated observation trials of all 22 existing scenarios produced 4/22
  consecutive successes. Observation is explicitly not acceptance. The earlier
  direct-tool baseline was 5/22; those numbers measure different execution paths
  and must not be described as a product regression without further diagnosis.
- The actual planner marks clarification nodes low-risk/idempotent. A dedicated
  interaction handler now pauses these nodes before tool execution and exposes
  the question and target node in the run result. The regression uses the real
  planner node builder. The owned-run clarification endpoint now accepts missing
  required parameters, rejects changes to existing parameters and stale answers,
  and queues resumption without approving the business step. 51 related tests
  passed, including HTTP ownership, invalid-answer immutability, queue draining,
  and the separate write-approval boundary. The task panel now includes a text/
  numeric answer form, hides approval during clarification, retains failed input,
  and prevents repeat submission while awaiting refresh. Its 18 frontend tests,
  build type check and 26 backend regressions passed. Structured detail forms,
  ambiguity answers, multi-question cases, visible runtime verification and final
  business-effect acceptance remain outstanding.
- SQL queue completion now performs ownership and lease checks in the UPDATE,
  not an earlier SELECT; expired owners cannot renew. Three queue tests passed,
  including a simultaneous claim by two spawned processes and expiration before
  replacement. Business-write and AgentRun persistence fencing remain required;
  queue-row ownership alone does not prove those invariants.

Local raw trial evidence is retained at
`/private/tmp/xcmax-technical-debt-evidence-20260908/orchestrated-trials/`.
It is a dirty development-tree observation, not a release receipt. Archive the
useful evidence before task cleanup and produce clean exact-main acceptance
receipts before marking D5 complete.
