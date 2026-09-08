# Technical debt closure acceptance

Baseline: origin/main `d7a90a8e599afa391e60ec2fef9cce9828a06cd5`.
Mainline reconciliation: merged `a114e4b4c` (including #1809 and #1808) into
this branch at `848023134`, without conflicts or changes to other worktrees.
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

- Agent task snapshots and run-event streams now re-resolve the original request's
  authenticated principal before reads and before releasing data. Session expiry,
  account/tenant/admin/Mod scope changes or validation failure close the stream;
  run ownership is also rechecked each polling cycle. A disabled ordinary-session
  user was previously accepted by Agent principal conversion; a failing regression
  now passes after the conversion rejects inactive users. The combined stream,
  route and Mod authorization suite passes 92 tests (`stream-account-revocation`),
  including revocation between read and send. Existing route fixture identities
  explicitly override the stream authorizer; dedicated tests exercise revalidation.
  Real-device expiry/revocation and streaming-load acceptance remain outstanding.
- Mainline `73861ed71` (#1806 Mac control) is included at `e42c48808`; the only
  merge conflict was the changelog, resolved by preserving both entries. At that
  checkpoint, all 47 changed backend test files pass together: 1034 passed and
  two opt-in benchmark skips. Full frontend validation passes 9827 tests with
  four live-backend skips. All 124 changed Python files pass Ruff check/format.
  The resulting 538-line Agent router violated the unchanged 500-line fitness
  limit, so event history/stream endpoints were extracted into `event_routes.py`
  with compatibility exports and the same concrete router. After extraction,
  117 route/golden/compatibility/renewal tests and all ten blocking dev guards
  pass. Existing utils-boundary warnings remain; this is not a debt-free claim.
- A deterministic SQLite interleaving exposed a claim race after resume's queue
  read: FOR UPDATE is ignored by SQLite. Resume now conditionally updates the
  observed queue state/execution count before changing the run, acquiring the
  database write lock and rejecting an intervening worker claim. The regression
  failed before the fix and passes afterward; 94 combined renewal/route/approval/
  background tests pass (`resume-fenced-regressions`). PostgreSQL concurrency
  qualification remains separate.
- Durable paused-run resume now commits session renewal, the applied control
  command, run state and queue together. Queue ownership is checked before run
  mutation; outstanding worker claims and running steps require reconciliation.
  Waiting approval steps remain waiting even if older control metadata says
  running, and are not enqueued. The HTTP resume path uses this transaction;
  memory resume shares the session identity rules. The combined renewal, HTTP,
  ownership, background-Mod and approval transaction suite passes 93 tests
  (`resume-complete-regressions`). Fault injection confirms resume rollback leaves
  the original run/session and no command or queue item, then permits retry.
  Historical missing bindings, real session/device acceptance and production
  database concurrency qualification remain outstanding.
- Explicit approval now accepts a renewed server-authenticated session only when
  user, Mod, account tenant and role exactly match the persisted binding. The
  session update, approval consumption and enqueue share the durable transaction;
  HTTP failure injection proves rollback retains the old binding and the same
  grant can retry. Memory dispatch uses the same identity validation before grant
  consumption. Session fields cannot be supplied through client runtime context.
  Eleven renewal tests and two HTTP transaction variants pass; the broader
  approval/route/background regression passes 84 tests before the final added
  legacy cases. Incomplete historical bindings remain rejected without mutation.
  Paused-run renewal, historical reconciliation and installed acceptance remain
  outstanding; this does not close the complete authorization lifecycle.
- Independent validation at `fd9cb14b3` launches each of all 268 generated
  mutants in a fresh Python process with its own temporary database/directory.
  The unmutated baseline passes 105 tests. Results: 253 assertion/test failures,
  13 survivors and two teardown errors caused by mutated resource-stack values;
  zero timeouts, no-tests cases or ResourceWarning logs. Conservatively excluding
  both teardown errors from killed gives 253/268 = 94.40%, above the unchanged
  80% threshold. This removes the forked pytest resource-warning ambiguity from
  the local evidence; current-head remote CI is still required. Per-mutant logs,
  result rows and SHA/hash-bound receipt are in `isolated-mutants/` under the task
  evidence directory. No real-model or delivery qualification is implied.
- A forced rerun of all 268 mutants after adding serving-event publication and
  missing-risk rejection tests reports 255 killed / 13 survived (95.15%). It
  still contains a pytest scandir cleanup exception, so it is not a qualifying
  replacement for clean CI evidence. Log: `mutation-composition-forced-run.log`.
  Progress parsing now also includes skipped and type-check results, consistently
  with results-line parsing; a 70/100 regression previously misreported 100% and
  now reports 70%. The five report tests pass. CI artifacts now retain the raw
  mutation run log alongside the history receipt for independent diagnosis.
- Local composition coverage adds mode selection, serving/shadow store isolation,
  unsafe-dispatch rejection, failure cleanup and reload tests. The selected DI/
  context suite passes 103 tests with 84% statement/branch coverage. A real local
  mutmut 3.7.0 run reports 251 killed and 17 survived out of 268, with zero
  no-tests mutants (93.66% under the corrected denominator). Two pytest scandir
  cleanup exceptions appear in its raw log, so this is provisional evidence,
  pending exception diagnosis and independent CI verification. No gate threshold
  or mutation source scope was reduced. Raw log: `mutation-composition-run.log`
  in the task evidence directory.
- Remote mutation run 34250327038 executed 268 reported mutants: 94 killed,
  6 survived, 168 without tests. The old 94% gate excluded uncovered mutants.
  Policy `all_reported_mutants_v2` now includes them in the denominator; replaying
  that exact log yields 35.07% and fails the unchanged 80% threshold. Regression
  tests pass. Covering the untested targets and obtaining a qualifying remote
  result remain D1 blockers; historical scores retain their original meaning.

- Read-only local desktop inventory examined 24 candidate host/Mod SQLite files.
  Only `Application Support/XCAGI/data/xcagi.db` contained Agent runs: 1750 total,
  1733 terminal and 17 waiting_user. All 17 lack Mod bindings and recorded tool
  calls; 15 lack tenant binding and 2 have tenant binding. Across these records,
  10 waiting steps were found. Absence of a tool-call record is not proof that no
  external effect occurred, and inconsistent/incomplete plans require review.
  No task was resumed, reassigned, reauthorized, or migrated. This local inventory
  does not qualify remote production, customer devices, or a renewal mechanism.

- Durable Mod bindings now snapshot the account tenant and role at authorization.
  Execution revalidates both against the host account, rejecting changes and legacy
  bindings missing this snapshot. Two negative cases reproduced execution after
  account changes before repair; 23 authorization/background-Mod regressions pass.
  Existing durable task inventory and an explicit reauthorization/migration path
  remain required before production activation; this is not migration closure.

- Mainline reconciliation on September 9: merged `75d09beff` (#1814 audit
  standard catalog) without conflicts. Architecture fitness and audit-benchmark
  SSOT validation pass; catalog validity is not product audit acceptance.
- Mod boundaries now cover task deduplication, run/task reads and controls,
  task/run collections before public limits, task streams and runtime counts.
  Backend integration at `631b1d1b0`: 960 passed / 2 opt-in benchmarks skipped,
  across 41 changed test files; 116 changed Python files pass Ruff and formatting.
- Native EventSource omitted active-Mod headers. Task streams now use credentialed
  fetch with explicit Mod/shell headers and discard events after runtime identity
  changes. Global and chat task lifecycles reset on account/tenant/Mod changes;
  delayed detail/read/control/archive responses are fenced before later actions
  and UI updates. Full frontend at `003c9fec0`: 621 files / 9818 tests passed,
  with 4 live-backend smoke tests skipped. Subsequent chat lifecycle changes have
  focused regression and build-type-check evidence, not a new full-suite result.
  Real browser interaction and installed-client identity remain unverified.

- CI run 34242372615 exposed formatting and architecture failures. Applied
  formatter to the 13 reported files; extracted tool fixture generation, market
  entitlement retrieval, SQL record decoding, and artifact download routing by
  responsibility. Local architecture fitness now passes without baseline changes.
  Focused verification: 341 formatting/contract tests, 74 entitlement tests,
  59 repository/artifact/background tests, and 36 route golden/compatibility tests
  pass. Golden snapshot now includes the existing artifact and clarification
  endpoints; no prior endpoint was removed. Cross-Mod task-id reuse has a
  reproduced negative test and returns conflict; same-Mod deduplication remains.
  These local results do not establish current remote CI or delivery acceptance.

- Frontend build type-check and all local Vitest tests pass: 620 files / 9808
  tests, with 2 live-backend smoke files / 4 tests skipped by configuration
  (`integration-frontend-all`); the focused Agent API/clarification/runtime suite
  separately passes 21 tests. These are local component/unit results, not browser
  or installed-client acceptance. Remote mutation-smoke run 34241687010 failed
  before executing mutations: uv --group dev named a nonexistent dependency
  group (dev is an optional extra). Workflow now uses --extra dev and --no-sync
  when invoking the separately installed mutmut. Frozen Python 3.11 dependency
  dry-run resolves successfully without changing the shared venv, workflow
  publication parity passes, and 7 scope regressions pass
  (`mutation-config-regression`). Actual remote mutation kill-rate result is
  still pending; no threshold or failure handling was weakened.

- Full fresh-SQLite Alembic upgrade reproduced a migration failure: the baseline
  creates current metadata, so the approval-consumption table existed before its
  new migration. Upgrade now preserves an existing table rather than recreating
  it. Full upgrade head and alembic check both pass with no new operations
  (`alembic-integration-fixed`); four approval repository/migration tests pass,
  including repeat-upgrade preservation of consumed-token replay rejection
  (`approval-migration-idempotent`). Single-head, layer ratchet, source governance,
  operational-error and broad-exception gates also pass locally. Remote checks
  for 8501466be were still queued when observed; this does not substitute for
  their eventual result or PostgreSQL/live migration qualification.

- Integration draft PR #1815 is now the single remote review channel:
  https://github.com/42433422/XCMAX/pull/1815 . Mainline be51a83a2 (#1810 metrics
  only) was merged at 5c9a3d5a1 without conflicts or other-worktree edits.
  All 108 changed Python files pass Ruff and root workflow publication --check
  reports no drift. PR CI/security/SSOT/frontend/customer-delivery jobs were
  observed queued/in progress at that head; none are claimed passed here. The
  initial Ruff file enumeration used Git's quoted non-ASCII filenames; NUL-safe
  enumeration corrected the invocation and the full check passed. Changelog
  entry is included for the product gate. The PR remains draft pending full
  acceptance; no merge, artifact activation or installed-client delivery occurred.

- Generic query verbs no longer force product_query. Product routing now requires
  product subject/model evidence; other query expressions reach the intent gate
  and remain unknown if it cannot resolve them. Three expression regressions
  verify fallback delegation, while existing explicit product/model/list cases
  still pass. Legacy tests that required bare 查询/找/看看 and 查询API to query
  products were corrected to require unknown. All 275 routing/Agent checks pass
  (`generic-query-routing`), and the 22 real business cases pass all 3 trials,
  safety=0 (`query-routing-business`, observe/gate_passed=false). This removes
  premature product routing; it does not claim the unavailable live model can
  correctly classify the deferred expressions, nor a universal model-ID grammar.

- After authentication changes, the current deterministic business run still
  passes all 22 tasks in each of 3 trials, safety failures=0
  (`current-business-trials`, source d84545fed). It remains observe mode,
  gate_passed=false, and reports tracked_source_dirty=true; it is not exact-clean
  release evidence or live-model accuracy. A three-expression synthetic live
  router probe (`live-router-smoke-corrected`) exits 2 with two model attempts,
  zero completions and StructuredOutputError: the isolated runtime reports no
  OPENAI_API_KEY/DEEPSEEK_API_KEY configured. A rule-path customer expression is
  routed to product_query before fallback. The initial smoke fixture used tool
  labels instead of route IDs; corrected IDs were rerun, preserving the original
  diagnostic output. No real-model acceptance is claimed. Environment files
  were checked only for credential presence (no values printed); other installed
  account/provider configuration still needs discovery before full live evaluation.

- Password-login web tokens now optionally carry their already-created session
  ID as a signed claim; refresh preserves it. Agent Mod binding verifies the web
  access token (under the existing feature flag) and maps the claim to a current
  host session, persisting only its row ID. Web identity lookup now uses host DB
  explicitly rather than Active-Mod business routing. Actual signed initial and
  refreshed tokens bind through host user lookup and deny after rights revocation.
  All 68 JWT/binding/Agent-route tests pass (`web-mod-binding`) and 75 auth-login
  regressions pass (`web-login-regression`). Legacy tokens without a session
  claim retain ordinary stateless authentication but need renewed login/session
  credentials for durable Mod authorization; no session is guessed by user ID.
  Real browser/mobile runtime acceptance and refresh-token replay durability
  remain distinct unverified requirements.

- Mobile Agent authentication now resolves the verified JWT session against the
  host database and reads the current active user's tenant, username and role.
  It no longer derives missing tenant scope or stale administrator access from
  token claims. A signed-token regression first reproduced empty tenant scope
  (`mobile-account-before`); current tenant 7/current normal role now win over an
  older admin token. Disabled users and expired/deleted sessions deny even without
  an Active-Mod header. Owner/session mismatch now returns authentication 401
  before Mod authorization. Sixty-two binding/route/real-dispatch checks pass
  (`mobile-account-after`), and the final 60-test route/binding suite includes
  the additional no-Mod expiry/deletion cases (`mobile-account-final`). Web
  stateless entitlement binding and full client runtime acceptance remain open.

- Mobile access JWTs already carry a signed session_id. Agent Mod binding now
  receives that field only after verify_mobile_jwt/access-type validation rather
  than treating the full Bearer JWT as a database session key. A signed-token
  regression reproduced the prior valid-token 403 (`mobile-mod-before`). Valid
  token-only mobile Mod requests now bind; refresh-as-access, tampered signature,
  signed owner/session mismatch and expired session deny. No token is persisted
  in the binding. All 61 mobile binding/route/real Mod dispatcher checks pass
  (`mobile-mod-final`). Web stateless tokens have no equivalent session claim;
  their durable authorization contract and mobile tenant derivation remain to
  complete before claiming full client compatibility.

- The three-database inventory test now starts the actual AgentTaskDispatcher
  inside a new process, with default host run/queue repositories and the real
  orchestrator/executor/business guard. An already-approved persisted task writes
  one movement to A and records matching completed run/queue states; a new task
  after revocation records matching failed states without extra writes. Recovery
  additionally uses a separate process that claims and exits before business
  execution, then advances its stored expiry deterministically. The replacement
  dispatcher records recovery_count=1 and preserves the same result/isolation.
  Thirty combined checks passed (`inventory-mod-dispatch-recovery`); after
  replacing the initial simulated departed owner with a real exited claimant,
  the recovery scenario passed (`inventory-mod-departed-claimant`). Approval JWT
  validation is covered separately: this fixture stages already-approved work.
  This still does not certify external side-effect reconciliation or installed
  customer UI/release acceptance.

- Registered inventory execution now has real three-database acceptance tests:
  host, authorized Mod A and unauthorized Mod B contain identical product/model
  and warehouse names. Both a fresh thread and a spawned process restore the
  persisted session binding and use the actual executor/router/InventoryService
  and normal database routing to write exactly one 50-unit movement/ledger into
  A, leaving host/B untouched. Revoking the session's rights then starting another
  worker denies execution without extra writes. No business tool/session factory
  is mocked; test DB-manager bypass only selects the isolated fixture URLs.
  Both scenarios pass (`inventory-real-mod`) and all 30 related scope/guard/
  fencing tests pass (`inventory-mod-regression`). The spawned process exercises
  persisted authorization and real business execution, not full dispatcher
  crash/requeue/UI acceptance; those broader delivery requirements remain.

- Agent session-authenticated Mod selection now binds a host session row ID,
  actor ID and entitled Mod ID into reserved runtime context. Creation strips
  caller-supplied bindings; continuation rejects binding replacement. Before
  each registered tool call, the executor rechecks the host session's owner,
  expiry, active user and current entitlement/public bundled catalog, restores
  Mod context, and resets it after execution. No login credential is persisted.
  Actual SQLite tests cover owner/Mod mismatch, API-principal binding, fresh
  worker context/reset, revocation with zero further tool calls, expiry,
  disabled user and deleted session. All 71 relevant checks pass
  (`agent-mod-binding-final`). This is a session-backed implementation, not full
  acceptance: token-only Mod clients need a durable reauthorization contract,
  aliases/admin entitlement policy need compatibility review, and real business
  writes into the restored Mod DB plus process-restart/customer acceptance remain.

- ModContextMiddleware now opens an empty, ContextVar-backed entitlement scope
  for each HTTP request and resets it on normal/error exit. Identity, rights,
  administrator checks, persistence and sync use the current immutable snapshot;
  scoped set/clear cannot overwrite another request's state. Non-HTTP startup
  retains legacy process-cache behavior. A barrier-driven overlapping A-admin /
  B-normal request test verifies separate identities, Mod sets and admin flags,
  A failure/clear cannot clear B, AnyIO synchronous handlers inherit the correct
  request identity, and the enclosing startup state is restored unchanged. All
  259 entitlement/middleware/Agent-route tests pass
  (`entitlement-concurrency-final`). This establishes HTTP context isolation;
  new detached background workers still require explicit authenticated Mod
  binding and revalidation, and legacy non-HTTP global consumers remain to audit.

- Session-row entitlement restoration now requires expires_at strictly after
  UTC now, matching persisted UTC-naive session timestamps and denying the exact
  expiry boundary. Real SQLite tests reproduced expired and exactly-expired
  grants despite a fresh entitlement TTL (`entitlement-expiry-before`); both now
  deny and clear cached rights, while a future expiry retains access and all
  session rows remain intact. The expanded 158-test suite passes
  (`entitlement-expiry-final`). Legacy tests now retain real ORM column
  definitions instead of replacing the Session model with MagicMock. This
  verifies row restoration, not every remote-token authentication path or
  concurrent/global-cache access; those and durable Mod task binding remain.

- Entitlement sync's session-keyed TTL previously returned the last account's
  process-global entitlement set. TTL reuse now restores the requested session
  row; missing/failed restoration in TTL and both market fallback paths clears
  stale state and returns no rights. Three tests reproduced wrong-account rights
  before the fix (`entitlement-session-before`). A real SQLite test alternates
  A/B session rows and verifies a persisted revocation overrides an unexpired
  TTL; all 55 entitlement tests pass (`entitlement-session-real-db`). This fixes
  sequential cache reuse and failed-restore fallback only. Global state under
  concurrent requests, session expiry validation, and durable task-to-Mod
  authorization binding remain unresolved and are not certified by these tests.

- Unified-task HTTP endpoints no longer translate an authenticated empty tenant
  into the repository's unrestricted None selector. Detail/read/archive, lists,
  stream and runtime task summaries pass the exact scope; legacy run backfill
  filters before limit. Unified creation also scopes deduplication and its
  fallback run lookup. Five negative HTTP tests first reproduced disclosure or
  mutation (`empty-task-tenant-before`); the corrected suite passes 47 checks,
  including separate same-ID scoped/unscoped creation and same-scope replay
  (`empty-task-tenant-final-corrected`). The first new creation test incorrectly
  expected 200 although this tool requires approval (202); its expectation was
  corrected without changing approval policy. Full Mod entitlement restoration
  remains pending; this closes another authenticated-tenant entry-point gap.

- Default run, queue and approval-consumption repositories now use
  HostSessionLocal explicitly. A real two-SQLite regression first reproduced a
  Mod request enqueue that a fresh background thread could not claim
  (`host-storage-before`); after the change that thread reads/claims the run,
  replay consumption remains denied outside Mod context, and the Mod database
  contains no scheduling/approval tables. Business SessionLocal still selects
  the Mod database. All 67 approval/crash/guard/route regressions passed
  (`host-storage-regressions`), plus 12 initial repository checks. Explicitly
  injected repository factories remain supported. Before production activation,
  inventory and reconcile any historical scheduling/approval rows in Mod
  databases; no legacy rows were moved or discarded here. Verified Mod entitlement
  restoration for actual business execution is still pending, so this is not
  acceptance of the complete customer-Mod workflow.

- SQL run/queue repositories now expose an initialized transaction context with
  explicit caller ownership rules. Approval and business-write guards use it
  instead of private schema/session methods; approval's repository inputs and
  result are typed. All 62 transaction/crash/guard/route checks passed
  (`public-transaction-boundaries`), followed by 44 checks after adding concrete
  type imports (`typed-approval-transaction`). This removes the recently added
  private transaction dependency, not the wider legacy dynamic-import D3 debt.

- Three task creation surfaces now share authenticated_runtime_context: run,
  unified task and observed-tool creation drop caller tenant IDs and use only the
  principal's tenant. Reinspection found earlier text incorrectly claimed the
  unified-task removal had landed; it had not, and this change actually wires it.
  Two HTTP cases verify forged tenant removal/override while preserving source;
  all 38 route checks passed (`authenticated-task-context`). Active-Mod middleware
  only normalizes the header, so it cannot alone serve as an entitlement proof
  for durable Mod restoration; that authorization path remains pending.

- SQL tenant-list regression now seeds two older target runs behind 205 newer
  same-user/other-tenant runs, plus an unscoped legacy run and a different user's
  target-tenant run. A fresh repository returns the correct target records at
  limits 1/2 across streaming batches, isolates empty tenants, and handles zero
  limit/missing tenants. All 39 route/repository checks passed
  (`sql-tenant-streaming`). This establishes filtering correctness, not indexed
  query performance on production-scale historical data.

- Non-admin run access now checks both user and persisted tenant. Seven HTTP
  regressions reject same-user cross-tenant detail/events/control/approval access
  without mutation or content disclosure. The public run list filters by tenant
  before limit; repositories accept a tenant filter, with SQL streaming legacy
  JSON-backed identities until enough matching rows are found. All 38 route/run
  repository checks passed (`tenant-run-access-final`). Dedicated SQL tenant-list
  pagination coverage and indexing/performance remain to verify; administrator
  access retains its existing explicit exception.

- Runtime ownership changes now raise a distinct exception. The resume HTTP
  endpoint translates it to a public 400 response instead of an unhandled server
  error. Its route test verifies unchanged full task state, no enqueue and no
  control command; all 31 route/context checks passed (`resume-tenant-http`).
  Retry HTTP accepts no runtime-context body, while its underlying lifecycle
  retains the ownership check. Principal/run tenant matching and active-Mod
  binding remain separate pending authorization work.

- Approval, synchronous/background resume and retry now share runtime-context
  tenant binding. Resume validates before creating its control command, so
  rejected tenant changes leave no command or run mutation; retry creates no new
  run. Three direct lifecycle tests assert unchanged full persisted state, no
  command and no extra run; all 35 route/lifecycle/dispatcher checks passed
  (`continuation-tenant-binding`). Task creation's second API also drops unverified
  client tenant IDs. HTTP error presentation for resume/retry and principal/Mod
  ownership across all endpoints remain to be completed.

- Approval continuation previously merged client runtime_context over persisted
  tenant identity. HTTP now rejects a differing tenant before consumption, and
  approval-state mutation repeats the check inside the durable transaction. A
  route regression verifies no staging/enqueue/consumption after tampering and
  a valid retry with the same grant. Task creation also drops client tenant IDs
  when the authenticated principal has no tenant. All 38 route/recovery checks
  passed (`approval-tenant-binding`). Resume/retry and other runtime-context
  mutation paths, full principal/run tenant checks, and active-Mod identity binding
  still require audit; this does not certify every authorization boundary.

- A fresh thread now exercises the real inventory tool executor/registered router
  against SQLite with two tenants' identical product models and warehouse names.
  Runtime tenant 2 writes only its own canonical IDs and one 50-unit movement;
  tenant 1 remains untouched. Reusing that thread without a tenant fails without
  inheriting the previous scope or adding a second movement. The end-to-end test
  passed (`inventory-background-tenant-final`). Warehouse codes remain globally
  unique in the current schema: the initial duplicate-code fixture failed and
  distinct codes retain same-name resolution coverage; this does not claim
  tenant-scoped code uniqueness or active-Mod background restoration.

- Tool execution restored integer tenant context only for business_db, omitting
  inventory. Inventory now restores a supplied runtime tenant before dispatch,
  then restores the caller context afterward; invalid IDs block the tool call.
  Integer parsing also rejects fractional IDs instead of truncating them to a
  different tenant. All 45 executor/business-guard checks passed
  (`inventory-runtime-tenant`). These executor tests observe the dispatch context;
  fresh-thread real-database end-to-end tenant selection and active-Mod restoration
  still need explicit verification, as do other SQL tool families.

- Full integrated business observation retains 22/22 across three trials after
  recent mainline, routing and inventory changes (`integrated-business-trials`).
  Returned-value assertions previously equated a missing path/field with explicit
  null and list fields allowed bool/int equality. They now require present paths
  and fields with distinct boolean types. Eight negative/positive cases verify
  this boundary; all 20 assertion/benchmark checks pass and the strengthened full
  three-trial rerun remains 22/22 with zero defined safety failures
  (`strict-business-trials`). Both reports explicitly have observe mode and
  gate_passed=false; neither is release or model acceptance.

- Inventory out/transfer previously subtracted unchecked quantities, allowing a
  negative request to increase source stock. All three movement methods now use
  one finite-positive-number validator before opening the business session,
  preserving inbound's existing public error. Real DB tests cover eight invalid
  values across in/out/transfer and verify stock/available remain 100 with zero
  movement rows after commit/readback. All 92 inventory/ownership checks passed
  (`inventory-quantity-contracts`). Warehouse validity and concurrent stock-update
  invariants remain separate from quantity validation and lease fencing.

- Inventory out and transfer now use the same worker ownership guard as inbound.
  Real SQLite checks cover all three operations with active/expired claims in
  shared and separate Mod databases: expired operations preserve initial ledgers
  with zero new movements; valid out reduces 100 to 50, transfer produces two
  50-unit warehouse balances and two movements. All 73 guard/inventory/dispatcher
  checks passed (`inventory-all-movement-fences`). Only inbound currently has
  abrupt-process and concurrent takeover tests; other tools and business receipts
  remain outstanding, so this is not full D4 acceptance.

- Inbound crash coverage now exits the child with os._exit(73) immediately after
  successful business commit, leaving the persisted step running without a result.
  A replacement claim invokes the real orchestrator recovery with an optimistic
  historical idempotent flag: current inventory registry prevents replay and
  marks manual_reconciliation_required, with zero executor calls. Fresh business
  sessions retain exactly one movement and quantity 50 for shared/Mod databases.
  All 13 guard/dispatcher checks passed (`inbound-commit-lost-receipt`). This proves
  no automatic duplicate write on unknown completion; it does not implement
  durable business-result lookup or automatic successful reconciliation.

- Spawned inbound workers now pause after flushing an actual 50-unit ledger and
  one inventory transaction, before commit. A separate connection with a clock
  beyond lease expiry cannot take over while that transaction is held; after
  commit it can recover the claim. Fresh business reads show zero before commit
  and one 50-unit movement afterward, for both shared and separate Mod databases.
  Eleven checks passed (`inventory-commit-takeover-final`). Child workers use the
  same explicit tenant scope as seeded business data; the initial missing-scope
  run failed before business writing and is retained as diagnostic evidence.
  Recovery execution/idempotent business receipts are not covered by this claim
  test, and must still prevent duplicate inbound after a lost completion receipt.

- SQL dispatcher execution now carries a scoped ownership context. Inventory-in
  acquires a conditional ownership write lock before business queries/writes:
  same-engine uses the business transaction, separate Mod engines hold the queue
  transaction while the existing business commit occurs without rerouting data.
  Four real SQLite cases verify active/expired ownership with shared/separate
  databases: valid writes one ledger/transaction at 50, expired writes neither.
  All 61 inventory/dispatcher checks passed (`inventory-worker-fence`). This is
  inbound-only: concurrent takeover during commit, abrupt cross-database process
  failure, out/transfer and other tools still require work. The ownership lock
  is not a distributed atomic commit or replay-safe business receipt.

- Label slots now have a focused parser that removes count/specification spans
  before model extraction. Requests with only 20张 or 28规格 preserve a missing
  model; reversed count/model order extracts the actual model, and multiple
  models do not silently select the first. Existing compact model/spec syntax
  remains supported. All 243 normal-router checks passed
  (`label-model-boundaries`). This is input extraction evidence, not printer
  side-effect or multi-product printing acceptance.

- Normal-chat routing independently treated any 打印 as shipment before reaching
  labels. It now requires shipment words or the existing print-model/spec syntax;
  打印标签 reaches label_print, quantity requires a count unit rather than taking
  digits from the model, and negated printing returns unknown without routing a
  write. Tests use actual 打印标签 instead of substituting 商标 to hide the defect;
  the old 打印一下=shipment assertion now requires unknown for the unspecified
  object. All 254 normal-router/intent regressions passed (`normal-label-negation`).
  This verifies routing only, not physical printer execution or installed UI.

- RuleEngine now honors complete configured quick commands before broad keyword
  matches, preventing printer-list navigation from becoming label printing and
  WeChat contacts from becoming template lookup. Longer requests still use the
  existing rule path and negated printing remains blocked. Thirty-two focused
  and 179 existing intent-service checks passed. An isolated full rule CLI run
  retains core 24/24 and improves semantic 19/73 to 26/73
  (`exact-command-rules.json` and log), with the complete failure report retained.
  This fixes command precedence, not the remaining semantic cases or live-model
  acceptance; benchmark labels and thresholds were not changed.

- Isolated rule CLI rerun used a temporary SQLite database with the real
  PurchaseUnit schema and an empty customer fixture. No ERROR/WARNING/Traceback
  occurred; core remains 24/24 and semantic 19/73 (`isolated-intent-rules.json`,
  matching log). Thus missing PostgreSQL does not explain this fixture's score;
  this remains a rule-layer result, not actual model accuracy. Inspection also
  found failure reports silently truncated each tier at 30 and omitted expected
  route/slots. Reports now retain all failures and their full expected contract;
  a 41-failure regression verifies count/content, with seven runner tests passing
  (`complete-intent-failures`). The existing isolated report predates that report
  fix and still contains the old truncated failure list.

- Latest main includes #1809's real-model evaluator and attendance upgrade work;
  the previously missing evaluator is now present, not an outstanding branch
  dependency. All 88 selected intent/security/approval/fencing route regressions
  passed after merging (`mainline-reconciliation`). A direct rule CLI run reports
  core 24/24 and semantic 19/73 with an OK ratchet, but also encountered unavailable
  localhost PostgreSQL while resolving purchase units. Its report
  `mainline-intent-rules.json` is diagnostic only, not clean-environment acceptance
  or real-model accuracy. Isolated rule rerun and actual model evidence remain.

- A spawned stale worker now reads a run and waits while another process expires
  its lease, claims the task and saves a new paused state. Releasing the old worker
  rejects its failed-state write; fresh readback retains paused state and the
  replacement owner. All 10 queue/dispatcher/fencing tests passed
  (`process-worker-fencing`). Business session inspection confirms SessionLocal
  resolves the active Mod database, so business fencing must preserve that data
  boundary rather than assume the queue table exists in every business database.
  Actual business commit fencing remains unimplemented.

- SQL dispatcher workers now receive a claim-bound run repository. Every run
  save conditionally locks the queue row using claimed state, owner, execution
  count and unexpired lease in the same transaction as run/task persistence.
  Failure receipts use the same guarded repository; lease-loss errors do not
  trigger an unguarded failed-run overwrite. SQLite tests verify expiry before
  replacement, takeover with a reused owner string, preservation of the new
  paused state, and rejection of saving another run. All 37 dispatcher/repository/
  route checks passed (`worker-run-fencing`). This guards run/task saves only;
  multi-process stale-save contention, control-command writes and actual tool
  business transactions still require coverage and fencing before D4 closes.

- Spawned-process approval tests now call the actual transaction service and use
  os._exit after flushing the queue before commit, or immediately after commit
  before response/notification. Verified exit codes distinguish both crash sites.
  Fresh sessions observe all-or-nothing state: pre-commit death permits the same
  grant to retry, post-commit death rejects replay and leaves a pollable queue.
  A replacement worker claims exactly once without notification; a second cannot
  claim it. All 32 HTTP/transaction checks passed (`approval-process-death`).
  This tests abrupt application process exit on SQLite, not power-loss durability
  or business-write recovery; those broader boundaries remain outstanding.

- The SQL-backed HTTP approval route now revalidates the signed grant against
  a freshly read run and commits consumption, run/task staging and enqueue in
  one transaction. It checks the queue shares the same engine, uses row locking
  plus a payload comparison, and notifies the dispatcher only after commit.
  A real SQLite HTTP test injects failure after queue flush: 503, no notification,
  no consumption or queue row, and the waiting run retained. The same grant then
  succeeds once and replay is rejected. All 39 route/repository/transaction
  checks passed (`atomic-http-approval-final`). In-memory test repositories retain
  their explicit non-durable path. Forced process death, concurrent control
  changes, post-commit response loss, stale-worker business fencing, and exact-main
  delivery remain to be verified; private repository transaction access should
  converge on an explicit unit-of-work interface during D3 cleanup.

- Run/task persistence and queue enqueue now expose caller-owned-session methods;
  existing standalone methods use the same implementations. File-backed SQLite
  fault tests flush approval, run/task and queue writes and interrupt after each
  stage: fresh sessions observe no approval/queue and the original waiting run
  and task. Before commit a separate connection sees no dispatch; on successful
  commit the worker can claim the run. Nine transaction/repository checks passed
  (`shared-approval-transaction`). This is transaction infrastructure only: the
  HTTP approval endpoint still needs to use a shared transaction, with fresh
  state validation and post-commit dispatcher notification.

- Real signed grants now have process-level evidence using the default production
  repository factory with an isolated SessionLocal: two spawned processes yield
  one consumption and one replay rejection; a third fresh process rejects a
  renewed token for the same action. Exactly one DB row remains. The actual
  migration upgrade builds a usable unique-JTI table and downgrade removes it
  in isolated SQLite. All 29 repository/HTTP checks passed
  (`signed-approval-restart`). This does not test the full migration chain or
  production migration, nor close the consumption/stage/enqueue crash window.

- Signed approval consumption now uses the durable repository instead of Redis
  with process-local fallback. The HTTP continuation endpoint returns 503 on
  storage failure before staging or enqueueing the run. An unmigrated SQLite
  endpoint test verifies waiting state, zero enqueue/tool calls, and successful
  retry with the same grant after storage recovery; 27 route/repository tests
  passed (`approval-storage-retry`). Migration execution, signed-grant process
  restart coverage and atomic consumption/run/queue coordination remain pending.

- Added a durable approval-consumption table and atomic insert repository, with
  migration `2026_09_08_agent_approval` after the verified single migration head.
  Two spawned processes compete for the same JTI: exactly one commits, and a new
  repository after process exit still rejects replay. Missing storage raises an
  error rather than permission; both tests passed. This is not yet the production
  approval guard: wiring, migration execution, grant-level restart coverage and
  queue/run persistence coordination remain required.

- Generated shipment spreadsheets now become hash-verified run artifacts exposed
  through the existing owned-task download endpoint and UI action. Only generated
  `.xlsx` paths inside the shipment output directory are copied. The golden case
  opens the stored workbook and asserts model/name/3 tins/spec 12/36 total/900
  amount in actual cells; all three trials retain 22/22 (`shipment-workbook-trials`).
  A real generation-to-HTTP-download test checks customer and all business cells
  and rejects another user; 35 route/assertion checks passed. Rendered installed
  UI and exact-main delivery remain pending, alongside D3/D4.

- Shipment record IDs are now copied while the DB session is open, avoiding
  DetachedInstanceError after the context's final commit/close. A real expiring
  SQLAlchemy-session test verifies the returned ID reads the persisted record.
  The legacy generator accepts an explicit output directory; the app now puts
  workbooks and labels beneath its writable data directory instead of resources.
  Three full trials reach 22/22 with shipment record assertions for 3 tins, spec
  12, quantity 36 and amount 900 (`shipment-output-scope-trials`); 18 focused checks
  passed. This remains a development observation: workbook cell/content and
  authenticated task download acceptance are pending, as are D3/D4/D5. Earlier
  `shipment-session-trials` outputs under this worktree's resources must be
  archived/removed as task-owned evidence during final cleanup, not confused
  with current app-data outputs.

- Explicit shipment-document requests now use the existing order parser rather
  than falling back to product search. Bare requests pause with zero tool calls;
  their deferred generation node is distinguished from actual execution. Three
  trials pass that interaction, observation 21/22 (`shipment-routing-trials`).
  The full generation case now has explicit parameter-bound approval and seeded
  customer/product records. It exposes `DetachedInstanceError` for ShipmentRecord
  during real generation (`seeded-shipment-trials`), and remains failed. Parser
  preservation and no-parser/no-LLM behavior for bare requests passed focused
  tests. File contents, download, structured missing-product answers and the
  detached-session defect still require completion.

- Named stock-in now enters the inventory tool before generic database-write
  fallback, preserving model and quantity. Contracts accept IDs or exact names;
  absent warehouse names are requested through the existing form and answering
  still stops at independent high-risk approval. The real golden case starts
  with stock 10, approves inbound 50 and verifies one ledger at 60 plus one `in`
  transaction with before=10/after=60. Three full trials passed, observation 20/22
  (`named-inbound-trials`), and 197 contract/interaction/inventory checks passed.
  These tests do not certify concurrent stock updates or installed-runtime use.

- Stock-in service/dispatcher now accept exact model and warehouse names in
  addition to IDs, resolve them before writes, and reject duplicate names or
  conflicting ID/name pairs. Real SQLite tests verify valid names write the
  canonical product/warehouse IDs and quantity 50, while rejected references
  leave both ledger and transaction tables unchanged; 148 regressions passed.
  Tool-contract alternatives and warehouse clarification remain outstanding.

- Stock-in now rejects nonpositive, nonfinite and malformed quantities before
  opening a write session, and requires an existing active destination warehouse.
  Real SQLite tests verify missing/inactive warehouses produce no ledger or
  transaction rows and valid quantity 50 is reflected in both. 143 inventory/tool
  regressions passed. Natural-language model resolution and warehouse selection
  remain outstanding; the stock-in golden case is not yet accepted.

- Order requests now use an approved `sales.create_order` action that composes
  existing quote/confirm services in one DB transaction. Missing price is asked
  explicitly without replacing the supplied quantity. The golden order case now
  requires confirmed state, one item, quantity 10, price 50 and amount 500; merely
  creating a quote no longer qualifies. Three full trials passed, observation
  19/22 (`confirmed-order-trials`), with 122 related checks. A separate file-backed
  SQLite fault test forces confirmation failure after quote creation and verifies
  fresh sessions see zero orders, items or newly bridged customers; 142 sales and
  existing end-to-end regressions passed. This action is non-idempotent and does
  not claim automatic recovery after an unknown commit result.

- Named quotation requests now preserve the customer/model and ask only for
  missing per-item quantity/price fields. Answers cannot replace known values,
  invalid answers leave the task unchanged, and resumption stops at independent
  write approval. The real benchmark seeds the customer-management PurchaseUnit
  and product, supplies explicit answers and parameter-bound approval, then checks
  exactly one quote and item with quantity 2, price 50 and amount 100. Sales quote
  now bridges the existing PurchaseUnit into the sales Customer model only after
  all product references validate; rejected products leave no bridge/order rows.
  Three full trials passed this case, observation 18/22. 104 backend checks and
  three form tests passed. Evidence: `named-quote-bridge-trials`; the preceding
  failed `named-quote-trials` records exposed the customer-model mismatch.
  This does not certify order confirmation, multi-product natural-language
  parsing, ambiguous-customer selection or installed-runtime behavior.

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
