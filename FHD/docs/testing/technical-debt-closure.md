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
