# Persy L4 relation and revision recall: evidence boundary

This increment extends the existing Persy / MemoryV2 / Mem0 authority rather than creating another memory database.

- Model extraction can retain explicitly mentioned typed endpoints; unknown or non-verbatim endpoints cannot create graph bridges.
- Current retrieval follows bounded 0–3-hop paths within one authorized memory scope, with source record IDs and revisions for every step. A path is not an assertion of transitive truth or confirmed identity. Pending, rejected and deleted memories are excluded from retrieval.
- An explicit `as_of` on the existing memory query API provides read-only historical revision review. It does not supply planner chunks or reinforce records; current revocation also prevents time-travel recall. Revision time is not real-world fact validity. Legacy timestamps without recorded UTC evidence are reported unavailable, not guessed.
- The existing graph exposes revision timestamps and partitions same-named entity nodes by scope. No new graph database or duplicate authority is introduced.
- Production L4 remains unaccepted until real-model typed extraction, identity disambiguation, temporal business validity, conflicting facts, Agent Runtime evidence integration, cross-process revision races, UI historical review, and representative large-corpus performance are independently verified.

Suggested acceptance: focused relation/temporal and existing governance tests; real model + real business cases; ACL/revocation/tenant regression; capture the exact commit, real runtime evidence, and CI results. The code changes alone are not L4 production acceptance.
