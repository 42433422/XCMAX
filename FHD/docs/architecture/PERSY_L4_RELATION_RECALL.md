# Persy L4 relation and revision recall: evidence boundary

This increment extends the existing Persy / MemoryV2 / Mem0 authority rather than creating another memory database.

- Model extraction can retain explicitly mentioned typed endpoints; unknown or non-verbatim endpoints cannot create graph bridges.
- Current retrieval follows bounded 0–3-hop paths within one authorized memory scope, with source record IDs and revisions for every step. A path is not an assertion of transitive truth or confirmed identity. Pending, rejected and deleted memories are excluded from retrieval.
- An explicit `as_of` on the existing memory query API provides read-only historical revision review. It does not supply planner chunks or reinforce records; current revocation also prevents time-travel recall. Revision time is not real-world fact validity. Legacy timestamps without recorded UTC evidence are reported unavailable, not guessed.
- The existing graph exposes revision timestamps and partitions same-named entity nodes by scope. No new graph database or duplicate authority is introduced.
- The original Mem0 and user-vector recall paths also use authoritative graph evidence. Every path step is checked against the current source revision, and graph-only hits do not masquerade as vector scores.
- Explicit reviewed values can declare `relation_validity: {effective_from, effective_until}` (offset-aware ISO timestamps, half-open) and `relation_cardinality: "one"`. Current recall suppresses out-of-window records and quarantines conflicting single-valued assertions without silently selecting one. `effective_at` is an explicit review-only business-time query; absent or ambiguous effective intervals are not inferred from recording dates. Explicit entity IDs do not merge with name-only candidates.
- The existing Persy memory view includes a read-only relation/record-time/business-time review panel and the original correction form can edit explicit business intervals and cardinality. Editing a changed entity name/type does not silently preserve an old entity ID.
- Production L4 remains unaccepted until real-model typed extraction, identity quality, time-validity and conflict integration, Agent Runtime and cross-process revision races, UI historical review, and representative large-corpus performance are independently verified.

Suggested acceptance: focused relation/temporal and existing governance tests; real model + real business cases; ACL/revocation/tenant regression; capture the exact commit, real runtime evidence, and CI results. The code changes alone are not L4 production acceptance.
