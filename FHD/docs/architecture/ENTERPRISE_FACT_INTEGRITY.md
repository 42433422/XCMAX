# Enterprise fact authority, memory references and correction

## Authority and scope

ERP tables remain the only business authority. The existing
`enterprise_cognition` projection is a disposable, scoped read model; the
existing Persy MemoryV2 authority stores reviewed *claims*, revisions and
tombstones, not another ERP truth table. A NeuroBus event invalidates views but
is not itself evidence of a changed balance, order or customer attribute.
Never write back to ERP from an observation, prediction, vector index or memory
recall. Every read uses the existing tenant, actor, Mod and source RBAC.

An observed ERP snapshot carries `source`, `entity_type`, `entity_id`,
`tenant_id`, `actor_id`, `mod_id`, the content digest
`source_version=sha256:<64 lowercase hex chars>`, and UTC `observed_at`.
The SHA-256 covers the **selected authority state and source_last_changed**;
it is not a database transaction ID, a commit sequence or evidence for fields
omitted from the source adapter. Up to 32 prior recorded observations remain
available for audit. Recorded observation time is not an effective-business-time
ledger.

## Reconcile remembered facts (query, read only)

1. Read a visible entity through the original `enterprise_cognition.query`
   action and save its `source_version` with a memory/decision reference.
   For orders, inventory movements, fund and journal entries, and customers,
   never store an unversioned textual memory as an independently verified ERP
   fact. Unverified chat assertions remain claims.
2. Before reusing that reference for a decision, call the **same** query action
   with `entity_type`, `entity_id` and `expected_source_version`.
   The backend forces an original-source SELECT, bypassing the 30-second
   projection TTL. Historical `as_of`, scenarios and multi-entity scans cannot
   be combined with this contract.
3. `fact_verification.status=current` means that the selected current ERP
   projection matches the referenced version. A changed source returns
   `superseded`, `memory_reuse_allowed=false`,
   `requires_reconciliation=true` and model-tool `success=false`.
   Unavailable or unauthorized source returns `unknown` (or access denial),
   never a stale positive result. Mismatched/unknown versions do not emit
   operating-gap proposals in this response.
4. After a correction, save a **new versioned** source reference. Correct or
   delete the old Persy MemoryV2 claim via the existing authorized mutation
   path. Its revision history and tombstone remain authoritative to vector and
   Mem0 replay, with the existing replay/revalidation protections. Do not
   silently replace a human-reviewed claim or auto-delete based on a failed
   source read.
5. If the ERP record itself is wrong, correct it only through its original
   approved business workflow. An inventory movement is not a stock balance;
   fund/journal rows are not a verified cash balance. Already-posted financial
   entries require the original accounting reversal/counter-entry controls,
   not a memory delete. Order cancellation/returns and customer corrections
   likewise require their original audited domain operations.

A successful read-through check is **not** an execution grant. Writers must
independently recheck authorization, invariant(s), idempotency key and the
expected source version inside the original business transaction; a source
could change after this SELECT.

## Acceptance and open boundaries

Regression candidates: original and revised order quantities inside TTL;
inventory movement correction; customer-name correction; fund amount
correction; unknown/foreign tenant result; malformed hash; historical/scenario
conflict; model-tool success semantics. These must pass on the exact PR head
before being reported as executed.

This increment implements a scoped fact **verification fence** and provenance
contract, not automatic deletion of every copied memory or a global
cross-process linearizability guarantee. Remaining acceptance requires an
audited mapping from every ERP-derived MemoryV2 claim to its source identity,
automatic invalidation/review on ERP updates, source-write CAS and accounting
compensation evidence, reconciliation after dropped NeuroBus events, concurrent
multi-process/Mod/tenant tests, and independent real business/72-hour runtime
verification. Without those, do not claim end-to-end consistency or complete
reversibility.
