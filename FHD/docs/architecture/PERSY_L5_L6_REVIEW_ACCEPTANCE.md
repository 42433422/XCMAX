# Persy L5–L6 incremental acceptance

Depends on the Persy L4 relation-recall branch. No duplicate authority, graph database,
or model-selected conflict winner is introduced.

## Implemented increment

- Explicit typed singleton relations are checked for overlapping validity in the existing
  MemoryV2 write transaction. A conflicting candidate remains pending; confirmation or
  active correction must resolve the conflict first. Pending conflict references are
  advisory snapshots; confirmation always rechecks authority. Non-overlapping half-open
  intervals and explicitly many-valued relations remain legal.
- Existing read-side conflict withholding still protects older inconsistent records.
  No arbitrary fact is inferred to be single-valued. Do not confuse an advisory name
  match with independently verified entity identity.
- Regression coverage exercises simultaneous confirmations, review followed by a
  valid successor, and shared enterprise memory visibility, correction and revocation
  across authorized actors, with personal, tenant and Mod isolation.

## Remaining acceptance gates (not claimed complete)

| Gate | Required evidence |
| --- | --- |
| L4 | Real model extraction, temporal/identity quality, desktop historical review, representative corpus, CI and independent runtime evidence |
| L5 | Review workflow usable from desktop and agent tools, revision-bound approval, cross-process races, conflict resolution and tombstone/replay on disk, expiry/retention policy and real business correction cases |
| L6 | At least two actual Employee Runtime identities, original authorized handoff and outcome references, same-tenant shared memory under correct Mod and capability ACL, source revision revalidation before execution, denied cross-scope attempts, real business independent verification and audit |
| Release | Exact commit, CI, Windows/macOS evidence, production deployment and repeatable real-model acceptance |

Never infer the L6 grade from a passing isolated unit test or from the existence of a shared graph.
