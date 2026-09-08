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
  planner node builder; 26 evaluator/orchestrator tests passed. Answer submission,
  target-parameter validation and resumption still require implementation and
  end-to-end verification before clarification can be called complete.
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
